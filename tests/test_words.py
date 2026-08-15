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


# --- the readings TSV round trip ----------------------------------------------
#
# Phase 1 writes the reading to a TSV; phase 2 reads that file back as an
# OVERRIDE. So the TSV is not a report -- it is the channel the word boundaries
# travel through, and anything the join drops there is gone from the finished
# karaoke. Joining the words with "" once cost every space in the romaji track
# while every unit test on the spacing functions themselves still passed.

def test_the_readings_row_keeps_word_boundaries(tmp_path):
    lyrics = tmp_path / "l.txt"
    lyrics.write_text("母は花を買う\n", encoding="utf-8")
    (_n, _surface, reading), = readings.from_lyrics(lyrics)
    assert reading == "はは わ はな お かう"


def test_a_reading_row_survives_the_tsv_round_trip(tmp_path):
    """Write the table, read it back as overrides, and the boundaries must
    still be there -- this is exactly what phase 2 does."""
    lyrics = tmp_path / "l.txt"
    lyrics.write_text("母は花を買う\n", encoding="utf-8")
    rows = readings.from_lyrics(lyrics)
    tsv = tmp_path / "r.tsv"
    readings.write_table(tsv, [(n, "", s, r) for n, s, r in rows])

    overrides = readings.load_overrides(tsv)
    assert readings.resolve_words("母は花を買う", overrides) == [
        "はは", "わ", "はな", "お", "かう"]


def test_phase2_romaji_cells_are_spaced_after_the_round_trip(tmp_path):
    """The end-to-end property the user sees: spaces in the karaoke track."""
    lyrics = tmp_path / "l.txt"
    lyrics.write_text("母は花を買う\n", encoding="utf-8")
    rows = readings.from_lyrics(lyrics)
    tsv = tmp_path / "r.tsv"
    readings.write_table(tsv, [(n, "", s, r) for n, s, r in rows])

    overrides = readings.load_overrides(tsv)
    words = readings.resolve_words("母は花を買う", overrides)
    units, owner = moras.split_words(words)
    assert "".join(romaji.line_spaced(units, owner)) == "haha wa hana o kau"


def test_phase1_hint_and_phase2_track_agree_on_spacing(tmp_path):
    """Both routes to romaji must produce the SAME string.

    Phase 1's `--insert-romaji` hint spaces the words before the TSV exists, so
    it kept its spaces throughout the bug; phase 2 went through the TSV and lost
    them. Pinning them together is what stops the two drifting apart again.
    """
    text = "母は花を買う"
    lyrics = tmp_path / "l.txt"
    lyrics.write_text(text + "\n", encoding="utf-8")

    # phase 1: straight from the analyser, no TSV involved
    u1, o1 = moras.split_words(readings.resolve_words(text, {}))
    hint = "".join(romaji.line_spaced(u1, o1))

    # phase 2: through the TSV, as an override
    rows = readings.from_lyrics(lyrics)
    tsv = tmp_path / "r.tsv"
    readings.write_table(tsv, [(n, "", s, r) for n, s, r in rows])
    u2, o2 = moras.split_words(
        readings.resolve_words(text, readings.load_overrides(tsv)))
    track = "".join(romaji.line_spaced(u2, o2))

    assert hint == track == "haha wa hana o kau"


def test_an_unspaced_manual_override_is_still_one_word(tmp_path):
    """Back-compat: tables a user corrected before this change had no spaces,
    and meant one word. They must keep meaning that."""
    assert readings.resolve_words("門前払い", {"門前払い": "もんぜんばらい"}) == [
        "もんぜんばらい"]


# --- furigana -----------------------------------------------------------------
#
# Lyric sheets gloss coined readings as kanji + a parenthesised kana reading.
# Kept as literal text it is not a sound anyone sings: the aligner receives the
# kanji reading AND the gloss, and every such word comes out doubled.

def test_a_furigana_gloss_replaces_the_kanji_it_glosses():
    assert readings.strip_ruby("目醒(めざ)めよ") == "めざめよ"


