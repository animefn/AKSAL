"""Complete-sentence reading selection, independent of model weights."""
from __future__ import annotations

import math

import pytest
import torch

from aksal import reading_selector


class FakeAligner:
    blank = 0
    vocab = {"か": 1, "れ": 2, "い": 3, "ま": 4, "だ": 5}

    def tokenise(self, units):
        missing = {char for unit in units for char in unit
                   if char not in self.vocab}
        ids = [self.vocab[char] for unit in units for char in unit
               if char in self.vocab]
        return ids, [], missing


def heard(*tokens: int, vocab_size: int = 6) -> torch.Tensor:
    """Confident CTC emissions with a blank between each heard token."""
    path = []
    for token in tokens:
        path.extend((token, 0))
    logits = torch.full((len(path), vocab_size), -8.0)
    for frame, token in enumerate(path):
        logits[frame, token] = 8.0
    return logits.log_softmax(dim=-1)


def alternatives(surface, current):
    return ["いまだ"] if surface == "未だ" and current == "まだ" else []


def test_candidates_include_current_and_every_nominated_reading():
    got = reading_selector.candidate_choices(
        [("未だ", "まだ")], lambda _surface, _current: ["いまだ", "まだ"])
    assert got == [("まだ", "いまだ")]


def test_complete_sentence_audio_selects_the_other_reading():
    words = [("彼", "かれ"), ("未だ", "まだ")]
    # かれ + いまだ
    lp = heard(1, 2, 3, 4, 5)
    got = reading_selector.select(words, FakeAligner(), lp, alternatives)
    assert got.reading == "かれ いまだ"
    assert got.decisions[0].chosen == "いまだ"
    assert got.decisions[0].confidence in {"likely", "highly likely"}


def test_uncertain_audio_keeps_the_existing_reading(monkeypatch):
    monkeypatch.setattr(reading_selector, "ctc_scores",
                        lambda _a, _lp, _targets: [0.0, 0.0])
    got = reading_selector.select(
        [("未だ", "まだ")], FakeAligner(), heard(4, 5), alternatives)
    assert got.reading == "まだ"
    assert got.decisions[0].confidence == "uncertain"
    assert got.decisions[0].chosen == "まだ"


def test_combination_probabilities_are_normalised():
    got = reading_selector.probabilities([-2.0, -3.0, -math.inf])
    assert sum(got) == pytest.approx(1.0)
    assert got[0] > got[1] > got[2]


def test_candidate_explosion_is_refused_without_approximating():
    choices = [(str(i), str(i + 100)) for i in range(9)]  # 512 combinations
    with pytest.raises(reading_selector.SelectionError, match="safety limit"):
        reading_selector.reading_combinations(choices)


def test_unsupported_candidates_cannot_win():
    scores = reading_selector.ctc_scores(
        FakeAligner(), heard(4, 5), ["まだ", "未知"])
    assert math.isfinite(scores[0])
    assert scores[1] == -math.inf
