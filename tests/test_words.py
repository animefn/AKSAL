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


# --- phase 1 romaji hints -----------------------------------------------------

def test_annotation_is_invisible_when_rendered():
    from aksal import ass
    text = romaji.annotate("空を見る", "sora o miru")
    assert ass.ANY_TAG.sub("", text) == "空を見る"


def test_annotation_strips_back_to_the_original():
    text = romaji.annotate("空を見る", "sora o miru")
    assert romaji.strip(text) == "空を見る"


def test_annotation_leaves_real_override_tags_alone():
    """Every genuine ASS tag begins with a backslash, so the pattern cannot
    match one."""
    text = romaji.annotate(r"{\i1}空{\i0}", "sora")
    assert romaji.strip(text) == r"{\i1}空{\i0}"


def test_annotation_cannot_be_closed_early_by_its_own_content():
    text = romaji.annotate("空", "a*RO*b")
    assert romaji.strip(text) == "空"


def test_braces_in_the_romaji_are_neutralised():
    text = romaji.annotate("空", "a{b}c")
    assert romaji.strip(text) == "空"


def test_empty_romaji_leaves_the_line_untouched():
    assert romaji.annotate("空", "") == "空"


def test_is_annotated_detects_only_our_marker():
    assert romaji.is_annotated(romaji.annotate("空", "sora"))
    assert not romaji.is_annotated(r"{\pos(1,2)}空")


def test_phase2_reads_through_an_annotation():
    """phase 2 takes Event.plain, so an annotated phase 1 line must yield the
    Japanese text and nothing else."""
    from aksal import ass
    ev = ass.Event(start=0.0, end=1.0,
                   text=romaji.annotate("空を見る", "sora o miru"))
    assert ev.plain == "空を見る"


# --- inflections belong to the word they inflect ------------------------------

def _romaji_of(text, overrides=None):
    words = readings.resolve_words(text, overrides or {})
    units, owner = moras.split_words(words)
    return "".join(romaji.line_spaced(units, owner))


@pytest.mark.parametrize("text,expected", [
    ("切り捨てて", "kirisutete"),      # verb + conjunctive particle
    ("見上げて歩く", "miagete aruku"),  # ...but the next verb is its own word
    ("行きます", "ikimasu"),           # verb + auxiliary
    ("見た", "mita"),                  # verb + past auxiliary
    ("空へ向かって走った", "sora e mukatte hashitta"),
])
def test_inflections_do_not_become_separate_words(text, expected):
    """The analyser tokenises grammar, not orthography. Romanising each token as
    its own word gives 'kirisute te'."""
    assert _romaji_of(text) == expected


def test_an_auxiliary_on_a_noun_stays_separate():
    """です after a noun is its own word, unlike ます after a verb."""
    assert _romaji_of("学生です") == "gakusei desu"


def test_case_and_topic_particles_never_attach():
    assert _romaji_of("母は花を買う") == "haha wa hana o kau"


def test_explicit_spaces_still_break_words_after_merging():
    """A space in the source is a hard boundary and must survive the merge."""
    assert _romaji_of("見上げ て") == "miage te"


# --- compound nouns -----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("門前払い", "monzenbarai"),      # unidic-lite alone: 門 + 前払い
    ("一切合切", "issaigassai"),      # unidic-lite alone: 一切 + 合切
])
def test_set_phrase_compounds_are_rejoined(text, expected):
    """unidic-lite splits these and gets the READING wrong, not just the
    spacing -- 門前払い would read モン + マエバライ, sounds never sung. ipadic
    knows them as single entries."""
    assert _romaji_of(text) == expected


def test_a_genuine_two_noun_sequence_is_left_split():
    """Only compounds ipadic knows as ONE entry are rejoined; ordinary noun
    pairs keep their boundary."""
    assert _romaji_of("存在証明") == "sonzai shoumei"


def test_compound_repair_does_not_cross_an_explicit_space():
    assert _romaji_of("門前 払い") == "monzen harai"


def test_an_override_still_wins_over_the_repair():
    """The escape hatch remains, for compounds no dictionary has."""
    assert _romaji_of("門前払い", {"門前払い": "と わ"}) == "to wa"


def test_compound_repair_degrades_gracefully_without_ipadic(monkeypatch):
    """ipadic is an optional extra; absent it, we fall back to unidic-lite."""
    monkeypatch.setattr(readings, "_IPADIC", None)
    monkeypatch.setattr(readings, "_IPADIC_TRIED", True)
    assert readings.compound_reading("門前払い") is None
    assert _romaji_of("母は花を買う") == "haha wa hana o kau"
