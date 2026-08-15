"""ichiran's `calc-score`, ported as faithfully as the data allows.

Ported from ichiran by Timofei Shatrov (MIT), dict.lisp. Constants are copied
rather than invented, and that distinction is the whole point of this file: an
earlier attempt guessed additive weights and could not express what ichiran
does, so long dictionary matches lost to their own parts no matter how the
numbers were pushed around.

THE SHAPE THAT MATTERS, and the thing guessing missed:

    score = prop_score * (length_coeff(moras, class) + kanji_bonus)

It is MULTIPLICATIVE. `prop_score` is a small sum of bonuses -- primary
reading, commonness, particle handling -- typically between 2 and 25. It is
then multiplied by a coefficient that runs 1, 8, 24, 40, 60 for a kanji word.
A four-mora word is therefore worth forty times a one-mora word before any
bonus applies, which is what makes a long match beat a fragmented parse. No
additive scheme reproduces that.

WHAT IS FAITHFUL AND WHAT IS SUBSTITUTED. The arithmetic, the constants and
the length table are ichiran's. What cannot be copied is where it reads its
inputs: `calc-score` queries JMdictDB for sense properties, conjugation graphs
and an entry's `common` column. Those are replaced by the equivalent fields
built into our own index -- `common` in ichiran's rank convention, `uk` for
prefer-kana, `ord` for the primary reading, `conj` for inflected forms. Where a
test has no equivalent here it is dropped rather than approximated, and each
such case is marked NOT PORTED below.
"""
from __future__ import annotations

# --- ichiran's constants, copied verbatim from dict.lisp ----------------------
GAP_PENALTY = -500                      # *gap-penalty*
SCORE_CUTOFF = 5                        # *score-cutoff*
SEGMENT_SCORE_CUTOFF = 2 / 3            # *segment-score-cutoff*

# *length-coeff-sequences*. Index by mora length; beyond the table, ichiran
# extrapolates linearly using the last value divided by the last index.
LENGTH_COEFFS = {
    "strong": (1, 8, 24, 40, 60),
    "weak": (1, 4, 9, 16, 25, 36),
    "tail": (4, 9, 16, 24),
    "ltail": (4, 12, 18, 24),
}

NOT_COMMON = -1
_SMALL = "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ"


def mora_length(kana: str) -> int:
    """Beats, not characters. Small kana ride on the mora before them."""
    return max(1, sum(1 for c in kana if c not in _SMALL))


def length_multiplier_coeff(length: int, cls: str) -> int:
    """`length-multiplier-coeff`: table lookup, then linear extrapolation."""
    coeffs = LENGTH_COEFFS[cls]
    if 0 < length < len(coeffs):
        return coeffs[length]
    return length * (coeffs[-1] // (len(coeffs) - 1))


def _is_kanji(c: str) -> bool:
    return "一" <= c <= "鿿"


def _is_katakana(c: str) -> bool:
    return "゠" <= c <= "ヿ"


def calc_score(entry, final: bool = False) -> int:
    """Score one dictionary match, following calc-score's structure.

    `entry` needs: surface, reading, pos, common, ord, uk, conj.
    """
    text = entry.surface
    n_kanji = sum(1 for c in text if _is_kanji(c))
    kanji_p = n_kanji > 0
    katakana_p = not kanji_p and any(_is_katakana(c) for c in text)

    # LENGTH IS MEASURED ON THE WRITTEN FORM, not the reading. ichiran computes
    # `(mora-length (text reading))`, and for a kanji word `text` is the kanji
    # spelling -- so 顔 has length 1 whether it is read かお or かんばせ.
    #
    # Measuring the reading instead hands a rare long reading an enormous
    # advantage, because length feeds a coefficient running 1, 8, 24, 40, 60:
    # かんばせ (4 moras, coefficient 40) beat かお (2 moras, coefficient 8) by
    # five times purely for being obscure. For a kana word the two are the same
    # string, so this is only ever a correction, never a change.
    length = mora_length(text)

    common = entry.common
    common_p = common != NOT_COMMON
    prefer_kana = bool(entry.uk)
    conj_only = bool(entry.conj)
    root_p = not conj_only
    pos = entry.pos
    particle_p = pos == "prt"
    pronoun_p = pos == "pn"

    # `long-p`: the threshold below which length stops earning its bonuses.
    if kanji_p and not prefer_kana and root_p:
        threshold = 2
    elif common_p and 0 < common < 10:
        threshold = 2
    else:
        threshold = 3
    long_p = length > threshold

    # NOT PORTED: *skip-words*, *final-prt* and skip-by-conj-data all consult
    # tables of sequence numbers from JMdictDB. Nothing here has sequence
    # numbers, so no word is skipped outright.

    score = 1

    # `primary-p`. ichiran's full test walks the entry's other readings and its
    # sense ordering; the substitute is the reading's own position in the entry
    # plus the kana/kanji preference, which is what those queries decide.
    primary_p = (entry.ord == 0) or (prefer_kana and not kanji_p)

    if primary_p:
        if long_p:
            score += 10
        elif common_p:
            score += 5
        elif prefer_kana or not kanji_p:
            score += 3
        else:
            score += 2

    no_common_bonus = particle_p

    if particle_p:
        score += 2
        if common_p:
            score += 2 + length
        if final:
            score += 5 if primary_p else 2

    if common_p and not no_common_bonus:
        if long_p or (root_p and (kanji_p or (primary_p and length > 2))):
            if common == 0:
                bonus = 10
            elif not primary_p:
                bonus = max(15 - common, 10)
            else:
                bonus = max(20 - common, 10)
        elif kanji_p:
            bonus = 8
        elif primary_p:
            bonus = 4
        elif length > 2 or 0 < common < 10:
            bonus = 3
        else:
            bonus = 2
        score += bonus

    if long_p:
        score = max(length, score)
    if kanji_p:
        score = max(5, score)
        if long_p and (n_kanji > 1 or length > 4):
            score += 2
    if pronoun_p and common_p:
        score += 2

    prop_score = score
    cls = "strong" if (kanji_p or katakana_p) else "weak"
    return prop_score * (length_multiplier_coeff(length, cls)
                         + ((n_kanji - 1) * 5 if n_kanji > 1 else 0))


def gap_penalty(start: int, end: int) -> int:
    """`(* (- end start) *gap-penalty*)` -- linear in uncovered characters."""
    return (end - start) * GAP_PENALTY


IDENTICAL_WORD_SCORE_CUTOFF = 1 / 2     # *identical-word-score-cutoff*


def cull_segments(scored: list[tuple[int, object]]) -> list[tuple[int, object]]:
    """`cull-segments`: for ONE span, drop readings far below the best.

    A span like 顔 offers かお and かんばせ, and 度 offers ど, たび and たんび.
    Carrying every one of them into the search lets a rare reading survive on
    the strength of the surrounding words, which is how かんばせ and ふたたび
    ended up in output. ichiran prunes them here instead: sort by score and
    keep only what is within half of the best.

    The cutoff is ichiran's *identical-word-score-cutoff*, not a chosen number.
    """
    if not scored:
        return scored
    ranked = sorted(scored, key=lambda pair: -pair[0])
    cutoff = ranked[0][0] * IDENTICAL_WORD_SCORE_CUTOFF
    return [pair for pair in ranked if pair[0] >= cutoff]
