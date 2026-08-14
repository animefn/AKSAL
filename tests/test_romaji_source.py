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


def test_punctuation_joins_the_word_before_it():
    # Not its own cell: a \k cell has a duration, and punctuation is not sung.
    assert cells("stop !") == ["stop !"]
    assert cells("yeah...") == ["yeah..."]


def test_punctuation_is_not_a_word_for_group_word():
    line = "Hey ... GO !"
    words = readings.resolve_words(line, {}, "romaji")
    _units, owner = moras.split_words(words)
    ro = romaji.line_sourced(line, words, owner)
    spans = moras.group_by_word(owner)
    assert ["".join(ro[a:b + 1]) for a, b in spans] == ["Hey ... ", "GO !"]


def test_brackets_do_not_defeat_the_lineup_check():
    # 「 and 」 attach to different sides of a cell depending on which path
    # built it; comparing only what is pronounced keeps the line verbatim.
    assert "".join(cells("「kyou」")) == "「kyou」"


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


def test_never_rewrites_silently_even_on_hostile_input():
    """The invariant, stated as a property rather than as examples.

    Preservation rests on three mechanisms agreeing -- span slicing, mora
    regrouping, gap bookkeeping -- and each has its own way to drop a
    character. So `line_sourced` compares its output against the input before
    returning. This asserts the only thing that matters: it is either exactly
    what the user typed, or it declines. Never something in between.
    """
    import random

    rng = random.Random(7)
    alphabet = (list("abcdefghijkmnoprstuwyz") + list("AEIOU")
                + list("!?,.'-「」()[]~") + [" ", "  ", "	", "　"])
    for _ in range(4000):
        line = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 24)))
        words = readings.resolve_words(line, {}, "romaji")
        units, owner = moras.split_words(words)
        got = romaji.line_sourced(line, words, owner)
        if got is None:
            continue
        assert "".join(got) == line, line
        assert len(got) == len(units), line


def test_plausible_romaji_is_never_declined():
    """Declining is safe but lossy -- the user gets our spelling, not theirs.

    So it must not fire on input that actually is romaji. Measured over the
    7292 romaji lines of the test corpus it never does; this keeps a cheap
    synthetic version of that check in the suite.
    """
    import random

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
        words = readings.resolve_words(line, {}, "romaji")
        _units, owner = moras.split_words(words)
        got = romaji.line_sourced(line, words, owner)
        assert got is not None and "".join(got) == line, line
