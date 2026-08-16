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
    """Forced alignment against the hiragana dual-CTC acoustic model.

    Loading lives in `dualctc`, because the checkpoint is a bare state_dict with
    no config, tokenizer or preprocessor and all three have to be rebuilt. What
    stays here is everything that depends only on a vocabulary and a blank
    index: tokenising, the forced-align call, the skip state, and durations.
    """

    def __init__(self, model: str | None = None, log=print):
        """`model` selects the acoustic model:

            None                     the built-in kana model, downloaded once
            hiragana-asr:PATH.pt     a local dual-CTC checkpoint
            PATH.pt                  the same
            any other string         a Hugging Face CTC model id

        The pipeline needs only a kana vocabulary, a blank index and 20 ms
        frames, so any model meeting that works -- see `hfmodel`, which checks
        all three rather than trusting them.
        """
        from . import dualctc, hfmodel
        from .model_spec import DEFAULT_MODEL

        spec = (model or "").strip()
        if (not spec or spec == DEFAULT_MODEL
                or spec.startswith(dualctc.SPEC_PREFIX) or spec.endswith(".pt")):
            dualctc.load_into(self, spec or None, log=log)
        else:
            hfmodel.load_into(self, spec, log=log)

    # --- emissions ------------------------------------------------------------

    def emissions(self, y: np.ndarray, cache: Path | None = None) -> torch.Tensor:
        from . import dualctc

        return dualctc.compute_emissions(self, y, cache)

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
        import warnings

        from torchaudio.functional import forced_align, merge_tokens

        targets = torch.tensor([token_ids], dtype=torch.int32)
        with warnings.catch_warnings():
            # torchaudio 2.8 warns that forced_align is removed in 2.9. That
            # removal was CANCELLED: pytorch/audio#3902 records that lfilter,
            # RNNTLoss, CUCT, forced_align and overdrive were preserved after
            # user feedback, and it is present and undeprecated in 2.10+.
            # The warning is stale, so it is silenced rather than migrated away
            # from. Scoped by text, so a genuine future deprecation still shows.
            warnings.filterwarnings("ignore", message=".*forced_align.*",
                                    category=UserWarning)
            labels, scores = forced_align(lp.unsqueeze(0), targets,
                                          blank=self.blank)
        return merge_tokens(labels[0], scores[0], blank=self.blank)

    # --- alignment with a skip state ------------------------------------------

    def align_groups(self, lp: torch.Tensor, groups: list[list[str]],
                     skip_cost: float = -1.5, frame_offset: int = 0
                     ) -> list[list[dict]]:
        """Align line by line, allowing audio BETWEEN lines to match nothing.

        This is the fix for the defect at the centre of phase 1. Plain forced
        alignment must consume every token, and it has no way to say "nothing is
        sung here" -- so an instrumental passage cannot be left empty, and the
        surrounding lines are dragged into it. A line after a long rest starts
        seconds early; a rest in the middle of a line gets spent as a held
        syllable; and a lyric sheet longer than the cut is smeared over the
        whole song rather than refused.

        `forced_align` supports this directly through a `<star>` token: extend
        the emission matrix with one extra column and put a star between every
        pair of lines. The star matches any audio, so the path can spend a rest
        on it instead of on a syllable.

        `skip_cost` is the log-probability given to that column, and it is the
        only knob. At 0 the star is free and will happily swallow singing too;
        made very negative it is never used and this degrades to plain forced
        alignment. Between those, it absorbs passages that match the lyrics
        poorly while leaving genuine singing to the real tokens.
        """
        flat: list[str] = [u for g in groups for u in g]
        token_ids, spans, missing = self.tokenise(flat)
        if not token_ids:
            return [[{"text": u, "start": None, "end": None, "conf": 0.0}
                     for u in g] for g in groups]

        star = lp.shape[-1]
        lp_star = torch.cat(
            [lp, torch.full((lp.shape[0], 1), float(skip_cost),
                            dtype=lp.dtype)], dim=-1)

        # Interleave one star before, between and after the lines. Each line's
        # tokens stay contiguous, so a star can only ever absorb audio at a line
        # boundary -- never in the middle of a word.
        targets: list[int] = [star]
        # Where each unit's tokens ended up in `targets`, so the result can be
        # taken apart again. Built while appending rather than recomputed after,
        # because the star offsets make any recomputation fiddly and wrong.
        placed: list[tuple[int, int]] = []
        unit_i = 0
        for g in groups:
            for _u in g:
                a, b = spans[unit_i]
                start = len(targets)
                targets.extend(token_ids[a:b])
                placed.append((start, len(targets)))
                unit_i += 1
            targets.append(star)

        if len(targets) > lp_star.shape[0]:
            raise ValueError(
                f"{len(targets)} tokens will not fit in {lp_star.shape[0]} "
                "frames -- the window is too short for this text")

        tok_spans = self._align(lp_star, targets)

        out: list[list[dict]] = []
        unit_i = 0
        for g in groups:
            line: list[dict] = []
            for u in g:
                a, b = placed[unit_i]
                owned = tok_spans[a:b]
                if owned:
                    start = (owned[0].start + frame_offset) * SEC_PER_FRAME
                    conf = float(np.exp(np.mean([s.score for s in owned])))
                    line.append({"text": u, "start": round(start, 3),
                                 "end": None, "conf": round(conf, 4)})
                else:
                    line.append({"text": u, "start": None, "end": None,
                                 "conf": 0.0})
                unit_i += 1
            out.append(line)
        if missing:
            self.log(f"  note: {len(missing)} character(s) not in the model "
                     f"vocabulary: {''.join(sorted(missing))}")
        return out

    # --- what was actually sung ---------------------------------------------

    def free_decode(self, lp: torch.Tensor) -> str:
        """Greedy CTC decode: the kana the model hears, with no lyrics imposed.

        Forced alignment answers "where do these sounds occur", and is obliged
        to place them SOMEWHERE however wrong they are. This answers the
        different question "what is being sung", which is the only way to catch
        a reading the sheet gets wrong -- most importantly gikun, where the
        lyricist writes one word and has the singer sing another (永遠 sung
        とわ). No dictionary can know those: they are invented per song.

        MEASURED LIMIT, so nobody rebuilds the same dead end: on sung music
        this decode is SPARSE -- roughly seven kana recovered from ten seconds
        of singing. It therefore cannot answer "does this word appear", because
        almost nothing appears; a detector built on that flagged 21% of a
        corpus song and buried its one true positive.

        What it can answer is which of TWO candidate readings was sung, scored
        over the same span. There the sparseness cancels: for a line where the
        sheet printed 永遠, えいえん matched 0% of the decode and とわ matched
        100%. Use it to compare, never to detect.
        """
        ids = torch.argmax(lp, dim=-1).tolist()
        kept: list[int] = []
        prev = None
        for i in ids:
            if i != prev and i != self.blank:
                kept.append(i)
            prev = i
        inv = {v: k for k, v in self.vocab.items()}
        return "".join(inv.get(i, "") for i in kept)



    def align_units(self, lp: torch.Tensor, units: list[str],
                    frame_offset: int = 0) -> list[dict]:
        """Align `units` against an emission matrix; times are absolute seconds."""
        token_ids, spans, missing = self.tokenise(units)
        if not token_ids:
            # Nothing in this line is in the model's vocabulary -- a line sung
            # entirely in English, say. Return a placeholder PER UNIT rather
            # than an empty list: callers pair this result with `units`
            # positionally, and a short list silently misaligns every cell after
            # it or, if the line is wholly foreign, indexes off the end.
            self.log(f"  note: nothing alignable in {''.join(units)[:40]!r}; "
                     "spacing it evenly")
            return [{"text": u, "start": None, "end": None, "conf": 0.0}
                    for u in units]
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


