"""State carried between phase 1 and phase 2.

**Everything lives beside the output you asked for**, sharing its stem. There is
no project directory, no hidden state, nothing written to the tool's own folder:

    D:/karaoke/OP01.lines.ass        the file you edit
    D:/karaoke/OP01.lyrics.txt       fetched lyrics, editable
    D:/karaoke/OP01.readings.tsv     reading overrides, editable
    D:/karaoke/OP01.aksal.json       what phase 1 found
    D:/karaoke/OP01.emissions.pt     cache
    D:/karaoke/OP01.vocals.wav       isolated vocal stem
    D:/karaoke/OP01.kara.jp.ass      phase 2 output

The caches sit with the rest on purpose. They are large, but keeping them here
means `OP01.*` removes every trace of a run -- there is nowhere else to look.

Phase 2 still needs to know what phase 1 decided (which audio was aligned
against, and how its timeline maps to the video's), which is what the .json
holds. It is a visible sibling rather than something to go hunting for.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .locate import Segment
from .model_spec import DEFAULT_MODEL, cache_tag

STATE_SUFFIX = ".aksal.json"

# Suffixes a person adds while editing, stripped when deriving the stem so that
# OP01.lines.fixed.ass still finds OP01.aksal.json.
EDIT_SUFFIXES = {"lines", "fixed", "corrected", "edited", "edit", "final",
                 "kara", "jp", "romaji", "kana"}


def stem_of(path: Path) -> Path:
    """Path without its extension or any editing suffixes.

    OP01.lines.ass -> OP01 ;  OP01.lines.fixed.ass -> OP01
    """
    parts = path.name.split(".")
    if len(parts) > 1:
        parts.pop()                       # drop the extension
    while len(parts) > 1 and parts[-1].lower() in EDIT_SUFFIXES:
        parts.pop()
    return path.parent / ".".join(parts)


@dataclass
class Project:
    base: Path                       # e.g. D:/karaoke/OP01  (no extension)
    video: Path
    mode: str                        # "reference" | "video"
    align_audio: Path                # what emissions were computed over
    reference: Path | None = None
    segments: list[Segment] = field(default_factory=list)
    # `model` is retained for old callers and old state files. New code uses
    # the two explicit roles below.
    model: str = ""
    timing_model: str = ""
    selection_model: str = ""
    lyrics_source: str = "jp"        # "jp" | "romaji"
    conditioned: bool = True

    # Slice of align_audio to decode. Not persisted -- re-derived each run.
    audio_start: float | None = None
    audio_dur: float | None = None

    def __post_init__(self) -> None:
        legacy = self.model or DEFAULT_MODEL
        self.timing_model = self.timing_model or legacy
        self.selection_model = self.selection_model or legacy
        # Keep the compatibility attribute meaningful for callers which have
        # not learned about roles yet. It is never used to resolve new runs.
        self.model = self.model or (
            self.timing_model
            if self.timing_model == self.selection_model else ""
        )

    @property
    def name(self) -> str:
        return self.base.name

    # --- sibling paths -------------------------------------------------------
    def sibling(self, suffix: str) -> Path:
        """A file beside the output, sharing its stem."""
        return self.base.parent / (self.base.name + suffix)

    @property
    def state_file(self) -> Path:
        return self.sibling(STATE_SUFFIX)

    @property
    def lyrics(self) -> Path:
        return self.sibling(".lyrics.txt")

    @property
    def readings_tsv(self) -> Path:
        return self.sibling(".readings.tsv")

    @property
    def lines_file(self) -> Path:
        return self.sibling(".lines.ass")

    @property
    def vocals(self) -> Path:
        return self.sibling(".vocals.wav")

    @property
    def window_wav(self) -> Path:
        return self.sibling(".window.wav")

    @property
    def emissions_cache(self) -> Path:
        """Cache name encodes what the matrix was computed over.

        Emissions depend on (model, audio, conditioning). Reusing a cache across
        a changed window would silently align against the wrong frames, so the
        window is part of the name rather than something to remember.
        """
        span = ""
        if self.segments:
            s = self.segments[0]
            span = f".{int(s.ref_start)}-{int(s.ref_end)}"
        raw = "" if self.conditioned else ".raw"
        model = cache_tag(self.timing_model)
        return self.sibling(f".emissions.{model}{span}{raw}.pt")

    def emissions_cache_for(self, source_tag: str,
                            model: str | None = None) -> Path:
        """An emissions cache for phase 2 or another named audio source."""
        return self.sibling(
            f".emissions.{cache_tag(model or self.timing_model)}."
            f"{source_tag}.pt"
        )

    # --- segment lookup ------------------------------------------------------
    def segment_at_ref(self, t: float) -> Segment | None:
        for s in self.segments:
            if s.contains_ref(t):
                return s
        return None

    def segment_at_video(self, t: float) -> Segment | None:
        for s in self.segments:
            if s.contains_ep(t):
                return s
        return None

    def spans_cut(self, a: float, b: float) -> bool:
        """True if reference times `a` and `b` sit in different retained chunks.

        A lyric line spanning a cut has middle syllables that are simply not in
        the video. Mapping its ends independently produces a short, plausible
        looking subtitle covering words that were never broadcast -- which is
        worse than dropping it, because nothing looks wrong.
        """
        sa, sb = self.segment_at_ref(a), self.segment_at_ref(b)
        return sa is not None and sb is not None and sa is not sb

    # --- time mapping --------------------------------------------------------
    def to_video(self, t: float) -> float | None:
        """Align-audio time -> video time."""
        for s in self.segments:
            if s.contains_ref(t):
                return round(t + s.offset, 3)
        return None

    def to_audio(self, t: float) -> float | None:
        """Video time -> align-audio time."""
        for s in self.segments:
            if s.contains_ep(t):
                return round(t - s.offset, 3)
        return None

    def clamp_to_audio(self, t: float) -> float:
        """Video time -> align-audio time, snapping to the nearest segment.

        Phase 2 works from line windows you may have nudged outward past a
        segment edge; refusing them would silently drop the first or last line.
        """
        if not self.segments:
            return t
        exact = self.to_audio(t)
        if exact is not None:
            return exact
        best = min(self.segments,
                   key=lambda s: min(abs(t - s.ep_start), abs(t - s.ep_end)))
        return round(min(max(t - best.offset, best.ref_start), best.ref_end), 3)

    # --- persistence ---------------------------------------------------------
    def save(self) -> None:
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({
            "video": str(self.video),
            "mode": self.mode,
            "align_audio": str(self.align_audio),
            "reference": str(self.reference) if self.reference else None,
            "segments": [s.to_dict() for s in self.segments],
            "model": self.model,
            "timing_model": self.timing_model,
            "selection_model": self.selection_model,
            "lyrics_source": self.lyrics_source,
            "conditioned": self.conditioned,
        }, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, base: Path) -> "Project":
        path = base.parent / (base.name + STATE_SUFFIX)
        if not path.exists():
            raise SystemExit(
                f"no state file at {path}.\n"
                "  Run phase1 first, or pass --video to align a hand-made "
                "subtitle without one.")
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            base=base,
            video=Path(d["video"]), mode=d["mode"],
            align_audio=Path(d["align_audio"]),
            reference=Path(d["reference"]) if d.get("reference") else None,
            segments=[Segment(**s) for s in d.get("segments", [])],
            model=d.get("model", ""),
            timing_model=d.get("timing_model", ""),
            selection_model=d.get("selection_model", ""),
            lyrics_source=d.get("lyrics_source", "jp"),
            conditioned=d.get("conditioned", True),
        )