def test_a_katakana_gloss_wins_too():
    """The interesting case: a word written in kanji but sung as a loanword.
    Only the gloss carries that reading -- the analyser cannot invent it."""
    assert readings.strip_ruby("冒険(スリル)を") == "スリルを"


def test_full_width_parentheses_are_handled():
    assert readings.strip_ruby("嘲笑（わら）われても") == "わらわれても"


@pytest.mark.parametrize("text", [
    "サビ(2回)くりかえし",     # a repeat marker, not a reading
    "ah (yeah) sing",          # an aside in latin script
    "(ここから)",              # kana in parens, but no kanji before it
])
def test_a_parenthetical_that_is_not_furigana_is_left_alone(text):
    assert readings.strip_ruby(text) == text


def test_normalise_surface_strips_ruby_so_every_caller_gets_it():
    """Doing it here means the readings table, the alignment units and the
    karaoke text all agree, rather than each stripping it separately."""
    assert readings.normalise_surface("　目醒(めざ)めよ　") == "めざめよ"


# --- the sokuon is a mora ------------------------------------------------------
#
# っ is one of the three special moras (特殊拍) with ん and the long-vowel mark:
# it occupies a beat, and singers give it one. It was previously attached to the
# following mora, which merged two beats into one cell and cost a timing point.
# Its romaji is the doubled consonant of what FOLLOWS, so it needs lookahead --
# which is why `romaji.line` resolves it rather than `romaji.unit`.

@pytest.mark.parametrize("kana,units,cells", [
    ("おもって", ["お", "も", "っ", "て"], ["o", "mo", "t", "te"]),
    ("まっちゃ", ["ま", "っ", "ちゃ"], ["ma", "t", "cha"]),      # Hepburn tch
    ("がっしゅく", ["が", "っ", "しゅ", "く"], ["ga", "s", "shu", "ku"]),
    ("つよく", ["つ", "よ", "く"], ["tsu", "yo", "ku"]),        # never t+su
])
def test_sokuon_is_its_own_cell(kana, units, cells):
    got = moras.split(kana)
    assert got == units
    assert romaji.line(got) == cells


def test_a_trailing_sokuon_has_nothing_to_double():
    r"""A glottal stop at the end of a line. The cell is left empty rather than
    invented, and the `\k` still advances so the tracks stay aligned."""
    units = moras.split("あっ")
    assert units == ["あ", "っ"]
    assert romaji.line(units) == ["a", ""]


def test_spaced_romaji_resolves_the_sokuon_too():
    """`line_spaced` must not romanise unit-by-unit -- that loses the lookahead
    and silently drops every sokuon from the romaji track."""
    words = ["おもって", "ほど"]
    units, owner = moras.split_words(words)
    assert "".join(romaji.line_spaced(units, owner)) == "omotte hodo"


# --- foreign words -------------------------------------------------------------

def test_a_latin_run_is_one_unit_not_one_per_letter():
    """"everyday" became eight karaoke cells, one per letter."""
    assert moras.split("everyday") == ["everyday"]
    assert romaji.line(["everyday"]) == ["everyday"]


def test_latin_inside_japanese_stays_one_unit():
    assert moras.split("あeverydayい") == ["あ", "everyday", "い"]


@pytest.mark.parametrize("word", ["dreamer", "light", "stop", "the", "single"])
def test_english_words_are_recognised_as_foreign(word):
    assert readings.is_foreign(word) is True


def test_a_word_that_parses_as_romaji_can_still_be_foreign():
    """"narrative" is phonotactically perfect Japanese romaji, so shape cannot
    catch it -- only the analyser can."""
    assert readings.is_foreign("narrative") is True


@pytest.mark.parametrize("word", [
    "kagayaki", "hirogetara", "hitoshirazu", "deatteita", "tsudzukete",
])
def test_japanese_words_are_not_called_foreign(word):
    """Conjugated and compound forms especially: a headword-only dictionary
    lookup calls 43% of real lyric words foreign."""
    assert readings.is_foreign(word) is False


