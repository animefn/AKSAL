"""Reading disputes: nominated by a second engine, decided by the audio.

The tool's analyser is right far more often than any alternative measured
(0.963 against pykakasi's 0.934 over the corpus), so a second engine can never
be trusted directly. What it can do is point at a word worth checking, and the
singer settles it.

These tests pin the GATE rather than the verdict. The verdict needs audio;
the gate is what stops the check firing on things that are not disputes at
all, and that is where the measured failures were.
"""
from aksal import readings


def test_a_contested_kanji_nominates_a_rival():
    # Measured over six songs: the audio preferred the rival for these, and
    # was right -- 風 is kaze here, not fuu.
    assert readings.rival_reading("風", "ふう") == "かぜ"
    assert readings.rival_reading("数", "すう") == "かず"


def test_kana_never_nominates():
    """Kana spells its own reading, so there is nothing to arbitrate."""
    assert readings.rival_reading("いつか", "いつか") is None
    assert readings.rival_reading("そんなに", "そんなに") is None


def test_particles_never_nominate():
    """を/は/へ are converted to their SUNG form here on purpose.

    pykakasi keeps the written form, so every such 'disagreement' is our own
    deliberate choice. Measured, this alone accounted for 15 of 16 apparent
    disputes -- and since を and お are the same sound, the audio cannot
    separate them anyway, so the margin would be noise.
    """
    assert readings.rival_reading("を", "お") is None
    assert readings.rival_reading("は", "わ") is None


def test_agreement_is_not_a_dispute():
    assert readings.rival_reading("永遠", "えいえん") is None


def test_unequal_mora_counts_do_nominate(monkeypatch):
    """The filter that USED to make this viable, and now only breaks it.

    An equal-mora-count requirement was correct while the scoring could not
    compare candidates of different length -- the metric of the day picked the
    shorter one 88-95% of the time whatever was sung. It also discarded every
    dispute that matters: まだ/いまだ is 2 against 3, こころ/しん 3 against 2,
    and this case, えいえん against とわ, 4 against 2.

    `reading_score` no longer has that defect (it scores only the emitting
    frames, so blank padding cannot be collected for free), so the gate is
    gone and an unequal pair must reach the audio. See
    docs/reading-arbitration.md.
    """
    class FakeRival:
        def convert(self, _surface):
            return [{"kana": "トワ"}]            # 2 moras against えいえん's 4

    monkeypatch.setattr(readings, "_RIVAL", FakeRival())
    monkeypatch.setattr(readings, "_RIVAL_TRIED", True)
    assert readings.rival_reading("永遠", "えいえん") == "とわ"


def test_a_split_rival_reading_is_joined_not_discarded(monkeypatch):
    """ichiran emits coarser units than the rival engine, and bailing on a
    split silently switched the whole arbiter off for every compound: 方が良い
    is ONE match here and three segments there. The reading of the whole span
    is what matters, so the pieces are joined."""
    class FakeRival:
        def convert(self, _surface):
            return [{"kana": "カタ"}, {"kana": "ガ"}, {"kana": "ヨイ"}]

    monkeypatch.setattr(readings, "_RIVAL", FakeRival())
    monkeypatch.setattr(readings, "_RIVAL_TRIED", True)
    assert readings.rival_reading("方が良い", "ほうがいい") == "かたがよい"


def test_absent_second_engine_degrades_quietly(monkeypatch):
    monkeypatch.setattr(readings, "_RIVAL", None)
    monkeypatch.setattr(readings, "_RIVAL_TRIED", True)
    assert readings.rival_reading("風", "ふう") is None
