"""An alternative acoustic model: hiragana-asr's dual-CTC wav2vec2.

Why bother, when the default model loads in one line and this one does not: the
default is fine-tuned from a MULTILINGUAL checkpoint (XLSR-53, 53 languages) on
a small Japanese corpus. This one is fine-tuned from a Japanese-only encoder
pretrained on 35,000 hours, over 1,000 hours of ReazonSpeech. The training
recipe is far stronger, and syllable-boundary precision is the one number an
acoustic model can still move.

It ships as a bare `state_dict` with no config, tokenizer or preprocessor, so
all three have to be reconstructed here:

  * the ENCODER is a stock `Wav2Vec2Model` built from the base model's config
  * the VOCABULARY is the author's KANA list, reproduced below because token
    ORDER is load-bearing -- a wrong order silently aligns to the wrong sounds
  * the BLANK is index 0, documented by the author as `BLANK_IDX = 0`

Model and vocabulary: github.com/nyosegawa/hiragana-asr (Apache-2.0).

Only the kana head is used. The phoneme head exists to improve training and its
output is a different alphabet entirely.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from .align import Aligner, MODEL_STRIDE, OVERLAP_SEC, WINDOW_SEC
from .audio import SR

BASE_MODEL = "reazon-research/japanese-wav2vec2-large"
INTER_CTC_LAYER = 12
BLANK_IDX = 0

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

SPEC_PREFIX = "hiragana-asr:"


def is_dualctc(spec: str | None) -> bool:
    return bool(spec) and str(spec).startswith(SPEC_PREFIX)


def checkpoint_path(spec: str) -> Path:
    """`hiragana-asr:` alone downloads the published checkpoint;
    `hiragana-asr:/path/to.pt` uses a local one."""
    rest = str(spec)[len(SPEC_PREFIX):].strip()
    if rest:
        return Path(rest)
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download("sakasegawa/japanese-wav2vec2-large-hiragana-ctc",
                                "best-medium-ep5-inference.pt"))


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


class DualCTCAligner(Aligner):
    """Same interface as `Aligner`, different acoustic model underneath.

    Everything downstream -- tokenising, forced alignment, the skip state,
    duration derivation -- is inherited unchanged, because it depends only on
    `self.vocab` and `self.blank`.
    """

    def __init__(self, spec: str, log=print):
        from transformers import Wav2Vec2Config, Wav2Vec2FeatureExtractor, Wav2Vec2Model

        path = checkpoint_path(spec)
        log(f"  loading acoustic model: hiragana-asr ({path.name})")

        cfg = Wav2Vec2Config.from_pretrained(BASE_MODEL)
        encoder = Wav2Vec2Model(cfg)
        hidden = int(getattr(cfg, "hidden_size", 1024))

        self.kana_head = torch.nn.Linear(hidden, len(KANA) + 1)
        blob = torch.load(path, map_location="cpu", weights_only=False)
        state = _find_state_dict(blob)

        enc_sd, head_sd = {}, {}
        for k, v in state.items():
            if k.startswith("encoder."):
                enc_sd[k[len("encoder."):]] = v
            elif k.startswith("kana_head."):
                head_sd[k[len("kana_head."):]] = v
        if not enc_sd or not head_sd:
            raise RuntimeError(
                "checkpoint does not look like a DualCTCModel "
                f"(found {len(enc_sd)} encoder and {len(head_sd)} head tensors)")

        missing, unexpected = encoder.load_state_dict(enc_sd, strict=False)
        self.kana_head.load_state_dict(head_sd)
        if missing:
            log(f"    note: {len(missing)} encoder tensor(s) not in checkpoint")

        encoder.eval()
        self.kana_head.eval()
        self.model = encoder
        self.processor = Wav2Vec2FeatureExtractor.from_pretrained(BASE_MODEL)

        # Index 0 is blank, kana follow. Getting this wrong is silently
        # catastrophic -- a kana sitting on the blank index would be treated as
        # "no output" everywhere it occurs -- so it is asserted, not assumed.
        self.vocab = {k: i + 1 for i, k in enumerate(KANA)}
        self.blank = BLANK_IDX
        assert BLANK_IDX not in self.vocab.values()
        self.log = log

    def _logits(self, chunk: np.ndarray) -> torch.Tensor:
        inputs = self.processor(chunk, sampling_rate=SR, return_tensors="pt",
                                padding=False)
        with torch.inference_mode():
            hidden = self.model(inputs.input_values).last_hidden_state
            return self.kana_head(hidden)[0]

    def emissions(self, y: np.ndarray, cache: Path | None = None) -> torch.Tensor:
        """Windowed log-probs, identical in shape and meaning to the default."""
        if cache is not None and cache.exists():
            self.log(f"  cached emissions: {cache.name}")
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
            lp = torch.log_softmax(self._logits(chunk), dim=-1)
            head = 0 if i == 0 else trim
            tail = lp.shape[0] if i == len(starts) - 1 else lp.shape[0] - trim
            pieces.append(lp[head:tail])
            self.log(f"\r    emissions {i + 1}/{len(starts)}", end="")
        self.log("")

        out = torch.cat(pieces, dim=0)
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            torch.save(out, cache)
        return out