def trim_line_tails(groups: list[list[dict]], max_hold: float,
                    floor: float = 0.35, factor: float = 2.5) -> int:
    """End a line when its singing ends, not when the next line starts.

    Ends are derived from the NEXT unit's onset, and for a line's final syllable
    that next unit belongs to the following line. So a line followed by an
    instrumental passage runs on until the cap -- and because `\\k` tiles the
    line, that whole stretch is spent inside it and the highlight sits on the
    last syllable for seconds.

    A final syllable may be held, but in proportion to the line it belongs to: a
    few times that line's own typical mora, not a flat two seconds regardless of
    whether the line was sung fast or slow. The floor keeps a very fast line
    from being clipped to nothing.

    Only the last syllable is touched. Interior gaps are real musical rests and
    are left alone.
    """
    trimmed = 0
    for g in groups:
        starts = [c["start"] for c in g if c["start"] is not None]
        last = g[-1] if g else None
        if last is None or len(starts) < 2:
            continue
        if last["start"] is None or last["end"] is None:
            continue
        gaps = sorted(starts[i] - starts[i - 1] for i in range(1, len(starts)))
        median = gaps[len(gaps) // 2]
        allowed = max(floor, min(max_hold, median * factor))
        capped = round(last["start"] + allowed, 3)
        if capped < last["end"] - 1e-6:
            last["end"] = capped
            trimmed += 1
    return trimmed


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
