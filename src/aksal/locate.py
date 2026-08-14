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
        if b.ref_start < a.ref_end - 1e-6:
            # Two video chunks claiming the SAME span of the song. Almost always
            # a repeated chorus: the video's second chorus fingerprints just as
            # well against the first occurrence in the track as against its own.
            #
            # This was checked in video time but not in song time, and the cost
            # was invisible -- every lyric line in the overlap belongs to the
            # earlier chunk, so the later chunk silently produces nothing at all
            # and its lines are reported as "not present in this cut".
            #
            # Handing the disputed span to the earlier chunk keeps the map
            # monotonic in both clocks, which is the invariant everything
            # downstream relies on.
            overlap = a.ref_end - b.ref_start
            log(f"  note: chunks overlap by {overlap:.1f}s of song time "
                "(a repeated section matched twice); giving the shared part to "
                "the earlier chunk")
            b.ref_start = round(a.ref_end, 3)
            b.ep_start = round(b.ref_start + b.offset, 3)
            if b.ref_end <= b.ref_start or b.ep_end <= b.ep_start:
                raise SpliceError(
                    "a chunk is entirely contained in another in song time; "
                    "the splice map is ambiguous")

    weak = [s for s in segments if 0 < s.support < min_support]
    if weak:
        log(f"  WARNING: {len(weak)} chunk(s) matched weakly "
            f"(support < {min_support}). A TV size that was separately mixed "
            "rather than cut from the same master will match poorly, and its "
            "syllable timing will not transfer.")
    return ordered


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

    # NOT chained by default -- see best_chain, which is measured and rejected.
    return _resolve_overlaps(out)


# A chunk boundary is never exact: the two matches either side of a cut both
# bleed a little past it, because the frames straddling the join fingerprint
# partly as one side and partly as the other.
MAX_TRIM_SEC = 3.0


def _largest_free_span(lo: float, hi: float,
                       taken: list[tuple[float, float]]
                       ) -> tuple[float, float] | None:
    """The longest part of [lo, hi] no already-kept chunk claims.

    Subtracting the whole set at once, rather than trimming against each
    neighbour in turn, is what handles a chunk sitting ENTIRELY inside a
    stronger one -- which trimming one end at a time leaves untouched and still
    overlapping, so validate() then rejects the map outright.
    """
    pieces = [(lo, hi)]
    for a, b in taken:
        nxt: list[tuple[float, float]] = []
        for x, y in pieces:
            if b <= x or a >= y:
                nxt.append((x, y))
                continue
            if a > x:
                nxt.append((x, min(a, y)))
            if b < y:
                nxt.append((max(b, x), y))
        pieces = nxt
    pieces = [p for p in pieces if p[1] > p[0]]
    return max(pieces, key=lambda p: p[1] - p[0]) if pieces else None


def best_chain(found: list[Segment]) -> list[Segment]:
    """Pick the set of chunks that tells one consistent story.

    MEASURED AND NOT USED BY DEFAULT. The reasoning below is sound and the
    result is a more self-consistent map, but on the one opening it was built
    for it made the output WORSE: it recovered three more lines and placed them
    around 17s out, because reading the video's final section as the song's
    later chorus then feeds those lines to the wrong occurrence of a repeated
    lyric. Median syllable error went 0.87s -> 16.79s. Kept, tested and
    available, because the failure is in how the lyric sheet's line order is
    consumed rather than in the chaining itself -- but it does not ship on until
    that half is solved.

    A splice map has to increase in BOTH clocks: later in the video means later
    in the song. Choosing chunks greedily by support does not respect that, and
    a repeated chorus is where it breaks -- the video's second chorus
    fingerprints just as well against the FIRST occurrence in the track, so the
    strongest reading of each chunk in isolation can claim the same span of the
    song twice and contradict itself.

    Picking the highest-scoring chain that is monotonic in both clocks fixes
    that at the source: a chunk whose best offset would contradict an earlier
    chunk is free to be read at its second-best offset instead, which is usually
    the later occurrence of the same chorus and is usually right.

    Longest-increasing-subsequence by weight, O(n^2) over a handful of chunks.
    Score is duration times support, so a long confident chunk outranks a short
    one and coverage is preferred over chunk count.
    """
    if len(found) < 2:
        return list(found)

    order = sorted(found, key=lambda s: (s.ep_start, s.ref_start))
    weight = [max(s.ep_end - s.ep_start, 0.0) * max(s.support, 1) for s in order]
    best = list(weight)
    prev = [-1] * len(order)

    for i, seg in enumerate(order):
        for j in range(i):
            other = order[j]
            # Strictly after in both clocks, allowing the small boundary
            # overlap that a cut always produces.
            if (other.ep_end - MAX_TRIM_SEC <= seg.ep_start
                    and other.ref_end - MAX_TRIM_SEC <= seg.ref_start
                    and best[j] + weight[i] > best[i]):
                best[i] = best[j] + weight[i]
                prev[i] = j

    end = max(range(len(order)), key=lambda i: best[i])
    chain: list[Segment] = []
    while end != -1:
        chain.append(order[end])
        end = prev[end]
    return list(reversed(chain))


def _resolve_overlaps(found: list[Segment]) -> list[Segment]:
    """Keep the strongest chunks, TRIMMING small overlaps rather than dropping.

    Rejecting any chunk that overlaps a stronger one is what silently cost a
    real 18-second chunk on a test-set OP: it grazed its neighbour's boundary by
    1.36s, the neighbour had more support and was kept first, and the whole
    chunk went -- after which phase 1 reported the six lyric lines inside it as
    "not present in this cut". They had been broadcast.

    A small overlap is a boundary disagreement, not a contradiction, so the
    weaker chunk gives up the overlapping part and keeps the rest. A LARGE
    overlap is two genuinely competing claims on the same video, and there the
    stronger one still wins outright.
    """
    kept: list[Segment] = []
    for seg in sorted(found, key=lambda s: -s.support):
        free = _largest_free_span(seg.ep_start, seg.ep_end,
                                  [(k.ep_start, k.ep_end) for k in kept])
        if free is None:
            continue                      # wholly inside a stronger chunk
        lo, hi = free
        trimmed = (seg.ep_end - seg.ep_start) - (hi - lo)
        if hi - lo < MIN_SEG_SEC or trimmed > MAX_TRIM_SEC:
            continue
        if trimmed > 0:
            # The song clock moves with the video clock inside a chunk, so the
            # reference span shifts by exactly the same amount.
            seg = Segment(
                ref_start=round(seg.ref_start + (lo - seg.ep_start), 3),
                ref_end=round(seg.ref_end - (seg.ep_end - hi), 3),
                ep_start=round(lo, 3), ep_end=round(hi, 3),
                offset=seg.offset, support=seg.support)
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
