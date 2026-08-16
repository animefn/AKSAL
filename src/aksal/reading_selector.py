"""Select ambiguous readings by scoring complete sentences against audio.

Candidate nomination stays in :mod:`aksal.readings`. This module only builds
the complete sentence hypotheses, obtains their CTC likelihoods, and
marginalises those likelihoods back to the ambiguous words.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Callable

import torch

from . import moras


MAX_COMBINATIONS = 256


class SelectionError(RuntimeError):
    """The line could not be compared safely."""


@dataclass(frozen=True)
class WordDecision:
    index: int
    surface: str
    current: str
    chosen: str
    ranked: tuple[tuple[str, float], ...]
    confidence: str

    @property
    def changed(self) -> bool:
        return self.chosen != self.current


@dataclass(frozen=True)
class LineSelection:
    reading: str
    decisions: tuple[WordDecision, ...]
    combinations: int


def _unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


def candidate_choices(
    words: list[tuple[str, str]],
    candidates_of: Callable[[str, str], list[str]],
) -> list[tuple[str, ...]]:
    """Current reading first, followed by every ASKAL-nominated alternative."""
    return [
        _unique((current, *candidates_of(surface, current)))
        for surface, current in words
    ]


def reading_combinations(choices: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    count = math.prod(map(len, choices))
    if count > MAX_COMBINATIONS:
        raise SelectionError(
            f"{count} complete readings exceed the safety limit of "
            f"{MAX_COMBINATIONS}"
        )
    return list(itertools.product(*choices))


def ctc_scores(aligner, log_probs: torch.Tensor,
               targets: list[str]) -> list[float]:
    """Total CTC log likelihood, identical in shape to the standalone scorer."""
    frames = int(log_probs.shape[0])
    scores: list[float] = []
    for target in targets:
        token_ids, _spans, missing = aligner.tokenise(moras.split(target))
        if not token_ids or missing or len(token_ids) > frames:
            scores.append(float("-inf"))
            continue
        labels = torch.tensor(token_ids, dtype=torch.long,
                              device=log_probs.device)
        loss = torch.nn.functional.ctc_loss(
            log_probs.unsqueeze(1),
            labels,
            torch.tensor([frames], dtype=torch.long, device=log_probs.device),
            torch.tensor([len(token_ids)], dtype=torch.long,
                         device=log_probs.device),
            blank=aligner.blank,
            reduction="sum",
            zero_infinity=False,
        )
        scores.append(-float(loss))
    if not any(math.isfinite(score) for score in scores):
        raise SelectionError("the audio interval is too short or unreadable")
    return scores


def probabilities(scores: list[float]) -> list[float]:
    finite = [score for score in scores if math.isfinite(score)]
    peak = max(finite)
    weights = [
        math.exp(score - peak) if math.isfinite(score) else 0.0
        for score in scores
    ]
    total = sum(weights)
    return [weight / total for weight in weights]


def confidence(ranked: list[tuple[str, float]]) -> str:
    top = ranked[0][1]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    if top >= 0.90 and top - runner_up >= 0.80:
        return "highly likely"
    if top >= 0.70 and top - runner_up >= 0.40:
        return "likely"
    return "uncertain"


def select(words: list[tuple[str, str]], aligner,
           log_probs: torch.Tensor, candidates_of,
           choices: list[tuple[str, ...]] | None = None) -> LineSelection:
    """Score full readings, then make conservative word-level decisions."""
    choices = choices or candidate_choices(words, candidates_of)
    combinations = reading_combinations(choices)
    if not any(len(choice) > 1 for choice in choices):
        return LineSelection(
            reading=" ".join(reading for _surface, reading in words),
            decisions=(), combinations=1)

    targets = ["".join(combination) for combination in combinations]
    probs = probabilities(ctc_scores(aligner, log_probs, targets))
    chosen_words = [reading for _surface, reading in words]
    decisions: list[WordDecision] = []

    for index, ((surface, current), alternatives) in enumerate(
            zip(words, choices)):
        if len(alternatives) <= 1:
            continue
        totals = {reading: 0.0 for reading in alternatives}
        for combination, probability in zip(combinations, probs):
            totals[combination[index]] += probability
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        certainty = confidence(ranked)
        # An uncertain comparison remains visible but cannot silently change
        # the reading used for final mora timing.
        chosen = ranked[0][0] if certainty != "uncertain" else current
        chosen_words[index] = chosen
        decisions.append(WordDecision(
            index=index,
            surface=surface,
            current=current,
            chosen=chosen,
            ranked=tuple(ranked),
            confidence=certainty,
        ))

    return LineSelection(
        reading=" ".join(chosen_words),
        decisions=tuple(decisions),
        combinations=len(combinations),
    )
