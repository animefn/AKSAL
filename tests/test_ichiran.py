"""The dictionary analyser: what it fixes, and what it still owes.

Each case here is one UniDic could not get right in principle rather than by
accident. A morphological analyser segments into short units and gives each its
citation reading, so no amount of tuning lets it know that 夜 is よ inside
夜が明ける -- only a dictionary containing that phrase does.

The failures are pinned too. An engine that changes what it gets WRONG is as
much a regression as one that changes what it gets right, and every one of
these was found by a test rather than by reading output.
"""
import pytest

from aksal import readings

pytestmark = pytest.mark.ichiran


def words(text: str) -> list[tuple[str, str]]:
    return readings.analyse_words(readings.normalise_surface(text))


def reading_of(text: str) -> str:
    return "".join(kana for _surface, kana in words(text))


# --- set phrases: the reason this engine exists --------------------------------

def test_a_set_phrase_is_one_word_with_its_own_reading():
    """夜 is よる alone and よ inside this phrase. UniDic gives よる both times."""
    assert words("夜が明けても")[0] == ("夜が明けて", "よがあけて")


def test_tomoni_is_one_word():
    """と共に is totomoni, which is what ichi.moe and every dictionary say."""
    assert ("と共に", "とともに") in words("君と共に")


def test_counters_keep_their_irregular_readings():
    assert reading_of("一度") == "いちど"
    assert reading_of("二度と") == "にどと"
    assert reading_of("三日") == "みっか"


# --- inflection ----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("行きます", "いきます"),        # polite
    ("葬られる", "ほうむられる"),     # passive
    ("待たせる", "またせる"),         # causative
    ("歌われる", "うたわれる"),
])
def test_inflected_forms_are_one_word(text, expected):
    """Missing an inflection does not lose a word, it SHATTERS the line: the
    stem matches and the remaining kana become separate tokens, so 行きます
    came out 行き | ま | す."""
    assert words(text) == [(text, expected)]


def test_iku_is_irregular_and_is_not_confused_with_okonau():
    """行く takes って, not the regular いて. Generating 行いて left the real
    行って out of the index, so it resolved to 行う -- おこなって."""
    assert reading_of("行って") == "いって"
    assert reading_of("行った") == "いった"


@pytest.mark.parametrize("text,expected", [
    ("書いて", "かいて"),      # ku -> ite
    ("泳いで", "およいで"),     # gu -> ide
    ("読んで", "よんで"),      # mu -> nde
    ("待って", "まって"),      # tsu -> tte
])
def test_regular_euphonic_changes_still_apply(text, expected):
    """The iku exception must not leak into ordinary godan verbs."""
    assert reading_of(text) == expected


# --- shape of the output -------------------------------------------------------

def test_readings_are_hiragana_even_for_katakana_words():
    """The acoustic model's vocabulary is hiragana. A katakana kana is simply
    not in it, so the aligner would drop the mora without a word of warning."""
    assert reading_of("カタカナ") == "かたかな"


def test_foreign_words_are_left_whole():
    """JMdict has single-letter entries, so segmenting English returns
    l|i|s|t|e|n -- six cells where a singer sings one word."""
    assert ("listen", "listen") in words("listen")


def test_digits_read_as_their_counter():
    """A digit reaching the aligner has no reading at all, which is worse than
    a wrong one. 1人 is ひとり, not "1" followed by にん."""
    assert reading_of("1人") == "ひとり"
    assert reading_of("2人") == "ふたり"


def test_particles_are_given_their_sung_form():
    """は is written ha and sung wa. JMdict records the spelling."""
    assert reading_of("君は") == "きみわ"
    assert reading_of("空へ") == "そらえ"


# --- known limits, pinned so they cannot drift silently ------------------------

def test_boundaries_are_coarser_than_a_karaoke_timer_would_draw():
    """A DICTIONARY UNIT IS NOT A KARAOKE CELL, and this is the open problem.

    ように and そのまま are single entries, so the dictionary returns them
    whole where a human timer splits them. Measured over the hand-timed corpus
    this produced 19 run-on words against UniDic's 5 -- correct as lexicography
    and too coarse for `--group word`.

    Pinned rather than fixed because the fix is a decision about karaoke cells,
    not about readings, and syllable grouping -- the default -- is unaffected.
    """
    assert words("ように") == [("ように", "ように")]
