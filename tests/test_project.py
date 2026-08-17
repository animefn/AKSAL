"""Directory-native project layout and durable state."""

from pathlib import Path

import pytest

from aksal.locate import Segment
from aksal.project import Project, STATE_NAME, default_output_dir, project_name


def make(root=Path("D:/karaoke/OP01.aksal"), **values):
    return Project(root=Path(root), video=Path("v.mkv"), mode="reference",
                   align_audio=Path("a.wav"), **values)


def test_default_directory_is_beside_the_input():
    assert default_output_dir(Path("D:/shows/S01.E01.mkv")) == Path(
        "D:/shows/S01.E01.aksal")


def test_artifact_name_is_consistent_for_inputs_and_project_directories():
    assert project_name(Path("OP01.aksal")) == "OP01"
    assert project_name(Path("OP01.lines.ass")) == "OP01"
    assert default_output_dir(Path("D:/kara/OP01.lines.ass")) == Path(
        "D:/kara/OP01.aksal")


def test_artifacts_have_clear_subdirectories():
    project = make()
    assert project.state == project.root / "project.json"
    assert project.lines_file == project.root / "OP01.lines.ass"
    assert project.readings == project.root / "readings.tsv"
    assert project.vocals == project.root / "audio" / "vocals.wav"
    assert project.emissions_cache_for("abc") == (
        project.root / "cache" / "emissions" / "abc.pt")
    assert project.kara_jp_file == project.root / "OP01.kara.jp.ass"
    assert project.kara_kana_file == project.root / "OP01.kara.kana.ass"
    assert project.kara_romaji_file == project.root / "OP01.kara.romaji.ass"


def test_save_creates_the_complete_layout(tmp_path):
    project = make(tmp_path / "song.aksal")
    project.save()
    assert project.state.exists()
    assert project.audio_dir.is_dir()
    assert project.emissions_dir.is_dir()
    assert not (project.root / "output").exists()


def test_round_trip(tmp_path):
    project = make(
        tmp_path / "song.aksal",
        segments=[Segment(0.5, 87.6, 36.5, 123.6, 36.0, support=7539)],
        timing_model="timing/id", selection_model="selection/id",
        analyser="unidic", lyrics_source="romaji", conditioned=False,
        separated=True,
        audio_start=1.25, audio_dur=89.5,
    )
    project.save()
    loaded = Project.load(project.root)
    assert loaded.timing_model == "timing/id"
    assert loaded.selection_model == "selection/id"
    assert loaded.analyser == "unidic"
    assert loaded.lyrics_source == "romaji"
    assert loaded.conditioned is False
    assert loaded.separated is True
    assert loaded.audio_start == pytest.approx(1.25)
    assert loaded.audio_dur == pytest.approx(89.5)
    assert loaded.segments[0].offset == pytest.approx(36.0)


def test_unsupported_or_missing_state_is_rejected(tmp_path):
    with pytest.raises(SystemExit, match="project not found"):
        Project.load(tmp_path / "missing")
    root = tmp_path / "old"
    root.mkdir()
    (root / STATE_NAME).write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(SystemExit, match="Unsupported"):
        Project.load(root)


def test_time_mapping_round_trips():
    project = make(segments=[Segment(0.0, 87.0, 36.0, 123.0, 36.0)])
    assert project.to_video(10.0) == pytest.approx(46.0)
    assert project.to_audio(46.0) == pytest.approx(10.0)


def test_clamp_snaps_outside_a_segment():
    project = make(segments=[Segment(0.0, 87.0, 36.0, 123.0, 36.0)])
    assert project.clamp_to_audio(35.0) == pytest.approx(0.0)
    assert project.clamp_to_audio(200.0) == pytest.approx(87.0)