def test_a_foreign_word_is_left_unsplit_in_a_romaji_sheet():
    words = readings.resolve_words("everyday shinjitsu", {}, "romaji")
    assert words == ["everyday", "しんじつ"]
    units, owner = moras.split_words(words)
    assert romaji.line_spaced(units, owner) == [
        "everyday ", "shi", "n", "ji", "tsu"]


def test_dzu_round_trips_to_the_right_kana():
    """A common fansub spelling of づ that no Hepburn table produces. Without
    it the word does not parse and gets mistaken for English."""
    assert romaji.to_kana("tsudzukete") == "つづけて"


# --- a line with nothing alignable in it ---------------------------------------

def test_karaoke_text_refuses_a_length_mismatch():
    """Cells and start times are paired POSITIONALLY. When the aligner returns
    fewer entries than there are cells -- which happened as soon as foreign
    words stopped being transliterated, because a wholly English line has no
    kana tokens at all -- the tiling loop indexed off the end, several modules
    away from the cause."""
    from aksal import ass

    with pytest.raises(ValueError, match="diverged"):
        ass.karaoke_text(["a", "b", "c"], [0.0, 0.5], 0.0, 2.0)


def test_karaoke_text_accepts_matching_lengths():
    from aksal import ass

    out = ass.karaoke_text(["a", "b"], [0.0, 0.5], 0.0, 1.0)
    assert out.count(r"\k") == 2


# --- a line ends when its singing ends -----------------------------------------

def test_a_line_tail_is_trimmed_to_its_own_pace():
    r"""Ends come from the NEXT unit's onset, and for the last syllable of a line
    that unit belongs to the following line -- so a line before an instrumental
    ran on until the cap, and `\k` tiling spent the whole rest inside it."""
    from aksal import align

    line = [{"start": 0.0, "end": 0.2}, {"start": 0.2, "end": 0.4},
            {"start": 0.4, "end": 8.0}]          # last one runs to the next line
    assert align.trim_line_tails([line], max_hold=2.0) == 1
    assert line[-1]["end"] == pytest.approx(0.9)  # 0.4 + 2.5 * 0.2


def test_a_genuinely_held_note_is_not_clipped_below_the_floor():
    from aksal import align

    line = [{"start": 0.0, "end": 0.05}, {"start": 0.05, "end": 5.0}]
    align.trim_line_tails([line], max_hold=2.0)
    assert line[-1]["end"] >= 0.05 + 0.35


def test_interior_gaps_are_left_alone():
    """A large gap mid-line is a musical rest, not a tail."""
    from aksal import align

    line = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 3.2},
            {"start": 3.2, "end": 3.4}]
    align.trim_line_tails([line], max_hold=2.0)
    assert line[0]["end"] == 3.0


def test_a_line_with_one_syllable_is_untouched():
    from aksal import align

    line = [{"start": 1.0, "end": 4.0}]
    assert align.trim_line_tails([line], max_hold=2.0) == 0
    assert line[0]["end"] == 4.0


# --- 接続助詞 is two different things under one tag ------------------------------
#
# The analyser gives て and けど the SAME tag (助詞/接続助詞), so the tag cannot
# be used to tell them apart. て is part of the verb form; けど joins two
# clauses and is its own word. Attaching everything with that tag produced
# run-on words like "houmurarerukedo" in real output.

@pytest.mark.parametrize("text,expected", [
    ("切り捨てて", "kirisutete"),          # inflection: must attach
    ("行ってしまえば", "itte shimaeba"),   # ば attaches, the rest does not
])
def test_an_inflectional_ending_attaches(text, expected):
    assert _romaji_of(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("葬られるけど", "houmurareru kedo"),
    ("走るから", "hashiru kara"),
    ("見たけれど", "mita keredo"),
    ("速いし", "hayai shi"),
    ("進みながら", "susumi nagara"),
])
def test_a_clause_joiner_stays_its_own_word(text, expected):
    """These carry the same POS tag as て, so only the surface form separates
    them. Defaulting to 'separate' is the safer direction: a missed inflection
    costs one visible space, a merged joiner costs a run-on word."""
    assert _romaji_of(text) == expected


