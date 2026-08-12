"""Word boundaries: tokenisation, unit ownership, romaji spacing, grouping.

Fixture text is invented, not lyrics.
"""
from __future__ import annotations

import pytest

from aksal import moras, readings, romaji


# --- unit ownership -----------------------------------------------------------

def test_split_words_tracks_which_word_each_unit_came_from():
    units, owner = moras.split_words(["そら", "を", "みる"])
    assert units == ["そ", "ら", "を", "み", "る"]
    assert owner == [0, 0, 1, 2, 2]


def test_split_words_on_empty_input():
    assert moras.split_words([]) == ([], [])


def test_split_words_skips_an_empty_word_without_shifting_ownership():
    units, owner = moras.split_words(["あ", "", "い"])
    assert units == ["あ", "い"]
    assert owner == [0, 2]


def test_group_by_word_gives_inclusive_spans():
    assert moras.group_by_word([0, 0, 1, 2, 2]) == [(0, 1), (2, 2), (3, 4)]


def test_group_by_word_on_empty():
    assert moras.group_by_word([]) == []


def test_group_by_word_single_word():
    assert moras.group_by_word([0, 0, 0]) == [(0, 2)]


# --- romaji spacing -----------------------------------------------------------

def test_spacing_attaches_to_the_last_syllable_of_each_word():
    """A space must never be its own cell -- it would need a duration, stealing
    time from a syllable and desynchronising the two tracks."""
    units, owner = moras.split_words(["そら", "を", "みる"])
    out = romaji.line_spaced(units, owner)
    assert out == ["so", "ra ", "wo ", "mi", "ru"]
    assert len(out) == len(units)


def test_no_trailing_space_on_the_final_word():
    units, owner = moras.split_words(["そら", "を"])
    assert romaji.line_spaced(units, owner)[-1] == "wo"


def test_spacing_preserves_cell_count_exactly():
    units, owner = moras.split_words(["きょう", "は", "あつい"])
    assert len(romaji.line_spaced(units, owner)) == len(units)


def test_single_word_gets_no_spaces():
    units, owner = moras.split_words(["あやかし"])
    assert "".join(romaji.line_spaced(units, owner)) == "ayakashi"


# --- analyser -----------------------------------------------------------------

def test_words_are_separated():
    words = readings.resolve_words("空を見る", {})
    assert len(words) >= 3
    # を is a particle here, so the reading is the spoken お, not the written を.
    assert "".join(words) == "そらおみる"


@pytest.mark.parametrize("text,expected", [
    ("母は", "wa"),      # は as particle is sung "wa"
    ("空へ", "e"),        # へ as particle is sung "e"
    ("本を", "o"),        # を as particle is sung "o"
])
def test_particles_use_the_spoken_reading(text, expected):
    words = readings.resolve_words(text, {})
    units, owner = moras.split_words(words)
    assert "".join(romaji.line_spaced(units, owner)).split()[-1] == expected


def test_long_vowels_keep_their_mora_count():
    """`pron` would render 今日 as キョー, merging two sung beats into one cell.
    Only particles may take the spoken reading."""
    units, _ = moras.split_words(readings.resolve_words("今日", {}))
    assert units == ["きょ", "う"]


def test_explicit_spaces_are_hard_word_boundaries():
    """Lyric sheets use spacing to mark phrasing; that outranks tokenisation."""
    words = readings.resolve_words("空 を 見る", {})
    assert len(words) == 3


# --- overrides ----------------------------------------------------------------

def test_override_spaces_mark_word_breaks():
    words = readings.resolve_words("永遠", {"永遠": "と わ"})
    assert words == ["と", "わ"]


def test_override_without_spaces_is_one_word():
    """Earlier tables had no spaces and meant exactly this, so they keep working."""
    assert readings.resolve_words("永遠", {"永遠": "とわ"}) == ["とわ"]


def test_override_still_wins_over_the_analyser():
    words = readings.resolve_words("永遠", {"永遠": "とわ"})
    assert "".join(words) == "とわ"


# --- romaji input -------------------------------------------------------------

def test_romaji_input_gets_word_boundaries_for_free():
    """No analyser involved -- the spaces are already authoritative."""
    words = readings.resolve_words("sora wo miru", {}, source="romaji")
    assert words == ["そら", "を", "みる"]


def test_romaji_input_without_spaces_is_one_word():
    assert readings.resolve_words("sora", {}, source="romaji") == ["そら"]


# --- both tracks stay in lockstep ---------------------------------------------

def test_word_grouping_preserves_total_syllables():
    units, owner = moras.split_words(readings.resolve_words("空を見上げる", {}))
    spans = moras.group_by_word(owner)
    assert sum(b - a + 1 for a, b in spans) == len(units)
    assert "".join("".join(units[a:b + 1]) for a, b in spans) == "".join(units)


def test_jp_and_romaji_cell_counts_match_in_word_mode():
    units, owner = moras.split_words(readings.resolve_words("空を見る", {}))
    spans = moras.group_by_word(owner)
    jp = ["".join(units[a:b + 1]) for a, b in spans]
    ro = ["".join(romaji.line(units[a:b + 1])) for a, b in spans]
    assert len(jp) == len(ro) == len(spans)
