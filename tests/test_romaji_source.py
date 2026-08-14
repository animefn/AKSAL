"""Romaji input must come back exactly as the user typed it.

The pipeline converts romaji to kana in order to align it. For a long time it
then re-romanised that kana, so a sheet that said "tsudzukete" came back
"tsuzukete" and punctuation was dropped outright.

The guarantee is now structural, not statistical: units, word ownership and the
user's text all come out of ONE walk of the line, so there is no second
derivation to disagree with the first. These tests pin the invariant.
"""
import random

from aksal import moras, readings, romaji


def build(line: str, overrides: dict | None = None):
    return readings.units_and_romaji(line, overrides or {}, "romaji")


def cells(line: str) -> list[str]:
    return build(line)[2]


def test_spans_reassemble_the_input_exactly():
    for text in ["tsudzukete", "kitte", "kan'i", "shou", "PURAIDO", "a, b."]:
        pairs = romaji.to_kana_spans(text)
        assert "".join(src for _kana, src in pairs) == text


def test_split_pairs_groups_identically_to_split():
    for text in ["tsudzukete", "kitte", "PURAIDO", "kan'i", "shou", "matcha"]:
        grouped = moras.split_pairs(romaji.to_kana_spans(text))
        assert [k for k, _s in grouped] == moras.split(romaji.to_kana(text))


def test_tokeniser_is_total():
    """Every character lands in a token -- the base of the whole guarantee."""
    rng = random.Random(1)
    alphabet = list("abkosu!?,.「」 ") + ["  ", "	", "　"]
    for _ in range(3000):
        line = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 20)))
        assert "".join(moras.romaji_tokens(line)) == line


def test_unhepburn_spelling_survives():
    # "dzu" is the case that started this: no Hepburn table emits it.
    assert "".join(cells("tsudzukete")) == "tsudzukete"


def test_capitalisation_survives():
    assert "".join(cells("PURAIDO no uta")) == "PURAIDO no uta"


def test_repeated_spaces_survive():
    assert "".join(cells("kimi ga  ita  basho")) == "kimi ga  ita  basho"


def test_line_edge_whitespace_survives():
    assert "".join(cells("  kimi ga ita  ")) == "  kimi ga ita  "


def test_punctuation_joins_the_cell_before_it():
    # Never its own cell: a \k cell has a duration, and punctuation is not sung.
    assert cells("stop !") == ["stop !"]
    assert cells("yeah...") == ["yeah..."]


def test_punctuation_is_not_a_word_for_group_word():
    _units, owner, ro = build("Hey ... GO !")
    spans = moras.group_by_word(owner)
    assert ["".join(ro[a:b + 1]) for a, b in spans] == ["Hey ... ", "GO !"]


def test_brackets_survive():
    assert "".join(cells("「kyou」")) == "「kyou」"


def test_a_token_that_makes_no_kana_is_folded_not_dropped():
    # A bare number produces no mora, so it cannot own a cell -- but it is the
    # user's text and must still appear.
    assert "".join(cells("yeah... 123 go!")) == "yeah... 123 go!"


def test_cells_stay_one_per_unit():
    units, _owner, ro = build("sono te wo nigirishimeta")
    assert len(ro) == len(units)


def test_word_grouping_keeps_the_source_spelling():
    _units, owner, ro = build("tsudzukete PURAIDO no uta")
    spans = moras.group_by_word(owner)
    assert ["".join(ro[a:b + 1]) for a, b in spans] == [
        "tsudzukete ", "PURAIDO ", "no ", "uta"]


def test_an_override_still_wins():
    """An override names the reading AND the word split, so it must take over.

    The sourced path cannot apply there: the surface no longer describes the
    words, and attaching the user's text to them would misplace it.
    """
    units, _owner, _ro = build("kimi", {"kimi": "き み"})
    assert units == ["き", "み"]


def test_the_line_is_reconstructed_exactly_for_any_input():
    """The invariant as a property, over hostile input.

    Anything with at least one pronounceable mora comes back character for
    character. Anything without has no karaoke to build at all.
    """
    rng = random.Random(7)
    alphabet = (list("abcdefghijkmnoprstuwyz") + list("AEIOU")
                + list("!?,.'-「」()[]~") + [" ", "  ", "	", "　"])
    checked = 0
    for _ in range(4000):
        line = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 24)))
        units, owner, ro = build(line)
        assert len(ro) == len(units) == len(owner), line
        if not units:
            continue
        assert "".join(ro) == line, line
        checked += 1
    assert checked > 2000, "fuzz produced too few pronounceable lines to matter"


def test_plausible_romaji_always_reconstructs():
    rng = random.Random(3)
    syl = ["ka", "ki", "ku", "ke", "ko", "sa", "shi", "su", "na", "no",
           "ta", "te", "to", "mi", "ru", "wa", "n"]
    punct = ["!", "?", ",", ".", "...", "「", "」", "~"]
    for _ in range(1500):
        parts = ["".join(rng.choice(syl) for _ in range(rng.randint(1, 4)))
                 for _ in range(rng.randint(1, 5))]
        if rng.random() < 0.5:
            parts[rng.randrange(len(parts))] += rng.choice(punct)
        line = " ".join(parts)
        _units, _owner, ro = build(line)
        assert "".join(ro) == line, line
