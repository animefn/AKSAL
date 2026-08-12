"""Flat, visible file layout.

Every artifact of a run is a sibling of the output, sharing its stem. There is
no project directory and nothing is written to the tool's own folder, so
`OP01.*` removes every trace of a run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aksal.locate import Segment
from aksal.project import STATE_SUFFIX, Project, stem_of


# --- stem derivation ----------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("OP01.lines.ass", "OP01"),
    ("OP01.lines.fixed.ass", "OP01"),          # suffixes stack while editing
    ("OP01.lines.corrected.ass", "OP01"),
    ("OP01.kara.jp.ass", "OP01"),
    ("OP01.ass", "OP01"),
    ("OP01", "OP01"),
    ("Show - 01.lines.ass", "Show - 01"),      # spaces and dashes survive
])
def test_stem_of(name, expected):
    assert stem_of(Path("D:/k") / name).name == expected


def test_stem_of_keeps_a_meaningful_dot():
    """Only known editing suffixes are stripped, not any dotted part."""
    assert stem_of(Path("D:/k/S01.E01.lines.ass")).name == "S01.E01"


def test_stem_of_preserves_the_directory():
    assert stem_of(Path("D:/karaoke/OP01.lines.ass")).parent == Path("D:/karaoke")


# --- sibling paths ------------------------------------------------------------

def make(base="D:/karaoke/OP01", **kw):
    return Project(base=Path(base), video=Path("v.mkv"), mode="reference",
                   align_audio=Path("a.wav"), **kw)


def test_every_artifact_is_a_sibling_sharing_the_stem():
    p = make()
    for path in (p.state_file, p.lyrics, p.readings_tsv, p.lines_file,
                 p.vocals, p.emissions_cache):
        assert path.parent == Path("D:/karaoke")
        assert path.name.startswith("OP01.")


def test_one_glob_matches_everything_a_run_produces():
    p = make()
    produced = [p.state_file, p.lyrics, p.readings_tsv, p.lines_file,
                p.vocals, p.window_wav, p.emissions_cache]
    assert all(x.match("OP01.*") for x in produced)


def test_nothing_is_written_to_the_tools_own_folder(tmp_path):
    """The complaint that started this: state used to land wherever the tool
    happened to be run from."""
    p = make(base=str(tmp_path / "sub" / "OP01"))
    p.save()
    assert p.state_file.exists()
    assert p.state_file.parent == tmp_path / "sub"


# --- emission cache identity --------------------------------------------------

def test_cache_name_encodes_the_window():
    """Reusing a cache across a changed window would silently align against the
    wrong frames."""
    a = make(segments=[Segment(0, 87, 36, 123, 36)]).emissions_cache
    b = make(segments=[Segment(0, 60, 36, 96, 36)]).emissions_cache
    assert a != b


def test_cache_name_encodes_conditioning():
    a = make(conditioned=True).emissions_cache
    b = make(conditioned=False).emissions_cache
    assert a != b
    assert "raw" in b.name


# --- persistence --------------------------------------------------------------

def test_round_trip(tmp_path):
    p = make(base=str(tmp_path / "OP01"),
             segments=[Segment(0.5, 87.6, 36.5, 123.6, 36.0, support=7539)],
             model="m", lyrics_source="romaji", conditioned=False)
    p.save()
    q = Project.load(tmp_path / "OP01")
    assert q.mode == p.mode
    assert q.model == "m"
    assert q.lyrics_source == "romaji"
    assert q.conditioned is False
    assert len(q.segments) == 1
    assert q.segments[0].offset == pytest.approx(36.0)


def test_state_file_sits_next_to_the_output(tmp_path):
    p = make(base=str(tmp_path / "OP01"))
    p.save()
    assert (tmp_path / f"OP01{STATE_SUFFIX}").exists()


def test_loading_without_a_state_file_says_what_to_do(tmp_path):
    with pytest.raises(SystemExit, match="no state file"):
        Project.load(tmp_path / "missing")


# --- time mapping is unaffected by the layout change --------------------------

def test_time_mapping_round_trips():
    p = make(segments=[Segment(0.0, 87.0, 36.0, 123.0, 36.0)])
    assert p.to_video(10.0) == pytest.approx(46.0)
    assert p.to_audio(46.0) == pytest.approx(10.0)


def test_clamp_snaps_a_time_just_outside_a_segment():
    p = make(segments=[Segment(0.0, 87.0, 36.0, 123.0, 36.0)])
    assert p.clamp_to_audio(35.0) == pytest.approx(0.0)
    assert p.clamp_to_audio(200.0) == pytest.approx(87.0)
