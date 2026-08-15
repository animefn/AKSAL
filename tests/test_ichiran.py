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

# --- a dictionary unit is not a karaoke cell -----------------------------------

def test_a_kana_grammatical_pattern_is_split():
    """ように is one JMdict entry, and a human timer writes "you ni".

    It may be split because splitting COSTS NOTHING -- よう + に joins back to
    exactly ように -- and because it is an `exp`, a grammatical pattern rather
    than a word.
    """
    assert words("ように") == [("よう", "よう"), ("に", "に")]


def test_an_ordinary_word_is_never_split_apart():
    """PRESERVING THE KANA IS NOT ENOUGH, and this was a real regression.

    どこか rejoins from どこ + か, so a rule that split whenever the reading
    survived shredded the correct parse どこか|ら|か into どこ|か|ら|か.
    Almost any compound preserves its kana, so the rule has to be narrow: only
    kana-only `exp` entries. A noun phrase like 心の奥 therefore stays whole,
    which costs a boundary and protects every ordinary word.
    """
    assert words("どこか") == [("どこか", "どこか")]
    assert words("心の奥") == [("心の奥", "こころのおく")]


def test_a_join_that_carries_the_reading_survives():
    """夜 is よ only inside the phrase, so splitting would change the kana."""
    assert words("夜が明けても")[0] == ("夜が明けて", "よがあけて")


def test_an_inflected_form_is_never_split():
    """歌われる decomposes into 歌 + われる with the kana intact, and われる is
    not a word anyone times separately. Preserving the reading says nothing
    about whether a boundary is real when the tail is an ending."""
    assert words("歌われる") == [("歌われる", "うたわれる")]


def test_a_kanji_expression_stays_whole():
    """と共に is totomoni. と + 共に gives the same kana and loses the unit the
    writer chose; an all-kana pattern like ように is grammar and does split."""
    assert ("と共に", "とともに") in words("君と共に")


def test_a_lone_kana_is_only_split_off_if_it_is_a_particle():
    """そのまま decomposes into その + ま + ま, which keeps every kana and is
    nonsense as words. JMdict tags ま as a particle, so the tag cannot be
    trusted for this and an explicit list is used."""
    assert words("そのまま") == [("そのまま", "そのまま")]
