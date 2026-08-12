"""Project state carried between phase 1 and phase 2.

Phase 2 needs to know what phase 1 decided -- which audio was aligned against,
and how that audio's timeline maps onto the video's. Keeping it in a file (as
opposed to re-deriving it) means phase 2 is cheap and deterministic no matter
how long you spend editing the lines in between.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .locate import Segment

PROJECT_FILE = "project.json"


@dataclass
class Project:
    name: str
    root: Path                       # work/<name>/
    video: Path
    lyrics: Path
    mode: str                        # "reference" | "video"
    align_audio: Path                # what emissions were computed over
    reference: Path | None = None
    segments: list[Segment] = field(default_factory=list)
    model: str = ""
    lyrics_source: str = "jp"        # "jp" | "romaji"
    conditioned: bool = True

    # Slice of align_audio to decode. Not persisted -- it is re-derived from the
    # subtitle on every standalone run, and is None whenever align_audio is
    # already exactly the span we want.
    audio_start: float | None = None
    audio_dur: float | None = None

    # --- paths ---------------------------------------------------------------
    @property
    def readings_tsv(self) -> Path:
        return self.root / "readings.tsv"

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
            span = f"_{int(s.ref_start)}_{int(s.ref_end)}"
        return self.root / f"emissions{span}{'' if self.conditioned else '_raw'}.pt"

    @property
    def stems_dir(self) -> Path:
        return self.root / "stems"

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
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / PROJECT_FILE).write_text(json.dumps({
            "name": self.name,
            "video": str(self.video),
            "lyrics": str(self.lyrics),
            "mode": self.mode,
            "align_audio": str(self.align_audio),
            "reference": str(self.reference) if self.reference else None,
            "segments": [s.to_dict() for s in self.segments],
            "model": self.model,
            "lyrics_source": self.lyrics_source,
            "conditioned": self.conditioned,
        }, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, root: Path) -> "Project":
        path = root / PROJECT_FILE
        if not path.exists():
            raise SystemExit(
                f"no project at {root}. Run phase1 first, or point --project at "
                f"the work directory phase1 printed.")
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            name=d["name"], root=root,
            video=Path(d["video"]), lyrics=Path(d["lyrics"]),
            mode=d["mode"], align_audio=Path(d["align_audio"]),
            reference=Path(d["reference"]) if d.get("reference") else None,
            segments=[Segment(**s) for s in d.get("segments", [])],
            model=d.get("model", ""),
            lyrics_source=d.get("lyrics_source", "jp"),
            conditioned=d.get("conditioned", True),
        )
