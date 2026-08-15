"""A dispute the audio cannot read must be surfaced, not silently settled.

Comparing two confidences with no floor means an unreadable span still yields a
verdict -- whichever candidate won by noise. Measured on the line that raised
this: 方 scored 0.0009 for our reading against 0.0003 for the rival, against a
median of 0.085 for an ordinary aligned syllable. The wrong reading won, so
nothing was flagged and the error passed in silence.

The fix is a third outcome. Below MIN_EVIDENCE neither side is believed and the
word is reported as unresolved -- a note on a row, never a prompt and never a
rewrite, so a run is never blocked waiting for an answer.

The comparison itself needs a model, so these tests drive the decision logic
with stubbed confidences: what is pinned is which outcome each pair produces.
"""
import torch

from aksal import align as align_mod


def _decide(ours_conf: float, rival_conf: float):
    """Run disputed_readings over one word with the two scores stubbed.

    The aligner is built without __init__ on purpose: loading a 630 MB acoustic
    model to test a comparison would make this a slow test of the wrong thing.
    """
    aligner = object.__new__(align_mod.Aligner)
    aligner._mean_conf = lambda _crop, kana: (      # noqa: SLF001
        ours_conf if kana == "かた" else rival_conf)

    frames = 40
    lp = torch.zeros((frames, 4))
    cells = [{"start": 0.0, "conf": 0.5}, {"start": 0.1, "conf": 0.5}]
    words = [("方", "かた")]
    owner = [0, 0]
    return aligner.disputed_readings(lp, cells, words, owner,
                                     lambda _s, _k: "ほう")


def test_no_evidence_is_reported_as_unresolved():
    """The Q1 case: both candidates far below anything legible."""
    got = _decide(0.0009, 0.0003)
    assert got == [("方", "かた", "ほう", False)]


def test_unresolved_holds_even_when_our_reading_wins():
    """Winning on noise is not winning.

    Our score being the higher of two unreadable numbers is exactly the state
    that used to pass silently, so it must still be surfaced.
    """
    [(_surface, _ours, _theirs, decided)] = _decide(0.0009, 0.0001)
    assert decided is False


def test_a_real_disagreement_is_still_flagged():
    """The floor must not suppress genuine catches.

    A floor high enough to silence the weak cases was measured and rejected:
    at 0.005 it would have deleted 風 -> かぜ and 数 -> かず, both correct.
    """
    got = _decide(0.0036, 0.0040)
    assert got == [("方", "かた", "ほう", True)]


def test_agreement_produces_nothing():
    """Where the audio backs our reading with real evidence, there is no flag."""
    assert _decide(0.5, 0.2) == []


def test_floor_sits_below_ordinary_syllables():
    """Pins the floor against the distribution it was derived from.

    Ordinary aligned syllables measured a median of 0.085 and a p10 of 0.0031
    over seven songs. The floor has to sit under the p10, or it starts
    discarding legible spans.
    """
    assert 0 < align_mod.MIN_EVIDENCE < 0.0031
