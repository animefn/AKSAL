"""The GUI's argv-building, kept independent of PyQt6.

The GUI is a form in front of ``aksal.cli.main``; these functions are the only
place that turns form values into the argv list the CLI parses. If they drift
from what the CLI flags actually accept, the GUI's Run buttons silently break
for anyone without PyQt6 installed to notice interactively -- hence a plain
pytest module for it, importable with no Qt dependency at all.
"""
from __future__ import annotations

from aksal.gui import params


def test_looks_timed_detects_ass_only():
    assert params.looks_timed("lines.ass")
    assert params.looks_timed("OP01.aksal/OP01.lines.ass")
    assert params.looks_timed('"quoted lines.ASS"')
    assert not params.looks_timed("lyrics.txt")
    assert not params.looks_timed("https://lrclib.net/api/get/123")
    assert not params.looks_timed("some anime opening lyrics search")


def test_phase1_argv_minimal():
    form = params.Phase1Form(video="EP01.mkv", lyrics="lyrics.txt")
    assert form.argv() == [
        "phase1", "--video", "EP01.mkv", "--lyrics", "lyrics.txt",
        "--analyser", "ichiran",
    ]


def test_phase1_argv_with_every_optional_field():
    form = params.Phase1Form(
        video="EP01.mkv", lyrics="lyrics.txt", output_dir="OP01.aksal",
        reference="full.flac", song_start="0:36", duration="90",
        insert_romaji=False, separate_vocals=True)
    assert form.argv() == [
        "phase1", "--video", "EP01.mkv", "--lyrics", "lyrics.txt",
        "--output-dir", "OP01.aksal", "--reference", "full.flac",
        "--song-start", "0:36", "--duration", "90",
        "--no-insert-romaji", "--analyser", "ichiran", "--separate-audio",
    ]


def test_phase2_argv_for_an_existing_project_omits_video():
    # Passing --video here would force phase2 to rebuild the project from
    # scratch, discarding the reference and separation choices phase1 saved.
    form = params.Phase2Form(lines="OP01.aksal/OP01.lines.ass", has_project=True,
                             video="EP01.mkv", reference="full.flac")
    assert form.argv() == ["phase2", "OP01.aksal/OP01.lines.ass"]


def test_phase2_argv_for_a_hand_made_subtitle_requires_video():
    form = params.Phase2Form(
        lines="hand.ass", has_project=False, video="EP01.mkv",
        reference="full.flac", group="word", time_against="reference",
        tracks=("jp",))
    assert form.argv() == [
        "phase2", "hand.ass", "--video", "EP01.mkv", "--reference", "full.flac",
        "--analyser", "ichiran", "--time-against", "reference",
        "--group", "word", "--tracks", "jp",
    ]


def test_phase2_argv_defaults_are_silent():
    form = params.Phase2Form(lines="hand.ass", has_project=False, video="EP01.mkv")
    argv = form.argv()
    assert "--time-against" not in argv
    assert "--group" not in argv
    assert "--tracks" not in argv


def test_default_lines_path_matches_phase1s_own_naming(tmp_path):
    from aksal import project as project_mod

    video = tmp_path / "EP01.mkv"
    video.write_bytes(b"")
    expected_root = project_mod.default_output_dir(video)
    expected = expected_root / f"{project_mod.project_name(expected_root)}.lines.ass"
    assert params.default_lines_path(video, None) == expected


def test_has_existing_project_is_false_for_a_bare_subtitle(tmp_path):
    lines = tmp_path / "hand.ass"
    lines.write_text("[Events]\n", encoding="utf-8")
    assert params.has_existing_project(lines) is False
