"""Romaji input must come back as the user typed it.

The pipeline converts romaji to kana to align it, and for a long time it then
re-romanised that kana -- so a sheet that said "tsudzukete" came back
"tsuzukete". These lock the round trip.
"""
from aksal import moras, readings, romaji


def cells(line: str, overrides: dict | None = None) -> list[str] | None:
    key = readings.normalise_surface(line)
    words = readings.resolve_words(key, overrides or {}, "romaji")
    _units, owner = moras.split_words(words)
    return romaji.line_sourced(key, words, owner)


def test_spans_reassemble_the_input_exactly():
    for text in ["tsudzukete", "kitte", "kan'i", "shou", "PURAIDO", "a, b."]:
        pairs = romaji.to_kana_spans(text)
        assert "".join(src for _kana, src in pairs) == text


def test_split_pairs_groups_identically_to_split():
    for text in ["tsudzukete", "kitte", "PURAIDO", "kan'i", "shou", "matcha"]:
        grouped = moras.split_pairs(romaji.to_kana_spans(text))
        assert [k for k, _s in grouped] == moras.split(romaji.to_kana(text))


def test_unhepburn_spelling_survives():
    # "dzu" is the case that started this: no Hepburn table emits it.
    assert "".join(cells("tsudzukete")) == "tsudzukete"


def test_capitalisation_survives():
    assert "".join(cells("PURAIDO no uta")) == "PURAIDO no uta"


def test_repeated_spaces_survive():
    assert "".join(cells("kimi ga  ita  basho")) == "kimi ga  ita  basho"


def test_cells_stay_one_per_mora():
    line = "sono te wo nigirishimeta"
    words = readings.resolve_words(line, {}, "romaji")
    units, owner = moras.split_words(words)
    got = romaji.line_sourced(line, words, owner)
    assert got is not None and len(got) == len(units)


def test_declines_when_the_word_count_disagrees():
    # An override defines its own word split, so the source line no longer
    # describes these words -- better to fall back than to attach the user's
    # text to the wrong syllable.
    words = ["か", "み"]
    assert romaji.line_sourced("kami", words, [0, 1]) is None


def test_declines_when_moras_do_not_regroup():
    assert romaji.line_sourced("zzz", ["ねこ"], [0, 0]) is None


def test_word_grouping_keeps_the_source_spelling():
    # --group word joins the per-mora cells; re-romanising the units there
    # would have discarded the user's text on this path alone.
    line = "tsudzukete PURAIDO no uta"
    words = readings.resolve_words(line, {}, "romaji")
    units, owner = moras.split_words(words)
    ro = romaji.line_sourced(line, words, owner)
    spans = moras.group_by_word(owner)
    assert ["".join(ro[a:b + 1]) for a, b in spans] == [
        "tsudzukete ", "PURAIDO ", "no ", "uta"]
