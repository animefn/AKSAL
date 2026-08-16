"""The acoustic model: hiragana-asr's dual-CTC wav2vec2.

Fine-tuned from a Japanese-only encoder pretrained on 35,000 hours, over 1,000
hours of ReazonSpeech. Measured against hand-timed karaoke it beat the
multilingual model it replaced on every song in the corpus, most sharply where
line placement had been poor.

It ships as a bare `state_dict` with no config, tokenizer or preprocessor, so
all three are rebuilt here:

  * the ENCODER is a stock `Wav2Vec2Model` built from the base model's config
  * the VOCABULARY is the author's KANA list, reproduced below because token
    ORDER is load-bearing -- a wrong order aligns to the wrong sounds and looks
    entirely plausible while doing it
  * the BLANK is index 0, documented by the author as `BLANK_IDX = 0`

Only the kana head is used. The phoneme head exists to help training and emits a
different alphabet.

One property is worth knowing before judging it: asked to transcribe singing
freely it emits almost nothing, because it is built not to guess and singing is
outside its training. Asked to ALIGN text it has been given, it is accurate.
Free transcription is a poor predictor of forced-alignment quality.

Model and vocabulary: github.com/nyosegawa/hiragana-asr (Apache-2.0).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from .align import MODEL_STRIDE, OVERLAP_SEC, WINDOW_SEC
from .audio import SR

REPO = "sakasegawa/japanese-wav2vec2-large-hiragana-ctc"
CHECKPOINT = "best-medium-ep5-inference.pt"
BASE_MODEL = "reazon-research/japanese-wav2vec2-large"
BLANK_IDX = 0

SPEC_PREFIX = "hiragana-asr:"
DEFAULT_SPEC = SPEC_PREFIX

# Order is the contract with the checkpoint. Reproduced verbatim from the
# author's src/asr/kana_vocab.py; index 0 is the CTC blank, kana start at 1.
KANA = [
    "あ", "い", "う", "え", "お",
    "か", "き", "く", "け", "こ",
    "さ", "し", "す", "せ", "そ",
    "た", "ち", "つ", "て", "と",
    "な", "に", "ぬ", "ね", "の",
    "は", "ひ", "ふ", "へ", "ほ",
    "ま", "み", "む", "め", "も",
    "や", "ゆ", "よ",
    "ら", "り", "る", "れ", "ろ",
    "わ", "を", "ん",
    "が", "ぎ", "ぐ", "げ", "ご",
    "ざ", "じ", "ず", "ぜ", "ぞ",
    "だ", "ぢ", "づ", "で", "ど",
    "ば", "び", "ぶ", "べ", "ぼ",
    "ぱ", "ぴ", "ぷ", "ぺ", "ぽ",
    "ぁ", "ぃ", "ぅ", "ぇ", "ぉ",
    "っ", "ゃ", "ゅ", "ょ", "ゎ",
    "ー",
]


def checkpoint_path(spec: str | None, log=print) -> Path:
    """Resolve a model spec to a checkpoint file.

    `hiragana-asr:` downloads the published weights and caches them;
    `hiragana-asr:/path/to.pt` uses a local file instead.
    """
    from .model_spec import DEFAULT_MODEL

    spec = DEFAULT_SPEC if not spec or spec == DEFAULT_MODEL else spec
    rest = str(spec)[len(SPEC_PREFIX):].strip() if str(spec).startswith(SPEC_PREFIX) \
        else str(spec).strip()
    if rest:
        path = Path(rest)
        if not path.exists():
            raise SystemExit(f"model checkpoint not found: {path}")
        return path

    from huggingface_hub import hf_hub_download

    # THE CACHE IS CHECKED WITHOUT THE NETWORK FIRST. hf_hub_download contacts
    # the hub on every call to see whether a newer revision exists, even when
    # the file is already on disk -- so copying a populated `models` folder to
    # a machine that is offline still produced a wall of connection errors, and
    # the "fetching" message appeared for a model that was never fetched.
    #
    # local_files_only resolves purely from the cache and raises if it is not
    # there, which turns "is it cached?" into a question that costs nothing and
    # cannot fail on a bad connection.
    try:
        return Path(hf_hub_download(REPO, CHECKPOINT, local_files_only=True))
    except Exception:                                # noqa: BLE001
        pass

    log("  fetching the acoustic model (once; about 630 MB)")
    log("  (this is the only download; it is cached beside the executable)")
    try:
        return Path(hf_hub_download(REPO, CHECKPOINT))
    except Exception as exc:                         # noqa: BLE001
        raise SystemExit(
            f"could not fetch the acoustic model: {type(exc).__name__}\n\n"
            "  It is downloaded once and cached, so this needs a working\n"
            "  connection the first time only. If this machine is offline,\n"
            "  copy the `models` folder from a machine that has it -- it sits\n"
            "  beside aksal.exe -- or point HF_HOME at a populated cache.")


def _cached_first(cls, model_id: str):
    """`cls.from_pretrained`, preferring the local cache over the network.

    The checkpoint is not the only thing fetched: the base model's config and
    its feature extractor are pulled from the hub too, and each one contacts it
    on every run to check for a newer revision. Fixing only the checkpoint left
    two more calls that fail on an offline machine with a populated cache --
    which is exactly the situation of someone who copied the `models` folder
    across.
    """
    try:
        return cls.from_pretrained(model_id, local_files_only=True)
    except Exception:                                # noqa: BLE001
        return cls.from_pretrained(model_id)


def _find_state_dict(blob) -> dict:
    """Pull the weights out of whatever the checkpoint wrapped them in."""
    if not isinstance(blob, dict):
        raise RuntimeError("checkpoint is not a dict; cannot find weights")
    for key in ("model_state_dict", "state_dict", "model"):
        inner = blob.get(key)
        if isinstance(inner, dict) and inner:
            return inner
    if any(isinstance(v, torch.Tensor) for v in blob.values()):
        return blob
    raise RuntimeError(f"no weights found in checkpoint (keys: {list(blob)[:8]})")


def load_into(aligner, spec: str | None = None, log=print) -> None:
    """Attach the model, its vocabulary and its blank index to `aligner`.

    A function over an existing object rather than a subclass: there is one
    acoustic model, so a class hierarchy would describe a choice that no longer
    exists.
    """
    from transformers import (Wav2Vec2Config, Wav2Vec2FeatureExtractor,
                              Wav2Vec2Model)

    path = checkpoint_path(spec, log=log)
    log(f"  acoustic model: {path.name}")

    cfg = _cached_first(Wav2Vec2Config, BASE_MODEL)
    encoder = Wav2Vec2Model(cfg)
    head = torch.nn.Linear(int(getattr(cfg, "hidden_size", 1024)), len(KANA) + 1)

    state = _find_state_dict(torch.load(path, map_location="cpu",
                                        weights_only=False))
    enc_sd = {k[len("encoder."):]: v for k, v in state.items()
              if k.startswith("encoder.")}
    head_sd = {k[len("kana_head."):]: v for k, v in state.items()
               if k.startswith("kana_head.")}
    if not enc_sd or not head_sd:
        raise RuntimeError(
            "this checkpoint is not a dual-CTC model "
            f"({len(enc_sd)} encoder and {len(head_sd)} head tensors found)")

    result = encoder.load_state_dict(enc_sd, strict=False)
    head.load_state_dict(head_sd)
    if result.missing_keys:
        log(f"    note: {len(result.missing_keys)} encoder tensor(s) missing")

    encoder.eval()
    head.eval()
    aligner.model = encoder
    aligner.kana_head = head
    aligner.processor = _cached_first(Wav2Vec2FeatureExtractor, BASE_MODEL)
    aligner.log = log

    # Index 0 is blank, kana follow. A kana sitting on the blank index would be
    # treated as "no output" everywhere it occurred, silently, so this is
    # asserted rather than assumed.
    aligner.vocab = {k: i + 1 for i, k in enumerate(KANA)}
    aligner.blank = BLANK_IDX
    aligner.output_key = None
    assert BLANK_IDX not in aligner.vocab.values()


def compute_emissions(aligner, y: np.ndarray,
                      cache: Path | None = None) -> torch.Tensor:
    """Log-probs for the whole signal, windowed and stitched.

    Depends only on (model, audio) and never on the lyrics, so it is worth
    caching: iterating on readings or timing heuristics is otherwise dominated
    by recomputing an identical matrix on CPU.
    """
    if cache is not None and cache.exists():
        aligner.log(f"  cached emissions: {cache.name}")
        return torch.load(cache)

    win = int(WINDOW_SEC * SR)
    hop = int((WINDOW_SEC - OVERLAP_SEC) * SR)
    trim = int((OVERLAP_SEC / 2) * SR / MODEL_STRIDE)

    pieces: list[torch.Tensor] = []
    starts = list(range(0, max(len(y) - win + hop, 1), hop))
    for i, s in enumerate(starts):
        chunk = y[s:s + win]
        if len(chunk) < SR // 2:
            continue
        inputs = aligner.processor(chunk, sampling_rate=SR,
                                   return_tensors="pt", padding=False)
        with torch.inference_mode():
            if getattr(aligner, "kana_head", None) is None:
                # Stock Hugging Face CTC models expose `.logits`; the custom
                # dual-CTC AutoModels expose a named kana head instead.
                output = aligner.model(inputs.input_values)
                key = getattr(aligner, "output_key", None)
                logits = (output[key] if key else output.logits)[0]
            else:
                hidden = aligner.model(inputs.input_values).last_hidden_state
                logits = aligner.kana_head(hidden)[0]
        lp = torch.log_softmax(logits, dim=-1)

        # Keep the frames furthest from a window seam, where the model had the
        # most context either side.
        head = 0 if i == 0 else trim
        tail = lp.shape[0] if i == len(starts) - 1 else lp.shape[0] - trim
        pieces.append(lp[head:tail])
        aligner.log(f"\r    emissions {i + 1}/{len(starts)}", end="")
    aligner.log("")

    out = torch.cat(pieces, dim=0)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        torch.save(out, cache)
    return out
