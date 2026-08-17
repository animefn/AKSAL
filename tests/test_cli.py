"""The CLI surface itself.

These exist because a syntax error sat in cli.py while 208 tests passed: nothing
in the suite imported it. A module the whole tool runs through was the only one
with no coverage at all, so any break in it reached the user rather than the
build.

They assert the SHAPE of the interface, not behaviour -- which flags exist, what
they default to -- so that removing or renaming one is a deliberate act with a
test to update, rather than something that quietly breaks a documented command.
"""
from __future__ import annotations

import pytest

from aksal.cli import (build_parser, display_command, display_reading,
                       reading_score_interval)


def flags(command: str) -> dict:
    sub = build_parser()._subparsers._group_actions[0].choices[command]
    return {opt: a for a in sub._actions for opt in a.option_strings}


def test_displayed_phase2_command_quotes_paths_with_spaces():
    arguments = ["aksal", "phase2", "D:/My Karaoke/OP01.lines.ass"]
    assert display_command(arguments, windows=True) == (
        'aksal phase2 "D:/My Karaoke/OP01.lines.ass"')
    assert display_command(arguments, windows=False) == (
        "aksal phase2 'D:/My Karaoke/OP01.lines.ass'")


def test_display_reading_adds_aksal_romaji():
    assert display_reading("いまだ") == "いまだ [imada]"
    assert display_reading("えい えん") == "えい えん [ei en]"


def test_reading_score_interval_adds_context_and_clamps_to_audio():
    assert reading_score_interval(2.0, 4.0, 10.0) == (1.25, 4.75)
    assert reading_score_interval(0.2, 9.8, 10.0) == (0.0, 10.0)
    assert reading_score_interval(12.0, 13.0, 10.0) == (10.0, 10.0)


def test_the_three_commands_exist():
    choices = build_parser()._subparsers._group_actions[0].choices
    assert set(choices) == {"phase1", "phase2", "find"}


@pytest.mark.parametrize("flag", [
    "--video", "--lyrics", "--reference", "--song-start", "--duration",
    "--insert-romaji", "--lyrics-format", "--model", "--timing-model",
    "--selection-model", "--separate-audio",
    "--no-lrc-hints", "--lead-in", "-o",
    "--output-dir",
])
def test_phase1_keeps_its_documented_flags(flag):
    assert flag in flags("phase1")


@pytest.mark.parametrize("flag", ["--video", "--reference", "--group",
                                 "--tracks", "--model", "--timing-model",
                                 "--selection-model", "--separate-audio",
                                 "--time-against", "--output-dir"])
def test_phase2_keeps_its_documented_flags(flag):
    assert flag in flags("phase2")


@pytest.mark.parametrize("flag", ["--anime", "--video", "--op", "--ed",
                                 "--song-start", "--pick", "--yes", "--run"])
def test_find_keeps_its_documented_flags(flag):
    assert flag in flags("find")


@pytest.mark.parametrize("gone", ["--no-preprocess", "--search",
                                  "--search-window", "--out", "--project"])
def test_removed_flags_stay_removed(gone):
    """--no-preprocess became the default and was deleted rather than left as
    an inert alias; --search and --search-window said in a second vocabulary
    what --song-start and --duration already say."""
    assert gone not in flags("phase1")
    assert gone not in flags("phase2")


def test_separation_is_off_by_default():
    """Measured a wash for four times the runtime, so it must be opt-in."""
    assert flags("phase1")["--separate-audio"].default is False


def test_the_model_defaults_to_the_built_in_one():
    assert flags("phase1")["--model"].default is None


def test_role_specific_models_default_to_the_general_model():
    assert flags("phase1")["--timing-model"].default is None
    assert flags("phase1")["--selection-model"].default is None


@pytest.mark.parametrize("argv,expected", [
    ([], ("sakasegawa/japanese-wav2vec2-large-hiragana-ctc",) * 2),
    (["--model", "X"], ("X", "X")),
    (["--timing-model", "Y"],
     ("Y", "sakasegawa/japanese-wav2vec2-large-hiragana-ctc")),
    (["--selection-model", "Z"],
     ("sakasegawa/japanese-wav2vec2-large-hiragana-ctc", "Z")),
    (["--model", "X", "--timing-model", "Y"], ("Y", "X")),
    (["--model", "X", "--selection-model", "Z"], ("X", "Z")),
    (["--model", "X", "--timing-model", "Y", "--selection-model", "Z"],
     ("Y", "Z")),
])
def test_model_precedence(argv, expected):
    from aksal.model_spec import resolve

    values = iter(argv)
    supplied = dict(zip(values, values))
    assert resolve(supplied.get("--model"), supplied.get("--timing-model"),
                   supplied.get("--selection-model")) == expected


def test_song_start_accepts_the_three_timestamp_forms():
    from aksal.cli import parse_time

    assert parse_time("96.4") == pytest.approx(96.4)
    assert parse_time("1:36.4") == pytest.approx(96.4)
    assert parse_time("0:01:36.4") == pytest.approx(96.4)
    with pytest.raises(Exception):
        parse_time("nonsense")


def test_find_does_not_require_a_video():
    """Looking up what a show's theme is should not demand the episode. The
    episode is only needed to VERIFY a downloaded track, and someone asking
    "what is this song" has not got that far yet."""
    assert flags("find")["--video"].required is False


def test_romaji_hints_are_on_by_default():
    """Phase 1 exists to be corrected in Aegisub, which is impossible if you
    cannot tell the lines apart. The hint renders as nothing, so the cost of
    having it on is zero and the cost of forgetting it is a wasted pass."""
    a = flags("phase1")["--insert-romaji"]
    assert a.default is True
    assert "--no-insert-romaji" in flags("phase1")
