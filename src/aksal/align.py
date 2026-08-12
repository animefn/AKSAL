"""CTC forced alignment.

Two entry points, matching the two phases:

  phase 1 -- one monotonic pass over the whole track, producing line timings.
  phase 2 -- alignment constrained to one hand-verified line window at a time,
             producing mora timings.

The windowed form is strictly more accurate, and that is the point of the
two-phase split: your phase-1 corrections become hard constraints that errors
cannot propagate across.

A note on durations. CTC is peaky -- it emits each label on a single frame and
blanks the rest, so raw token spans come back one frame wide no matter how long
the syllable was actually sung. Spike POSITIONS are trustworthy; widths are not.
So a unit runs from its own spike to the next, capped.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from .audio import SR

DEFAULT_MODEL = "vumichien/wav2vec2-large-xlsr-japanese-hiragana"

WINDOW_SEC = 20.0
OVERLAP_SEC = 2.0
MODEL_STRIDE = 320             # wav2vec2 downsamples 16 kHz by 320 -> 20 ms/frame
SEC_PER_FRAME = MODEL_STRIDE / SR

VOWEL_OF = {
    **{c: "あ" for c in "あかさたなはまやらわがざだばぱゃ"},
    **{c: "い" for c in "いきしちにひみりぎじぢびぴ"},
    **{c: "う" for c in "うくすつぬふむゆるぐずづぶぷゅ"},
    **{c: "え" for c in "えけせてねへめれげぜでべぺ"},
    **{c: "お" for c in "おこそとのほもよろをごぞどぼぽょ"},
}


class Aligner:
    def __init__(self, model_name: str = DEFAULT_MODEL, log=print):
        import warnings

        from transformers import (Wav2Vec2Config, Wav2Vec2ForCTC,
                                  Wav2Vec2Processor)
        from transformers.configuration_utils import PretrainedConfig

        log(f"  loading acoustic model: {model_name}")

        # Many published wav2vec2 checkpoints were uploaded years ago with
        # `gradient_checkpointing` baked into config.json. It is a *training*
        # memory/compute tradeoff -- activations are recomputed on the backward
        # pass, and we never run one -- so it is inert here. transformers still
        # warns on every load and drops support in v5.
        #
        # Two things are needed, because they have different causes:
        #  * the MODEL is built from a config we clean first, which is the real
        #    fix and is what keeps this working under v5. Verified to leave the
        #    weights bit-identical.
        #  * the PROCESSOR reads config.json itself and gives no way to pass a
        #    cleaned one, so that message alone is filtered. Scoped to this
        #    text, so unrelated warnings still surface.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*gradient_checkpointing.*",
                category=UserWarning)
            self.processor = Wav2Vec2Processor.from_pretrained(model_name)

            cfg_dict, _ = PretrainedConfig.get_config_dict(model_name)
            cfg_dict.pop("gradient_checkpointing", None)
            config = Wav2Vec2Config(**cfg_dict)
            self.model = Wav2Vec2ForCTC.from_pretrained(model_name,
                                                        config=config)
        self.model.eval()
        self.vocab: dict[str, int] = self.processor.tokenizer.get_vocab()
        self.log = log

        # Getting this wrong is silently catastrophic: if the real blank index
        # is occupied by a kana, the aligner treats that kana as "no output".
        blank = self.processor.tokenizer.pad_token_id
        if blank is None:
            for name in ("<pad>", "[PAD]", "<blank>"):
                if name in self.vocab:
                    blank = self.vocab[name]
                    break
        if blank is None:
            raise RuntimeError("cannot identify this model's CTC blank token")
        self.blank = blank

    # --- emissions ------------------------------------------------------------

    def emissions(self, y: np.ndarray, cache: Path | None = None) -> torch.Tensor:
        """Log-probs for the whole signal, windowed and stitched.

        Depends only on (model, audio) and never on the lyrics, so it is worth
        caching: iterating on readings or timing heuristics is otherwise
        dominated by recomputing an identical matrix on CPU.
        """
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
            inputs = self.processor(chunk, sampling_rate=SR,
                                    return_tensors="pt", padding=False)
            with torch.inference_mode():
                logits = self.model(inputs.input_values).logits[0]
            lp = torch.log_softmax(logits, dim=-1)

            # Keep the frames furthest from a window seam, where the model had
            # the most context.
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

    # --- tokenisation ---------------------------------------------------------

    def tokenise(self, units: list[str]) -> tuple[list[int], list[tuple[int, int]], set[str]]:
        """Map display units to model tokens.

        Returns (token_ids, per-unit (start, end) slices, characters dropped).
        """
        token_ids: list[int] = []
        spans: list[tuple[int, int]] = []
        missing: set[str] = set()

        for u in units:
            start = len(token_ids)
            for ch in u:
                if ch.isspace():
                    continue
                candidates = [ch]
                # Only respell a long-vowel mark if the model has no token for
                # it; sung, it is a continuation of the preceding vowel.
                if ch in "ーｰ―‐" and ch not in self.vocab:
                    prev = next((c for c in reversed(u) if c in VOWEL_OF), None)
                    candidates = [VOWEL_OF.get(prev, "")] if prev else []
                ids = [self.vocab[c] for c in candidates if c in self.vocab]
                if not ids and ch not in "ーｰ―‐":
                    missing.add(ch)
                token_ids.extend(ids)
            spans.append((start, len(token_ids)))
        return token_ids, spans, missing

    # --- alignment ------------------------------------------------------------

    def _align(self, lp: torch.Tensor, token_ids: list[int]):
        from torchaudio.functional import forced_align, merge_tokens

        targets = torch.tensor([token_ids], dtype=torch.int32)
        labels, scores = forced_align(lp.unsqueeze(0), targets, blank=self.blank)
        return merge_tokens(labels[0], scores[0], blank=self.blank)

    def align_units(self, lp: torch.Tensor, units: list[str],
                    frame_offset: int = 0) -> list[dict]:
        """Align `units` against an emission matrix; times are absolute seconds."""
        token_ids, spans, missing = self.tokenise(units)
        if not token_ids:
            return []
        if len(token_ids) > lp.shape[0]:
            raise ValueError(
                f"{len(token_ids)} tokens will not fit in {lp.shape[0]} frames "
                "-- the window is too short for this text")

        tok_spans = self._align(lp, token_ids)
        out: list[dict] = []
        for u, (a, b) in zip(units, spans):
            owned = tok_spans[a:b]
            if owned:
                start = (owned[0].start + frame_offset) * SEC_PER_FRAME
                conf = float(np.exp(np.mean([s.score for s in owned])))
            else:
                start, conf = None, 0.0
            out.append({"text": u, "start": None if start is None else round(start, 3),
                        "end": None, "conf": round(conf, 4)})
        if missing:
            self.log(f"  note: {len(missing)} character(s) not in the model "
                     f"vocabulary: {''.join(sorted(missing))}")
        return out


# --- duration derivation ------------------------------------------------------

def derive_durations(items: list[dict], max_hold: float, tail: float = 0.4,
                     limit: float | None = None) -> None:
    """Give each unit an end: its successor's spike, capped at `max_hold`."""
    n = len(items)
    for i, c in enumerate(items):
        if c["start"] is None:
            continue
        nxt = next((items[j]["start"] for j in range(i + 1, n)
                    if items[j]["start"] is not None), None)
        end = nxt if nxt is not None else c["start"] + tail
        end = min(end, c["start"] + max_hold)
        if limit is not None:
            end = min(end, limit)
        c["end"] = round(max(end, c["start"] + 0.02), 3)


