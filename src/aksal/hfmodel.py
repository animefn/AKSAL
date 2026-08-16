"""Bring your own acoustic model, from Hugging Face.

The pipeline needs exactly three things from a model, and nothing else:

  * a KANA vocabulary -- alignment units are moras, so the tokens must be kana
  * a BLANK index     -- CTC's "no output" symbol
  * 20 ms frames      -- wav2vec2 downsamples 16 kHz audio by 320

Any CTC model meeting those aligns as well as the built-in one. That is why
this exists: the default is the best of the ones measured, not the last word,
and a model released next year should not require a code change.

Every one of those three is CHECKED rather than assumed, because each fails
silently otherwise. A model whose vocabulary is kanji-mixed produces plausible
nonsense -- measured: one popular Japanese ASR checkpoint has 2,155 kanji
tokens against 74 kana, and forcing mora units through it aligns to the wrong
sounds without erroring. A wrong blank index makes one kana mean "no output"
everywhere it occurs. A different stride silently scales every timestamp.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

KANA_RANGE = ("ぁ", "ヿ")      # hiragana + katakana
MIN_KANA_SHARE = 0.5


def _model_identity(model_id: str, model) -> str:
    commit = getattr(model.config, "_commit_hash", None)
    if commit:
        return f"hf:{model_id}@{commit}"
    path = Path(model_id)
    if path.exists():
        digest = hashlib.sha256()
        items = [path] if path.is_file() else sorted(
            p for p in path.rglob("*") if p.is_file())
        for item in items:
            stat = item.stat()
            name = item.name if path.is_file() else str(item.relative_to(path))
            digest.update(name.encode("utf-8"))
            digest.update(f":{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        return f"local:{path.resolve()}@{digest.hexdigest()}"
    # Some old Hub configs do not retain their resolved commit. Include the
    # complete config rather than pretending the bare repository ID is a fixed
    # revision; users can also pass an explicit local snapshot for strict pinning.
    config_hash = hashlib.sha256(
        model.config.to_json_string().encode("utf-8")).hexdigest()
    return f"hf:{model_id}@config-{config_hash}"


def _cached_first(cls, model_id: str, **kwargs):
    """Load without touching the network when the checkpoint is cached."""
    try:
        return cls.from_pretrained(model_id, local_files_only=True, **kwargs)
    except OSError:
        return cls.from_pretrained(model_id, **kwargs)


def _config_dict(model_id: str) -> dict:
    from transformers.configuration_utils import PretrainedConfig

    try:
        got, _ = PretrainedConfig.get_config_dict(
            model_id, local_files_only=True)
    except OSError:
        got, _ = PretrainedConfig.get_config_dict(model_id)
    return got


def looks_like_kana_vocab(vocab: dict[str, int]) -> tuple[bool, float]:
    """Is this a kana model? Returns (verdict, share of single-kana tokens)."""
    singles = [t for t in vocab if len(t) == 1]
    if not singles:
        return False, 0.0
    kana = sum(1 for t in singles if KANA_RANGE[0] <= t <= KANA_RANGE[1])
    share = kana / len(singles)
    return share >= MIN_KANA_SHARE, share


def load_into(aligner, model_id: str, log=print) -> None:
    """Load a Hugging Face CTC model and attach it to `aligner`."""
    import warnings

    from transformers import (AutoFeatureExtractor, AutoModel,
                              AutoModelForCTC, AutoProcessor,
                              PreTrainedTokenizerFast,
                              Wav2Vec2FeatureExtractor)
    log(f"  acoustic model: {model_id}")

    # Checkpoints uploaded years ago bake `gradient_checkpointing` into their
    # config. It is a training-time memory tradeoff, inert here, and dropped in
    # transformers v5 -- so the config is cleaned before the model is built.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*gradient_checkpointing.*",
                                category=UserWarning)
        cfg_dict = _config_dict(model_id)
        if cfg_dict.get("model_type") == "dual_ctc":
            try:
                processor = _cached_first(AutoFeatureExtractor, model_id)
            except OSError:
                # DistilHuBERT's dual-CTC repository intentionally contains no
                # preprocessor config. Its reference scorer uses ordinary
                # Wav2Vec2 zero-mean/unit-variance waveform normalisation.
                processor = Wav2Vec2FeatureExtractor(
                    feature_size=1,
                    sampling_rate=16_000,
                    padding_value=0.0,
                    do_normalize=True,
                    return_attention_mask=False,
                )
                log("    no feature extractor in the repository; using "
                    "16 kHz Wav2Vec2 normalisation")
            tokenizer = _cached_first(
                PreTrainedTokenizerFast, model_id, subfolder="kana_tokenizer")
            model = _cached_first(
                AutoModel, model_id, trust_remote_code=True)
            output_key = "kana_logits"
        else:
            processor = _cached_first(AutoProcessor, model_id)
            tokenizer = getattr(processor, "tokenizer", None)
            if tokenizer is None:
                raise SystemExit(
                    f"{model_id} has no CTC tokenizer. ASKAL needs a model "
                    "that maps audio frames directly to kana tokens.")
            model = _cached_first(AutoModelForCTC, model_id)
            output_key = None
    model.eval()

    vocab = tokenizer.get_vocab()
    ok, share = looks_like_kana_vocab(vocab)
    if not ok:
        raise SystemExit(
            f"{model_id} does not look like a kana model: only "
            f"{share:.0%} of its single-character tokens are kana.\n\n"
            "  Alignment units here are MORAS, so the model must emit kana. A\n"
            "  full ASR model that writes kanji will align to the wrong sounds\n"
            "  and give no sign that it has: the output looks completely\n"
            "  ordinary and every timestamp is wrong.")

    blank = tokenizer.pad_token_id
    if blank is None:
        for name in ("<pad>", "[PAD]", "<blank>", "<ctc_blank>"):
            if name in vocab:
                blank = vocab[name]
                break
    if blank is None:
        raise SystemExit(
            f"cannot identify the CTC blank token of {model_id}. Without it a\n"
            "  real kana would be treated as 'no output' everywhere it occurs.")

    stride = 1
    for k in getattr(model.config, "conv_stride", []) or []:
        stride *= int(k)
    if stride != 320:
        raise SystemExit(
            f"{model_id} has an audio stride of {stride} samples, but ASKAL "
            "currently supports only 320-sample (20 ms) CTC frames. Refusing "
            "the model because accepting it would silently scale every "
            "timestamp incorrectly.")

    output_size = int(getattr(model.config, "vocab_size", len(vocab)))
    if output_size != len(vocab):
        raise SystemExit(
            f"{model_id} emits {output_size} logits but its tokenizer contains "
            f"{len(vocab)} tokens; token IDs cannot be aligned safely.")

    aligner.processor = processor
    aligner.model = model
    aligner.kana_head = None          # logits come straight from the model
    aligner.vocab = vocab
    aligner.blank = blank
    aligner.output_key = output_key
    aligner.model_identity = _model_identity(model_id, model)
    aligner.frame_stride = stride
    aligner.output_size = output_size
    aligner.log = log
    log(f"    {len(vocab)} tokens, {share:.0%} kana, blank at {blank}")
