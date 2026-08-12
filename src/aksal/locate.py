"""Finding the song inside a video.

Three strategies, tried in order of cost and reliability:

  1. An explicit --song-start. Always wins, costs nothing, cannot be wrong.
  2. Chapter markers, if the container carries them.
  3. Constellation fingerprinting against a reference track (mode A only).

There is deliberately no automatic fallback beyond that. A locator that guesses
badly produces subtitles that look completely plausible and are entirely
mistimed, which is far worse than an error message naming the flag to pass.
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter

from .audio import FRAME_SEC, decode, logspec

# --- constellation parameters -------------------------------------------------
PEAK_NEIGHBOURHOOD = (21, 9)
PEAK_FLOOR_PCT = 82
FAN_OUT = 12
MIN_DT, MAX_DT = 2, 80
MAX_DF = 96

MIN_SUPPORT = 40
MAX_GAP_SEC = 1.2
MIN_SEG_SEC = 2.5


@dataclass
class Segment:
    """One chunk of the reference kept by the edit, at a constant time offset.

    A TV edit is straight cuts, never time-stretching, so within a chunk the
    mapping between reference time and video time is a pure translation.
    """
    ref_start: float
    ref_end: float
    ep_start: float
    ep_end: float
    offset: float
    support: int = 0

    def contains_ref(self, t: float) -> bool:
        return self.ref_start <= t <= self.ref_end

    def contains_ep(self, t: float) -> bool:
        return self.ep_start <= t <= self.ep_end

    def to_dict(self) -> dict:
        return asdict(self)


class SpliceError(ValueError):
    """A splice map that later stages cannot express."""


def validate(segments: list[Segment], min_support: int = 200,
             log=print) -> list[Segment]:
    """Reject or flag splice maps that downstream stages cannot honour.

    Cheap to check here and expensive to debug later: a degenerate chunk turns
    into an empty audio slice deep inside phase 2, where the symptom is an
    unhelpful shape error rather than "this edit is not a plain splice".
    """
    if not segments:
        return segments

    for s in segments:
        if s.ref_end <= s.ref_start or s.ep_end <= s.ep_start:
            raise SpliceError(
                f"zero or negative length chunk: song {s.ref_start}-{s.ref_end} "
                f"-> video {s.ep_start}-{s.ep_end}")

    ordered = sorted(segments, key=lambda s: s.ep_start)
    for a, b in zip(ordered, ordered[1:]):
        if b.ep_start < a.ep_end - 1e-6:
            raise SpliceError(
                f"chunks overlap in video time: {a.ep_start}-{a.ep_end} and "
                f"{b.ep_start}-{b.ep_end}")
        if b.ref_start < a.ref_start:
            # Video order and song order disagree: the edit reordered material.
            # Nothing downstream assumes that, so refuse rather than emit
            # subtitles that run backwards through the lyrics.
            raise SpliceError(
                "this edit reorders the song (a later video chunk maps to an "
                "earlier part of the track); AKSAL cannot express that")

    weak = [s for s in segments if 0 < s.support < min_support]
    if weak:
        log(f"  WARNING: {len(weak)} chunk(s) matched weakly "
            f"(support < {min_support}). A TV size that was separately mixed "
            "rather than cut from the same master will match poorly, and its "
            "syllable timing will not transfer.")
    return ordered


def identity_segment(start: float, end: float) -> Segment:
    """Mode B: the 'reference' IS the video audio, so the mapping is identity."""
    return Segment(ref_start=start, ref_end=end, ep_start=start, ep_end=end,
                   offset=0.0, support=0)


SONG_CHAPTERS = ("op", "opening", "intro", "avant",
                 "ed", "ending", "credit", "insert", "song")

# --- strategy 2: chapters -----------------------------------------------------

def chapters(path: Path) -> list[tuple[float, float, str]]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters",
         str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    out = []
    for ch in data.get("chapters", []):
        title = (ch.get("tags") or {}).get("title", "")
        out.append((float(ch["start_time"]), float(ch["end_time"]), title))
    return out


def chapter_guess(path: Path, keywords=SONG_CHAPTERS) -> float | None:
    """Return the start of a chapter that looks like a song, if any."""
    for start, _end, title in chapters(path):
        low = title.lower()
        if any(k in low for k in keywords):
            return start
    return None


# --- strategy 3: fingerprinting ----------------------------------------------

def peaks(S: np.ndarray) -> np.ndarray:
    local_max = maximum_filter(S, size=PEAK_NEIGHBOURHOOD, mode="constant")
    floor = np.percentile(S, PEAK_FLOOR_PCT)
    f, t = np.nonzero((S == local_max) & (S > floor))
    order = np.argsort(t)
    return np.stack([f[order], t[order]], axis=1)


def fingerprint(S: np.ndarray) -> dict[int, list[int]]:
    pk = peaks(S)
    table: dict[int, list[int]] = defaultdict(list)
    n = len(pk)
    for i in range(n):
        f1, t1 = int(pk[i, 0]), int(pk[i, 1])
        paired = 0
        for j in range(i + 1, n):
            f2, t2 = int(pk[j, 0]), int(pk[j, 1])
            dt = t2 - t1
            if dt < MIN_DT:
                continue
            if dt > MAX_DT:
                break
            if abs(f2 - f1) > MAX_DF:
                continue
            table[(f1 & 0x1FF) << 16 | (f2 & 0x1FF) << 7 | (dt & 0x7F)].append(t1)
            paired += 1
            if paired >= FAN_OUT:
                break
    return table


def _match_pairs(ref_fp, ep_fp) -> dict[int, list[int]]:
    by_delta: dict[int, list[int]] = defaultdict(list)
    for h, ref_times in ref_fp.items():
        ep_times = ep_fp.get(h)
        if not ep_times:
            continue
        # A hash colliding in dozens of places carries no location information
        # and only raises the noise floor under every delta bin.
        if len(ref_times) * len(ep_times) > 64:
            continue
        for rt in ref_times:
            for et in ep_times:
                by_delta[et - rt].append(rt)
    return by_delta


def _segments(by_delta, search_offset: float) -> list[Segment]:
    max_gap = MAX_GAP_SEC / FRAME_SEC
    out: list[Segment] = []
    for delta, ref_frames in by_delta.items():
        if len(ref_frames) < MIN_SUPPORT:
            continue
        arr = np.array(sorted(ref_frames))
        splits = np.nonzero(np.diff(arr) > max_gap)[0] + 1
        for run in np.split(arr, splits):
            if (run[-1] - run[0]) * FRAME_SEC < MIN_SEG_SEC:
                continue
            if len(run) < MIN_SUPPORT // 2:
                continue
            out.append(Segment(
                ref_start=round(float(run[0] * FRAME_SEC), 3),
                ref_end=round(float(run[-1] * FRAME_SEC), 3),
                ep_start=round(float((run[0] + delta) * FRAME_SEC + search_offset), 3),
                ep_end=round(float((run[-1] + delta) * FRAME_SEC + search_offset), 3),
                offset=round(float(delta * FRAME_SEC + search_offset), 3),
                support=int(len(run)),
            ))

    kept: list[Segment] = []
    for seg in sorted(out, key=lambda s: -s.support):
        if any(seg.ep_start < k.ep_end and k.ep_start < seg.ep_end for k in kept):
            continue
        kept.append(seg)
    return sorted(kept, key=lambda s: s.ep_start)


def locate_by_fingerprint(ref: Path, video: Path, search_start: float = 0.0,
                          search_dur: float | None = 420.0,
                          log=print) -> list[Segment]:
    """Find every chunk of `ref` present in `video`, with its time offset."""
    log(f"  fingerprinting {ref.name}")
    ref_fp = fingerprint(logspec(decode(ref)))
    log(f"    {len(ref_fp)} hashes")

    log(f"  fingerprinting {video.name}"
        + (f" ({search_start:.0f}s +{search_dur:.0f}s)" if search_dur else ""))
    ep_fp = fingerprint(logspec(decode(video, start=search_start or None,
                                       dur=search_dur)))
    log(f"    {len(ep_fp)} hashes")

    return _segments(_match_pairs(ref_fp, ep_fp), search_start)
