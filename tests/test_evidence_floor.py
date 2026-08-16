"""What the audio is allowed to decide, and what it must hand back.

Three outcomes, and the boundaries between them are the whole design:

  SILENT      the audio confidently backs the reading we already had. Most
              words carry some rival in a dictionary this large, so a
              confirmation must produce nothing or the real disputes drown.
  audio       the audio confidently prefers the OTHER reading. The reading is
              changed and the change is announced.
  unclear     the margin is too small, or the span is unreadable. The
              dictionary's reading stands and the alternative is named.

Below MIN_EVIDENCE neither side is believed at all. That case is real: 方 once
scored 0.0009 for our reading against 0.0003 for the rival -- against a median
of 0.085 for an ordinary aligned syllable -- and the wrong reading "won", so
nothing was flagged and the error passed in silence.

The comparison needs a model, so these drive the decision logic with stubbed
scores: what is pinned is which outcome each pair produces, never a number the
acoustic model happened to emit.
"""
import torch

from aksal import align as align_mod

OURS, RIVAL = "かた", "ほう"


def _decide(ours_score: float, rival_score: float):
    """disputed_readings over one word, with both candidate scores stubbed.

    Scores are in `reading_score`'s units -- mean log-probability over the
    emitting frames -- so they are negative and a bigger number is better.

    The aligner is built without __init__ on purpose: loading a 630 MB acoustic
    model to test a comparison would make this a slow test of the wrong thing.
    """
    aligner = object.__new__(align_mod.Aligner)
    aligner.reading_score = lambda _crop, kana: (
        ours_score if kana == OURS else rival_score)

    lp = torch.zeros((40, 4))
    cells = [{"start": 0.0, "conf": 0.5}, {"start": 0.1, "conf": 0.5}]
    return aligner.disputed_readings(lp, cells, [("方", OURS)], [0, 0],
                                     lambda _s, _k: [RIVAL])


# A margin comfortably over the gate, and one comfortably under it, expressed
# relative to the constant so the tests follow it if it is retuned.
WIDE = align_mod.MARGIN_DECIDE + 1.0
NARROW = align_mod.MARGIN_DECIDE / 3


def test_an_unreadable_span_decides_nothing():
    """The Q1 case: both candidates far below anything legible.

    The margin between two meaningless numbers is itself meaningless, so a
    wide one must not license a decision.
    """
    [got] = _decide(align_mod.LOG_MIN_EVIDENCE - 1,
                    align_mod.LOG_MIN_EVIDENCE - 1 - WIDE)
    assert got["verdict"] == "unclear"
    assert got["chosen"] == OURS


def test_unreadable_holds_even_when_our_reading_wins():
    """Winning on noise is not winning.

    Our score being the higher of two illegible numbers is exactly the state
    that used to pass silently, so it must still be surfaced.
    """
    [got] = _decide(align_mod.LOG_MIN_EVIDENCE - 2,
                    align_mod.LOG_MIN_EVIDENCE - 5)
    assert got["verdict"] == "unclear"


def test_a_clear_win_for_the_rival_changes_the_reading():
    """This is the point of the mechanism: the singer overrules the dictionary."""
    [got] = _decide(-1.0 - WIDE, -1.0)
    assert got["verdict"] == "audio"
    assert got["chosen"] == RIVAL
    assert got["theirs"] == RIVAL


def test_a_narrow_win_for_the_rival_is_not_enough():
    """Accuracy is ~93% over the confident quarter and ~78% overall, so a bare
    argmax spends its accuracy on the near-ties -- the cases that should be
    left alone. A close call keeps the dictionary's reading and says so."""
    [got] = _decide(-1.0 - NARROW, -1.0)
    assert got["verdict"] == "unclear"
    assert got["chosen"] == OURS
    assert got["theirs"] == RIVAL


def test_a_confident_confirmation_is_silent():
    """Almost every word has SOME rival in JMdict -- 今日 alone has four. If
    agreeing produced a flag, the genuine disputes would be unfindable."""
    assert _decide(-1.0, -1.0 - WIDE) == []


def test_a_narrow_win_for_our_reading_is_still_reported():
    """Ours winning by a hair is not a confirmation; the singer may well have
    sung the other one, and a human can settle it in a glance."""
    [got] = _decide(-1.0, -1.0 - NARROW)
    assert got["verdict"] == "unclear"
    assert got["chosen"] == OURS


def test_floor_sits_below_ordinary_words_not_through_them():
    """Pins the floor against the distribution it was derived from.

    `reading_score` measured a median of -6.2 and a p10 of -19.3 over 822
    ordinary words. The floor has to sit under that low tail or it starts
    refusing legible spans -- and this is not hypothetical: the floor was once
    set to log(MIN_EVIDENCE) = -6.9 by converting the OLD metric's units, which
    landed on the median, declared half of all normal words unreadable, and
    made the arbiter decide nothing whatsoever.

    The two constants measure different quantities (mean probability per mora
    vs mean log-probability per emitting frame) and must NOT be derived from
    one another.
    """
    assert align_mod.LOG_MIN_EVIDENCE < -19.3      # under the p10
    assert align_mod.LOG_MIN_EVIDENCE > -27.6      # but above the worst word


def test_a_word_at_median_legibility_is_still_arbitrable():
    """The regression this guards: a floor set at the median made every
    ordinary word "unreadable", so the arbiter never decided anything.

    At the measured median (-6.2), a confident win for our reading must be a
    silent confirmation -- not an "unclear" report caused by the span being
    refused outright.
    """
    assert _decide(-6.2, -6.2 - WIDE) == []


def test_a_word_at_median_legibility_can_be_overruled():
    """The same span, with the rival winning, must actually switch."""
    [got] = _decide(-6.2 - WIDE, -6.2)
    assert got["verdict"] == "audio"
    assert got["chosen"] == RIVAL
