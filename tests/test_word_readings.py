"""Single words the analyser reads wrong, and the ones it must be left alone on.

These corrections were mined from 109 verified songs of hand-made karaoke --
what a human transcribed as SUNG, against what the analyser reads. That gives
the correction real evidence, but it also makes the mechanism dangerous: an
entry applies in every song, so a reading that is merely USUALLY right would
break the songs where the other reading was sung.

Half of these tests therefore pin what must NOT be corrected. Those are the
regressions worth catching, because adding an entry always looks like an
improvement in the song that motivated it.
"""
from aksal import readings


def _reading(text: str, surface: str) -> str:
    words = readings.analyse_words(readings.normalise_surface(text))
    return next(k for s, k in words if s == surface)


def test_bokura_is_not_bokutou():
    """僕等 has no reading ぼくとう; the analyser invents it."""
    assert _reading("僕等", "僕等") == "ぼくら"
    assert _reading("僕等の未来", "僕等") == "ぼくら"


def test_shikabane_not_kabane():
    """かばね is archaic. Sung しかばね in 3 of 3 corpus occurrences, かばね in none."""
    assert _reading("屍", "屍") == "しかばね"
    assert _reading("屍を越えて", "屍") == "しかばね"


def test_corrections_are_whole_words_only():
    """A correction keys on a WORD, never a substring of one.

    屍 and 僕等 are short and appear inside longer words. Matching on substrings
    would rewrite readings the analyser had right.
    """
    assert _reading("仲間", "仲間") == "なかま"
    assert _reading("人間", "人間") == "にんげん"


def test_ambiguous_readings_are_left_alone():
    """間 is genuinely context-dependent, and the analyser already handles it.

    あいだ and ま are both ordinary readings with different meanings. Forcing
    either would fix one song and break another, so 間 must stay out of the
    correction table however often the corpus disagrees with us.
    """
    assert "間" not in readings.WORD_READINGS
    assert _reading("間", "間") == "ま"
    assert _reading("この間", "間") == "ま"


def test_asu_is_not_forced_to_ashita():
    """明日 stays as the analyser reads it, and the reason is TIMING.

    Singers prefer あした -- 7 corpus songs -- but あす and あした differ in mora
    count, so forcing one changes how every line containing it is timed. A 55%
    majority does not justify retiming the other 45%.
    """
    assert "明日" not in readings.WORD_READINGS
    assert _reading("明日", "明日") == "あす"
