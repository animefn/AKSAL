"""Character normalisation, and the silent failures it exists to prevent.

Every case here failed silently before: the analyser returned a plausible-
looking reading, or none at all, and nothing downstream could tell the
difference. A character the model cannot pronounce does not raise anything --
the aligner simply hunts for sounds nobody sang and drags its neighbours along.
"""
from aksal import moras, readings


def reading(text: str) -> str:
    return " ".join(k for _s, k in
                    readings.analyse_words(readings.normalise_surface(text)))


def test_old_kanji_forms_get_their_real_reading():
    # 戀 read as レン is wrong; 嬢 had no reading at all in its old form.
    assert reading("戀の歌") == "こい の うた"
    assert reading("孃の唄") == "じょう の うた"


def test_halfwidth_katakana_is_folded():
    assert reading("ｶﾀｶﾅ") == "かたかな"


def test_combining_dakuten_is_composed():
    # か + U+3099 otherwise splits into two units and is aligned as two sounds.
    composed = readings.normalise_surface("が")
    assert composed == "が"
    assert len(moras.split(composed)) == 1


def test_fullwidth_latin_and_digits_are_folded():
    assert readings.normalise_surface("ｋｉｍｉ") == "kimi"
    assert readings.normalise_surface("１２３") == "123"


def test_variation_selectors_are_removed():
    """The old-new kanji mapping emits IVS selectors for some characters.

    Left in, the selector becomes a karaoke cell of its own AND strips the
    kanji of its reading -- so a word that was correct before normalisation
    comes out broken. A variation selector picks a glyph, never a sound.
    """
    for word, want in (("辿り着いた", "たどりついた"),
                       ("疼く", "うずく"),
                       ("嘲り", "あざけり")):
        normalised = readings.normalise_surface(word)
        assert "\U000E0100" not in normalised, word
        assert reading(word) == want, word


def test_ruby_still_wins_after_normalisation():
    assert reading("冒険(スリル)") == "すりる"


def test_iteration_marks_are_left_alone():
    # 時々 already reads correctly; normalisation must not disturb it.
    assert reading("時々") == "ときどき"


def test_normalisation_never_touches_the_romaji_display_path():
    """Romaji output is built from the RAW line, so it stays verbatim."""
    line = "tsudzukete PURAIDO"
    _units, _owner, cells = readings.units_and_romaji(line, {}, "romaji")
    assert "".join(cells) == line


def test_the_dictionary_is_pinned_not_inherited():
    """Readings must be a property of AKSAL, not of the machine it runs on.

    fugashi.Tagger() with no arguments takes whichever dictionary happens to be
    installed, preferring full UniDic over unidic-lite -- and the two disagree:
    UniDic 3.1 reads 方 here as カタ, unidic-lite as ホウ. A user with `unidic`
    installed for an unrelated project would silently get different, worse
    readings from this tool. This caught exactly that during development.
    """
    import unidic_lite

    readings.tagger()                                  # force construction
    assert unidic_lite.DICDIR.replace("\\", "/") in readings._TAGGER_ARGS
    assert reading("その方が良い") == "その ほう が よい"