# --- the segmentation rules, stated as cases -----------------------------------
#
# Word segmentation is a TEXT problem, so it gets a text test. The timing scorer
# folds whitespace away by design -- so that a spacing difference cannot disturb
# a timing comparison -- which also made it structurally unable to see a run-on
# word. One survived the entire corpus and dozens of runs unscored. These cases
# are taken from hand-timed karaoke, where a word boundary is where the human
# chose to break the highlight.

@pytest.mark.parametrize("text,expected", [
    ("絶対的", "zettai teki"),        # 接尾辞: a suffix is its own word
    ("雑音だらけ", "zatsuon darake"),
    ("葬られるけど", "houmurareru kedo"),   # 接続助詞 joining clauses
    ("走るから", "hashiru kara"),
    ("切り捨てて", "kirisutete"),           # 接続助詞 as inflection: attaches
    ("行きます", "ikimasu"),                # 助動詞 on a verb: attaches
    ("母は花を買う", "haha wa hana o kau"),  # particles never attach
])
def test_word_boundaries_match_a_human_timer(text, expected):
    assert _romaji_of(text) == expected


def test_the_corpus_wide_run_on_count_does_not_regress():
    """A ceiling, not a target. Segmentation is currently wrong on a handful of
    words out of ~700 in the hand-timed corpus; this fails if that gets worse.

    Kept as a number rather than a list because the point is to catch a RULE
    that starts over-merging, which is how every spacing bug here has arrived.
    """
    import subprocess
    import sys
    from pathlib import Path

    import os

    audit = Path(__file__).resolve().parents[2] / "tests" / "segaudit.py"
    if not audit.exists():                      # corpus not present in a clone
        pytest.skip("segmentation corpus not available")
    # The engine has to be named explicitly: this runs in a SUBPROCESS, which
    # inherits no fixture, so without it the audit silently uses the shipped
    # default while this test believes it is measuring UniDic. The ceiling
    # below was calibrated against UniDic's boundaries and means nothing for
    # another engine's.
    env = dict(os.environ, AKSAL_ANALYSER="unidic")
    out = subprocess.run([sys.executable, str(audit)], capture_output=True,
                         text=True, encoding="utf-8", errors="replace",
                         cwd=audit.parent, env=env).stdout
    total = int(out.rsplit("corpus:", 1)[1].strip())
    assert total <= 5, f"segmentation regressed to {total} run-on words\n{out}"


# --- bring your own acoustic model ---------------------------------------------

def test_a_kanji_vocabulary_is_rejected():
    """Alignment units are moras, so a full ASR model that writes kanji aligns
    to the wrong sounds -- and gives no sign of it, because the output looks
    entirely ordinary. Measured: one popular Japanese checkpoint has 2,155
    kanji tokens against 74 kana."""
    from aksal import hfmodel

    kanji = {c: i for i, c in enumerate("日本語漢字森川空海山")}
    ok, share = hfmodel.looks_like_kana_vocab(kanji)
    assert not ok and share == 0.0


def test_a_kana_vocabulary_is_accepted():
    from aksal import hfmodel

    kana = {c: i for i, c in enumerate("あいうえおかきくけこ")}
    ok, share = hfmodel.looks_like_kana_vocab(kana)
    assert ok and share == 1.0


def test_a_mixed_vocabulary_is_judged_on_the_kana_share():
    from aksal import hfmodel

    # Two kana in eight tokens: a model that mostly writes kanji, which is
    # exactly the shape of a general ASR checkpoint.
    mixed = {c: i for i, c in enumerate("あい日本語漢字森")}
    ok, share = hfmodel.looks_like_kana_vocab(mixed)
    assert not ok
    assert share == pytest.approx(2 / 8)

    # Just over the line the other way: still accepted.
    ok2, share2 = hfmodel.looks_like_kana_vocab(
        {c: i for i, c in enumerate("あいうえお日本語")})
    assert ok2 and share2 > 0.5


def test_an_empty_vocabulary_does_not_crash():
    from aksal import hfmodel

    assert hfmodel.looks_like_kana_vocab({}) == (False, 0.0)
