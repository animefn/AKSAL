"""Where syllable timing comes from, as an explicit seam.

Phase 1 and phase 2 need different things from audio, and conflating them was a
hidden assumption rather than a decision:

    structure  (which lines are in this cut, roughly where)  -> the REFERENCE
    timing     (the \\k values themselves)                    -> the VIDEO

Only the reference can answer the first: it holds the whole song, so every
lyric line has a true home and a repeated chorus is unambiguous.

But taking the *timing* from it assumes the TV edit is a literal cut of the same
recording, so that a retained chunk is a pure translation. That is often true and
sometimes not -- a separately mixed TV-size version, or a cross-fade at a splice
join, breaks it, and no constant offset can carry syllable durations across.
Timing against the video is immune to both, because it measures what was
actually broadcast.

A TimingSource is therefore a pair: some audio, and the mapping between that
audio's timeline and the video's. Everything downstream works in these terms and
does not care which was chosen.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:                                    # pragma: no cover
    from .project import Project


@dataclass
class TimingSource:
    """Audio to align against, plus how its clock relates to the video's."""
    audio: Path
    name: str                       # "video" | "reference"
    start: float | None = None      # slice of `audio` to decode
    dur: float | None = None
    offset: float = 0.0             # audio time + offset = video time
    conditioned: bool = True
    cache_tag: str = ""

    def to_video(self, t: float) -> float:
        return round(t + self.offset, 3)

    def to_audio(self, t: float) -> float:
        return round(t - self.offset, 3)

    def describe(self) -> str:
        span = ""
        if self.start is not None:
            end = self.start + (self.dur or 0.0)
            span = f", {self.start:.1f}-{end:.1f}s"
        return f"{self.name} audio ({self.audio.name}{span})"


def from_video(project: "Project", first: float, last: float,
               pad: float = 2.0) -> TimingSource:
    """Time against the video's own audio, over the span the lines cover.

    Decoding only that span matters: an acoustic model over a whole episode is
    minutes of work for audio that has no lyrics to match. The slice start
    becomes the offset, since the decoded array's t=0 is that instant.
    """
    start = max(first - pad, 0.0)
    dur = max(last + pad - start, 0.1)
    return TimingSource(audio=project.video, name="video",
                        start=start, dur=dur, offset=start,
                        conditioned=project.conditioned,
                        cache_tag=f"video.{int(start)}-{int(start + dur)}")


def from_reference(project: "Project") -> TimingSource:
    """Time against the audio phase 1 aligned to, mapped by the splice offset.

    Only valid when the edit is a literal splice. With several chunks the offset
    is not a single number, so callers must clamp each line to one chunk first
    (see Project.segment_at_video); this carries the first chunk's offset as a
    default for the common single-chunk case.
    """
    offset = project.segments[0].offset if project.segments else 0.0
    return TimingSource(audio=project.align_audio, name="reference",
                        start=project.audio_start, dur=project.audio_dur,
                        offset=offset, conditioned=project.conditioned,
                        cache_tag="ref")
