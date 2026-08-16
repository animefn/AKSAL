"""Directory-native ASKAL project state and artifact paths."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .locate import Segment
from .model_spec import DEFAULT_MODEL


SCHEMA_VERSION = 2
STATE_NAME = "project.json"


def default_output_dir(input_path: Path) -> Path:
    """Return the default project directory beside *input_path*."""
    return input_path.parent / f"{input_path.stem}.aksal"


@dataclass
class Project:
    """All durable inputs, choices, and paths for one ASKAL run."""

    root: Path
    video: Path | None = None
    mode: str = "video"
    align_audio: Path | None = None
    reference: Path | None = None
    segments: list[Segment] = field(default_factory=list)
    timing_model: str = DEFAULT_MODEL
    selection_model: str = DEFAULT_MODEL
    analyser: str = "ichiran"
    lyrics_source: str | None = None
    conditioned: bool = False
    separated: bool = False
    audio_start: float | None = None
    audio_dur: float | None = None

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        for attribute in ("video", "align_audio", "reference"):
            value = getattr(self, attribute)
            if value is not None:
                setattr(self, attribute, value.resolve())
        if self.mode not in {"reference", "video"}:
            raise ValueError(f"unknown project mode: {self.mode}")
        if self.analyser not in {"ichiran", "unidic"}:
            raise ValueError(f"unknown analyser: {self.analyser}")
        if self.video is None:
            raise ValueError("a project requires a video")
        if self.align_audio is None:
            raise ValueError("a project requires alignment audio")
        if self.lyrics_source not in {None, "jp", "romaji"}:
            raise ValueError(f"unknown lyrics source: {self.lyrics_source}")
        if self.audio_start is not None and self.audio_start < 0:
            raise ValueError("audio_start cannot be negative")
        if self.audio_dur is not None and self.audio_dur <= 0:
            raise ValueError("audio_dur must be positive")

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def state(self) -> Path:
        return self.root / STATE_NAME

    @property
    def lyrics(self) -> Path:
        return self.root / "lyrics.txt"

    @property
    def readings(self) -> Path:
        return self.root / "readings.tsv"

    @property
    def selections(self) -> Path:
        return self.root / "selections.json"

    @property
    def lines_file(self) -> Path:
        return self.root / "lines.ass"

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def emissions_dir(self) -> Path:
        return self.cache_dir / "emissions"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def reference_audio(self) -> Path:
        return self.audio_dir / "reference.m4a"

    @property
    def vocals(self) -> Path:
        return self.audio_dir / "vocals.wav"

    @property
    def window_wav(self) -> Path:
        return self.audio_dir / "window.wav"

    def emissions_cache_for(self, key: str) -> Path:
        return self.emissions_dir / f"{key}.pt"

    def segment_at_ref(self, t: float) -> Segment | None:
        return next((segment for segment in self.segments if segment.contains_ref(t)), None)

    def segment_at_video(self, t: float) -> Segment | None:
        return next((segment for segment in self.segments if segment.contains_ep(t)), None)

    def spans_cut(self, start: float, end: float) -> bool:
        first = self.segment_at_ref(start)
        last = self.segment_at_ref(end)
        return first is not None and last is not None and first is not last

    def to_video(self, t: float) -> float | None:
        segment = self.segment_at_ref(t)
        return round(t + segment.offset, 3) if segment else None

    def to_audio(self, t: float) -> float | None:
        segment = self.segment_at_video(t)
        return round(t - segment.offset, 3) if segment else None

    def clamp_to_audio(self, t: float) -> float:
        if not self.segments:
            return t
        exact = self.to_audio(t)
        if exact is not None:
            return exact
        nearest = min(
            self.segments,
            key=lambda segment: min(abs(t - segment.ep_start), abs(t - segment.ep_end)),
        )
        return round(
            min(max(t - nearest.offset, nearest.ref_start), nearest.ref_end), 3
        )

    def ensure_directories(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.emissions_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        """Atomically save project state after creating its directory layout."""
        self.ensure_directories()
        data = {
            "schema_version": SCHEMA_VERSION,
            "video": str(self.video) if self.video else None,
            "mode": self.mode,
            "align_audio": str(self.align_audio) if self.align_audio else None,
            "reference": str(self.reference) if self.reference else None,
            "segments": [segment.to_dict() for segment in self.segments],
            "timing_model": self.timing_model,
            "selection_model": self.selection_model,
            "analyser": self.analyser,
            "lyrics_source": self.lyrics_source,
            "conditioned": self.conditioned,
            "separated": self.separated,
            "audio_start": self.audio_start,
            "audio_dur": self.audio_dur,
        }
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.root, prefix=".project-",
            suffix=".tmp", delete=False
        ) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        try:
            temporary.replace(self.state)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, root: Path) -> "Project":
        root = root.resolve()
        state = root / STATE_NAME
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SystemExit(f"ASKAL project not found: {state}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Cannot read ASKAL project {state}: {exc}") from exc

        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SystemExit(
                f"Unsupported ASKAL project schema {version!r} in {state}; "
                f"expected {SCHEMA_VERSION}. Create a new output directory."
            )

        def optional_path(value: str | None) -> Path | None:
            return Path(value) if value else None

        try:
            return cls(
                root=root,
                video=optional_path(data.get("video")),
                mode=data.get("mode", "video"),
                align_audio=optional_path(data.get("align_audio")),
                reference=optional_path(data.get("reference")),
                segments=[Segment(**segment)
                          for segment in data.get("segments", [])],
                timing_model=data.get("timing_model", DEFAULT_MODEL),
                selection_model=data.get("selection_model", DEFAULT_MODEL),
                analyser=data.get("analyser", "ichiran"),
                lyrics_source=data.get("lyrics_source"),
                conditioned=bool(data.get("conditioned", False)),
                separated=bool(data.get("separated", False)),
                audio_start=data.get("audio_start"),
                audio_dur=data.get("audio_dur"),
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise SystemExit(f"Malformed ASKAL project {state}: {exc}") from exc
