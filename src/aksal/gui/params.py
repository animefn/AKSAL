"""Argv-building logic for the GUI, kept free of any Qt import.

The GUI is a thin form in front of the same ``aksal.cli.main`` the command
line uses -- these functions turn form values into the argv list ``main``
already knows how to parse, so the two front ends can never disagree about
what a flag does. Dependency-free on purpose: it can be unit-tested without
PyQt6 installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def looks_timed(lyrics_value: str) -> bool:
    """A ``.ass`` path is already-timed lines; anything else is Phase 1 input.

    Covers a local lyrics file, an Uta-Net/LRCLIB URL, or a bare LRCLIB search
    term -- all of which are untimed text that Phase 1 still has to place.
    """
    return lyrics_value.strip().strip('"').lower().endswith(".ass")


@dataclass
class Phase1Form:
    video: str
    lyrics: str
    output_dir: str = ""
    reference: str = ""
    song_start: str = ""
    duration: str = ""
    analyser: str = "ichiran"
    insert_romaji: bool = True
    separate_vocals: bool = False

    def argv(self) -> list[str]:
        out = ["phase1", "--video", self.video, "--lyrics", self.lyrics]
        if self.output_dir:
            out += ["--output-dir", self.output_dir]
        if self.reference:
            out += ["--reference", self.reference]
        if self.song_start:
            out += ["--song-start", self.song_start]
        if self.duration:
            out += ["--duration", self.duration]
        if not self.insert_romaji:
            out.append("--no-insert-romaji")
        out += ["--analyser", self.analyser]
        if self.separate_vocals:
            out.append("--separate-audio")
        return out


@dataclass
class Phase2Form:
    lines: str
    has_project: bool
    video: str = ""
    reference: str = ""
    output_dir: str = ""
    time_against: str = "video"
    group: str = "syllable"
    tracks: tuple = ("jp", "romaji")
    analyser: str = "ichiran"
    separate_vocals: bool = False

    def argv(self) -> list[str]:
        out = ["phase2", self.lines]
        # A hand-made subtitle needs --video to build a project from scratch.
        # A project this GUI already made (or one that exists on disk beside
        # the lines file) must NOT get --video: that flag forces phase2 to
        # rebuild the project from nothing, redoing fingerprinting and
        # throwing away the reference and separation choices phase1 recorded.
        if not self.has_project:
            out += ["--video", self.video]
            if self.reference:
                out += ["--reference", self.reference]
            if self.output_dir:
                out += ["--output-dir", self.output_dir]
            out += ["--analyser", self.analyser]
        if self.time_against != "video":
            out += ["--time-against", self.time_against]
        if self.group != "syllable":
            out += ["--group", self.group]
        tracks = ",".join(self.tracks) or "jp,romaji"
        if tracks != "jp,romaji":
            out += ["--tracks", tracks]
        if self.separate_vocals:
            out.append("--separate-audio")
        return out


def default_lines_path(video: Path, output_dir: Path | None) -> Path:
    """Where phase1 will write its lines file, without having to parse its log."""
    from aksal import project as project_mod

    root = (output_dir or project_mod.default_output_dir(video)).resolve()
    return root / f"{project_mod.project_name(root)}.lines.ass"


def has_existing_project(lines_path: Path) -> bool:
    """Whether *lines_path* already belongs to an aksal project on disk."""
    from aksal.cli import resolve_project_root

    try:
        resolve_project_root(lines_path, None)
        return True
    except SystemExit:
        return False
