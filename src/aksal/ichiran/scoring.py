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
    """`length-multiplier-coeff`: table lookup, then linear extrapolation.

    OFF-BY-ONE WARNING, learned the hard way: ichiran's list is
    (:strong 1 8 24 40 60) and it indexes with (elt coeffs length) -- element
    0 is the KEYWORD, so one mora gets coefficient 1, not 8. An earlier port
    kept lisp's index against a python table without the keyword, which gave
    every word the coefficient of a word one mora longer -- and since the
    ratio between 1 and 2 moras is 8:1, not 3:1, that shifted which parse
    wins on nearly every line.
    """
    coeffs = LENGTH_COEFFS[cls]
    if 0 < length <= len(coeffs):
        return coeffs[length - 1]
    return length * (coeffs[-1] // len(coeffs))


def _is_kanji(c: str) -> bool:
    return "一" <= c <= "鿿"


def _is_katakana(c: str) -> bool:
    return "゠" <= c <= "ヿ"


# ichiran's *weak-conj-forms*: these stems exist as attachment points for the
# suffix machinery, not as words. Standing alone they earn no commonness bonus
# (`conj-types-p` in calc-score); as the root of a compound (`use_length` set)
# they are scored in full.
WEAK_FORMS = frozenset({"neg-stem", "adj-stem"})

# *final-prt*: particles that only mean anything at the end of an utterance.
# Mid-line they score zero -- ichiran returns 0 from calc-score outright --
# which is what stops 学生です from ending in the dialectal particle す.
# ichiran keys these by JMdict sequence number; the surface is the equivalent
# key in an index that has no sequence numbers.
FINAL_PRT = frozenset({"かい", "なの", "け", "っけ", "ぞ", "ぜ", "がな",
                       "わい", "のう", "かいな", "す"})

# *semi-final-prt*: final particles with other uses (さ し な ね わ). They
# keep a base score mid-line but collect the particle bonuses only when final.
SEMI_FINAL_PRT = FINAL_PRT | frozenset({"さ", "し", "な", "ね", "わ"})


def calc_score(entry, final: bool = False,
               use_length: int | None = None, score_mod=0) -> int:
    """Score one dictionary match, following calc-score's structure.

    `entry` needs: surface, reading, pos, common, ord, uk, conj, form.

    `use_length` is ichiran's compound path: the entry is the ROOT of a
    root+suffix compound and `use_length` is the mora length of the whole
    compound. The root is scored at its own written length as usual, then a
    tail coefficient pays for the moras the suffix covers -- so 狂って+いた
    outscores 狂って plus debris, but through the root's own weight rather
    than a flat bonus. `score_mod` is the suffix's own score: an int is
    `score_mod * prop_score * suffix_moras` (apply-score-mod), a callable is
    a constant bonus (ichiran's `(constantly 360)` for ください).
    """
    text = entry.surface
    n_kanji = sum(1 for c in text if _is_kanji(c))
    kanji_p = n_kanji > 0
    katakana_p = not kanji_p and any(_is_katakana(c) for c in text)
    form = getattr(entry, "form", "base")
    ctr_mode = entry.pos == "ctr" and form == "counter"
    weak = form in WEAK_FORMS
    # `conj-types-p`: a weak stem only counts as a real inflection when it is
    # serving as a compound root.
    conj_types_p = (not weak) or bool(use_length)

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
    # A CONJUGATED FORM'S RANK IS EXACTLY ZERO. ichiran stores no rank on the
    # form and restores literal 0 from the original -- so every branch keyed
    # on the rank's VALUE (the `0 < common < 10` threshold, the bonus ladder)
    # sees 0, not the base word's band. 行って from 行う (nf01, rank 1) was
    # sneaking a long-word bonus that 行って from 行く (rank 0) could not get,
    # and おこなって beat いって for it.
    if conj_only and common_p:
        common = 0
    root_p = ctr_mode or not conj_only
    pos = entry.pos
    particle_p = pos == "prt"
    pronoun_p = pos == "pn"
    # *copulae*: だ and です get the long-word commonness branch regardless of
    # their length, because nothing about a copula is expressed by mora count.
    cop_da_p = pos == "cop"

    if particle_p and not final and entry.surface in FINAL_PRT:
        return 0

    # `long-p`: the threshold below which length stops earning its bonuses.
    # The conj-type branches are ichiran's: a kanji stem acting as a compound
    # root earns length like a dictionary word (行き in 行きすぎる), while a
    # standalone te-form or volitional needs to be genuinely long before its
    # length means anything.
    if kanji_p and not prefer_kana and (root_p or
                                        (use_length and form == "stem")):
        threshold = 2
    elif common_p and 0 < common < 10:
        threshold = 2
    elif form in ("te", "vol") and not use_length:
        threshold = 4
    else:
        threshold = 3
    long_p = length > threshold

    # NOT PORTED: *skip-words*, *final-prt* and skip-by-conj-data all consult
    # tables of sequence numbers from JMdictDB. Nothing here has sequence
    # numbers, so no word is skipped outright.

    score = 1

    # `primary-p`, following ichiran's three-way test. The decisive clause for
    # lyrics: a KANA reading of a word that HAS a kanji spelling is not primary
    # unless the word is usually written in kana -- いたかった belongs to 痛い,
    # so meeting it bare means this is probably not that word at all. `base`
    # carries the entry's canonical spelling precisely for this test.
    entry_has_kanji = kanji_p or any(_is_kanji(c) for c in entry.base)
    primary_p = (
        (prefer_kana and conj_types_p and not kanji_p)
        or ((entry.ord == 0 or cop_da_p)
            and (kanji_p or conj_types_p)
            and ((kanji_p and not prefer_kana)
                 or (common_p and pronoun_p)
                 or not entry_has_kanji))
        or (prefer_kana and kanji_p and entry.ord == 0))

    if primary_p:
        if long_p:
            score += 10
        elif common_p:
            score += 5
        elif prefer_kana or not kanji_p:
            score += 3
        else:
            score += 2

    no_common_bonus = particle_p or not conj_types_p

    # ichiran's particle block verbatim: a semi-final particle mid-line gets
    # NO particle bonus (よ, ね, な are sentence-enders being used as filler),
    # and the final-position bonus is its own term.
    semi_final = entry.surface in SEMI_FINAL_PRT
    if particle_p and (final or not semi_final):
        score += 2
        if common_p:
            score += 2 + length
        if final:
            if primary_p:
                score += 5
            elif semi_final:
                score += 2

    if common_p and not no_common_bonus:
        if long_p or cop_da_p or (root_p and (kanji_p or
                                              (primary_p and length > 2))):
            # A CONJUGATED FORM'S COMMONNESS IS BORROWED, and ichiran caps a
            # borrowed bonus at the common=0 level: its database stores no
            # rank on the form itself and restores `common 0` from the
            # original. This index copies the base's rank onto the form, so
            # without the cap いたかった collected 痛い's full 19 points and
            # beat real words.
            if common == 0 or conj_only:
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
    if ctr_mode:
        score = max(5, score)
    if pronoun_p and common_p:
        score += 2

    prop_score = score
    cls = "strong" if (kanji_p or katakana_p) else "weak"
    score = prop_score * (length_multiplier_coeff(length, cls)
                          + ((n_kanji - 1) * 5 if n_kanji > 1 else 0))

    # The compound path: pay for the suffix's moras with a tail coefficient
    # scaled by the root's own prop score, plus the suffix's score-mod.
    if use_length and use_length > length:
        tail_cls = "ltail" if (length > 3 and (kanji_p or katakana_p)) \
            else "tail"
        score += prop_score * length_multiplier_coeff(use_length - length,
                                                      tail_cls)
        if callable(score_mod):
            score += score_mod(prop_score)
        else:
            score += score_mod * prop_score * (use_length - length)
    return score


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