def fix_tail_smear(groups: list[list[dict]], max_hold: float) -> int:
    """Pull back a trailing BLOCK of units that spiked into a following rest.

    Where a line is followed by an instrumental passage the forced path still
    has to place the remaining tokens somewhere, and their posteriors are
    diffuse, so they land seconds late -- together, still tightly spaced
    relative to each other. Looking at one unit at a time only ever catches the
    final one.

    The distinction that matters: a large gap MID-line with plenty of tightly
    packed units after it is a real musical rest and must be left alone. A large
    gap near the END with few units after it is smear.
    """
    fixed = 0
    for grp in groups:
        n = len(grp)
        if n < 3:
            continue
        starts = [c["start"] for c in grp]
        if any(s is None for s in starts):
            continue
        gaps = [starts[i] - starts[i - 1] for i in range(1, n)]
        normal = [g for g in gaps if g <= max_hold]
        med = sorted(normal)[len(normal) // 2] if normal else 0.2

        # Scan forward through the tail window so the EARLIEST suspect gap wins.
        for i in range(max(1, n - max(2, int(0.3 * n))), n):
            if gaps[i - 1] > max_hold:
                anchor = grp[i - 1]["start"]
                for j, k in enumerate(range(i, n), start=1):
                    grp[k]["start"] = round(anchor + med * j, 3)
                    grp[k]["smear_fixed"] = True
                fixed += n - i
                break
    return fixed


def snap_to_onsets(items: list[dict], env: np.ndarray, hop_sec: float = 0.01,
                   radius: float = 0.10) -> int:
    """Nudge each unit's start to the nearest energy onset within `radius`.

    CTC spikes land somewhere inside a syllable rather than on its attack. With
    an isolated vocal stem the envelope gives a much sharper attack than the
    posterior does, so this is where mora boundaries get their final polish.
    """
    if len(env) < 3:
        return 0
    flux = np.diff(env, prepend=env[0])
    flux[flux < 0] = 0.0
    if flux.max() <= 0:
        return 0
    flux /= flux.max()

    r = int(radius / hop_sec)
    moved = 0
    for c in items:
        if c["start"] is None:
            continue
        centre = int(c["start"] / hop_sec)
        lo, hi = max(centre - r, 0), min(centre + r + 1, len(flux))
        if hi <= lo:
            continue
        local = flux[lo:hi]
        if local.max() < 0.05:          # no real attack nearby; leave it alone
            continue
        best = lo + int(np.argmax(local))
        new = round(best * hop_sec, 3)
        if abs(new - c["start"]) > 1e-6:
            c["start"] = new
            moved += 1
    return moved
