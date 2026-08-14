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

KANA_RANGE = ("ぁ", "ヿ")      # hiragana + katakana
MIN_KANA_SHARE = 0.5


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

    from transformers import (Wav2Vec2Config, Wav2Vec2ForCTC,
                              Wav2Vec2Processor)
    from transformers.configuration_utils import PretrainedConfig

    log(f"  acoustic model: {model_id}")

    # Checkpoints uploaded years ago bake `gradient_checkpointing` into their
    # config. It is a training-time memory tradeoff, inert here, and dropped in
    # transformers v5 -- so the config is cleaned before the model is built.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*gradient_checkpointing.*",
                                category=UserWarning)
        processor = Wav2Vec2Processor.from_pretrained(model_id)
        cfg_dict, _ = PretrainedConfig.get_config_dict(model_id)
        cfg_dict.pop("gradient_checkpointing", None)
        model = Wav2Vec2ForCTC.from_pretrained(model_id,
                                               config=Wav2Vec2Config(**cfg_dict))
    model.eval()

    vocab = processor.tokenizer.get_vocab()
    ok, share = looks_like_kana_vocab(vocab)
    if not ok:
        raise SystemExit(
            f"{model_id} does not look like a kana model: only "
            f"{share:.0%} of its single-character tokens are kana.\n\n"
            "  Alignment units here are MORAS, so the model must emit kana. A\n"
            "  full ASR model that writes kanji will align to the wrong sounds\n"
            "  and give no sign that it has: the output looks completely\n"
            "  ordinary and every timestamp is wrong.")

    blank = processor.tokenizer.pad_token_id
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
    if stride and stride != 320:
        log(f"  WARNING: this model downsamples by {stride}, not 320. Every "
            "timestamp will be scaled by "
            f"{stride / 320:.2f} unless MODEL_STRIDE is changed to match.")

    aligner.processor = processor
    aligner.model = model
    aligner.kana_head = None          # logits come straight from the model
    aligner.vocab = vocab
    aligner.blank = blank
    aligner.log = log
    log(f"    {len(vocab)} tokens, {share:.0%} kana, blank at {blank}")
