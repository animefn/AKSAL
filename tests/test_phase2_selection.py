from argparse import Namespace

import numpy as np
import torch

from aksal import align, ass, audio, reading_selector, readings, timing
from aksal.cli import cmd_phase2
from aksal.locate import Segment
from aksal.project import Project


class FakeAligner:
    blank = 0
    vocab = {"い": 1, "ま": 2, "だ": 3}
    model_identity = "fake-kana-model@1"
    frame_stride = 320
    loaded_models = []

    def __init__(self, model, log=print):
        self.log = log
        self.loaded_models.append(model)

    def tokenise(self, units):
        missing = {char for unit in units for char in unit
                   if char not in self.vocab}
        ids = [self.vocab[char] for unit in units for char in unit
               if char in self.vocab]
        return ids, [], missing

    def emissions(self, _samples, cache=None):
        logits = torch.full((150, 4), -8.0)
        logits[:, 0] = 8.0
        for frame, token in ((55, 1), (65, 2), (75, 3)):
            logits[frame, :] = -8.0
            logits[frame, token] = 8.0
        return logits.log_softmax(dim=-1)

    def align_units(self, _lp, units, frame_offset=0):
        return [
            {"text": unit, "start": (frame_offset + i + 1) * 0.02,
             "end": (frame_offset + i + 2) * 0.02, "conf": 1.0}
            for i, unit in enumerate(units)
        ]


def arguments(lines):
    return Namespace(
        lines=lines, tracks="jp,romaji", video=None, output_dir=None,
        model=None, timing_model=None, selection_model=None, analyser=None,
        separate_vocals=False, time_against="video", device="cpu",
        group="syllable", snap=False, reference=None,
    )


def test_phase2_selects_and_reuses_complete_line_reading(tmp_path, monkeypatch):
    root = tmp_path / "song.aksal"
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"video")
    project = Project(
        root=root, video=video, mode="video", align_audio=video,
        segments=[Segment(0.0, 10.0, 0.0, 10.0, 0.0)],
        lyrics_source="jp", timing_model="timing-model",
        selection_model="selection-model",
    )
    project.save()
    ass.write(
        project.lines_file,
        [ass.Event(1.0, 2.0, "未だ")],
        [ass.STYLE_JP], project=root,
    )

    monkeypatch.setattr(align, "Aligner", FakeAligner)
    monkeypatch.setattr(audio, "prepare",
                        lambda *_args, **_kwargs: np.ones(48_000, np.float32))
    monkeypatch.setattr(audio, "envelope",
                        lambda _samples: np.ones(300, np.float32))
    monkeypatch.setattr(
        timing, "from_video",
        lambda project, *_args, **_kwargs: timing.TimingSource(
            audio=project.video, name="video", offset=0.0,
            conditioned=False, cache_tag="test"),
    )
    monkeypatch.setattr(readings, "analyse_words",
                        lambda _surface: [("未だ", "まだ")])
    monkeypatch.setattr(
        readings, "candidate_readings",
        lambda surface, current: ["いまだ"]
        if (surface, current) == ("未だ", "まだ") else [],
    )
    score_windows = []
    real_select = reading_selector.select

    def capture_score_window(words, selector, log_probs, candidates_of,
                             choices=None):
        score_windows.append(log_probs.shape[0])
        return real_select(words, selector, log_probs, candidates_of,
                           choices=choices)

    monkeypatch.setattr(reading_selector, "select", capture_score_window)

    FakeAligner.loaded_models.clear()
    cmd_phase2(arguments(project.lines_file))
    assert FakeAligner.loaded_models == ["selection-model", "timing-model"]
    # The corrected 1.0-2.0 subtitle window is scored with 0.75 seconds of
    # context on both sides: frames 12 through 137 at 20 ms per frame.
    assert score_windows == [126]
    assert "いまだ" in project.readings.read_text(encoding="utf-8")
    assert project.selections.exists()
    assert project.kara_jp_file.exists()

    # The exact same project must use its saved phase-2 decision rather than
    # invoking the complete-sentence scorer again.
    monkeypatch.setattr(
        reading_selector, "select",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("saved selection was not reused")),
    )
    FakeAligner.loaded_models.clear()
    cmd_phase2(arguments(project.lines_file))
    assert FakeAligner.loaded_models == ["timing-model"]
