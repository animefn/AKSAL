"""Generate the inflected forms of a Japanese word, surface and reading together.

WHY THIS IS THE FIRST PHASE. JMdict holds 夜が明ける but lyrics contain
夜が明けても. A dictionary lookup of the written form therefore misses, and the
whole point of adopting JMdict -- that it knows 夜 is よ inside this idiom --
is lost. ichiran solves this by building a database of every conjugated form;
this is that step.

THE TRICK THAT MAKES IT TRACTABLE. Inflection only ever touches trailing KANA,
and that kana appears identically in the written form and in the reading:

    明ける / あける   ->  strip る from both, append て  ->  明けて / あけて
    書く   / かく     ->  strip く from both, append いて ->  書いて / かいて

So one rule conjugates both strings at once, and an expression ending in a verb
(夜が明ける / よがあける) conjugates exactly like the bare verb does. No
alignment between surface and reading is needed, which is the part that would
otherwise be hard.

WHERE THIS STOPS, BY DESIGN. Auxiliaries after the te-form (〜ていた, 〜てくる,
〜ちゃう) are NOT generated here. ichiran attaches those during the search --
dict-grammar.lisp's suffix machinery, ported in suffixes.py -- because they
compose (いる itself conjugates: 〜ていました) and pre-generating the product
of two conjugations explodes the index while still missing forms. This module
generates exactly what ichiran's conjugation table generates: one inflection
step, including the stem forms the suffix machinery attaches to.

Forms are NAMED because the suffix machinery selects roots by form: たい
attaches to a continuative stem ("stem"), ちゃう to a te-form ("te"), さ to an
adjective stem ("adj-stem"). The names are the contract between this file, the
index, and suffixes.py.
"""
from __future__ import annotations

# Godan euphonic changes (音便) for the て/た forms. This is the one place the
# conjugation is not a plain suffix swap: the final mora of the stem changes
# according to the verb's ending, and getting it wrong produces plausible
# nonsense (書きて rather than 書いて).
GODAN_TE = {
    "く": ("いて", "いた"), "ぐ": ("いで", "いだ"),
    "す": ("して", "した"),
    "つ": ("って", "った"), "る": ("って", "った"), "う": ("って", "った"),
    "ぬ": ("んで", "んだ"), "ぶ": ("んで", "んだ"), "む": ("んで", "んだ"),
}

# The -a-, -i-, -e- and -o- row of each godan ending, for the negative, the
# masu stem, the conditional and the volitional respectively.
GODAN_ROWS = {
    "う": ("わ", "い", "え", "お"), "く": ("か", "き", "け", "こ"),
    "ぐ": ("が", "ぎ", "げ", "ご"), "す": ("さ", "し", "せ", "そ"),
    "つ": ("た", "ち", "て", "と"), "ぬ": ("な", "に", "ね", "の"),
    "ぶ": ("ば", "び", "べ", "ぼ"), "む": ("ま", "み", "め", "も"),
    "る": ("ら", "り", "れ", "ろ"),
}

ICHIDAN = "ichidan"
GODAN = "godan"
GODAN_IKU = "godan-iku"
ADJ_I = "adj-i"
SURU = "suru"
KURU = "kuru"

# Forms ichiran lists in *weak-conj-forms*: real inflections, but not words on
# their own. They exist so the suffix machinery has roots to attach to (行か +
# なきゃ, 高 + さ); standing alone they must not collect the commonness bonus,
# or bare stems start beating real words. scoring.py reads this set.
WEAK_FORMS = frozenset({"neg-stem", "adj-stem"})

# The negative is not one form but a small family, and sung Japanese uses all
# of it: 行かない / 行かなかった / 行かなくて / 行かなければ. ichiran gets these
# from secondary conjugation (ない conjugates as an i-adjective); here the
# family is spelled out once and appended wherever the negative stem goes.
_NEG_TAILS = (("ない", "neg"), ("なかった", "neg-past"),
              ("なくて", "neg-te"), ("なければ", "neg-cond"))


def classify(pos_values: set[str]) -> str | None:
    """Which conjugation class, from JMdict's part-of-speech strings.

    JMdict states these as human-readable text because its DTD entities expand
    on parse, so matching is on that text. Checked against the file: the labels
    are "Ichidan verb", "Godan verb with 'ku' ending", "adjective (keiyoushi)".
    """
    low = " | ".join(p.lower() for p in pos_values)
    if "ichidan verb" in low:
        return ICHIDAN
    # Checked BEFORE plain godan, because JMdict states this class as "Godan
    # verb - Iku/Yuku special class" and the substring "godan verb" matches it.
    if "iku/yuku" in low:
        return GODAN_IKU
    if "godan verb" in low:
        return GODAN
    if "adjective (keiyoushi)" in low and "yoi/ii" not in low:
        return ADJ_I
    if "suru verb" in low or "aux. verb suru" in low:
        return SURU
    if "kuru verb" in low:
        return KURU
    return None


def _pair(surface: str, reading: str, drop: int, add: str):
    """Replace the last `drop` characters of both strings with `add`."""
    if drop and (len(surface) < drop or len(reading) < drop):
        return None
    s = surface[:-drop] if drop else surface
    r = reading[:-drop] if drop else reading
    return s + add, r + add


def forms(surface: str, reading: str, cls: str) -> list[tuple[str, str, str]]:
    """(form surface, form reading, form name), including the base form.

    Returns [] when the word does not inflect or does not end the way its class
    requires -- a mismatch means the entry is not what it claims, and inventing
    forms from it would put wrong readings in the index.
    """
    out: list[tuple[str, str, str]] = [(surface, reading, "base")]
    if not surface or not reading:
        return out

    tail = surface[-1]

    # THE POLITE AND PASSIVE FORMS ARE NOT OPTIONAL. Leaving them out does not
    # merely miss a word -- it fragments the line, because the segmenter then
    # matches only the stem and the remaining kana become separate tokens:
    # 行きます came out 行き | ま | す, and 葬られる came out 葬 | ら | れる.
    # Sung Japanese is full of both, so every such verb was being shattered.
    if cls == ICHIDAN:
        if tail != "る":
            return out
        adds = [("て", "te"), ("た", "past"), ("", "stem"), ("れば", "cond"),
                ("よう", "vol"), ("られる", "pass"), ("させる", "caus"),
                ("ろ", "imp"),
                ("ます", "polite"), ("ました", "polite-past"),
                ("ません", "polite-neg")]
        adds += [(t, name) for t, name in _NEG_TAILS]
        for add, name in adds:
            got = _pair(surface, reading, 1, add)
            if got:
                out.append((*got, name))

    elif cls in (GODAN, GODAN_IKU):
        if cls == GODAN and tail not in GODAN_TE:
            return out
        # 行く は く-godan in every form EXCEPT the て and た ones, where it
        # takes って/った rather than the regular いて/いた. The regular rule
        # generates 行いて, which is not a word, so the real 行って never
        # entered the index at all -- and 行って then resolved to the only
        # other verb that produces it, 行う (おこなって). 行く is one of the
        # commonest verbs in sung Japanese, so this mattered everywhere.
        if cls == GODAN_IKU:
            if tail != "く":
                return out
            te, ta = "って", "った"
        else:
            te, ta = GODAN_TE[tail]
        a_row, i_row, e_row, o_row = GODAN_ROWS[tail]
        adds = [(te, "te"), (ta, "past"),
                (a_row, "neg-stem"), (i_row, "stem"),
                (e_row + "ば", "cond"), (o_row + "う", "vol"),
                (e_row + "る", "pot"),
                (a_row + "れる", "pass"), (a_row + "せる", "caus"),
                (e_row, "imp"),
                (i_row + "ます", "polite"),
                (i_row + "ました", "polite-past"),
                (i_row + "ません", "polite-neg")]
        adds += [(a_row + t, name) for t, name in _NEG_TAILS]
        for add, name in adds:
            got = _pair(surface, reading, 1, add)
            if got:
                out.append((*got, name))

    elif cls == ADJ_I:
        if tail != "い":
            return out
        adds = [("くて", "te"), ("かった", "past"),
                ("く", "adv"), ("", "adj-stem"), ("ければ", "cond"),
                ("くない", "neg"), ("くなかった", "neg-past"),
                ("くなくて", "neg-te"), ("くなければ", "neg-cond")]
        for add, name in adds:
            got = _pair(surface, reading, 1, add)
            if got:
                out.append((*got, name))

    elif cls == SURU:
        # JMdict states these two ways: as the bare noun ("noun which takes the
        # aux. verb suru", 勉強) and as the full verb ("suru verb - included",
        # 恋する). Appending blindly produced 恋するする, so the する is stripped
        # first when it is already there and the stem is what gets suffixed.
        if surface.endswith("する") and reading.endswith("する"):
            surface, reading = surface[:-2], reading[:-2]
        adds = [("する", "base"), ("して", "te"), ("した", "past"),
                ("し", "stem"), ("すれば", "cond"), ("しよう", "vol"),
                ("できる", "pot"),
                ("します", "polite"), ("しました", "polite-past"),
                ("しません", "polite-neg")]
        adds += [("し" + t, name) for t, name in _NEG_TAILS]
        for add, name in adds:
            got = _pair(surface, reading, 0, add)
            if got:
                out.append((*got, name))

    elif cls == KURU:
        # 来る is irregular in the READING while the kanji stays put, so the
        # pair cannot be derived by suffixing and is written out.
        if surface.endswith("来る"):
            head_s, head_r = surface[:-2], reading[:-2]
            for s_tail, r_tail, name in (("来る", "くる", "base"),
                                         ("来て", "きて", "te"),
                                         ("来た", "きた", "past"),
                                         ("来ない", "こない", "neg"),
                                         ("来なかった", "こなかった", "neg-past"),
                                         ("来れば", "くれば", "cond"),
                                         ("来ます", "きます", "polite"),
                                         ("来ました", "きました", "polite-past")):
                out.append((head_s + s_tail, head_r + r_tail, name))

    # SECONDARY CONJUGATION. The potential, passive and causative are ichidan
    # verbs in their own right, and sung Japanese conjugates them further as a
    # matter of course: 戻れない (potential negative), 愛された (passive past),
    # 葬られて (passive te-form, which the suffix machinery then extends to
    # 葬られていた). ichiran's conjugation graph chains these via its `via`
    # column; one explicit level reproduces the part of the graph that occurs
    # in lyrics. The form name keeps its ancestry ("pot-neg") so the suffix
    # machinery can still recognise the tail it attaches to.
    for s, r, name in [f for f in out if f[2] in ("pot", "pass", "caus")]:
        if not s.endswith("る"):
            continue
        for tail, sub in (("て", "te"), ("た", "past"), ("", "stem"),
                          ("ます", "polite"), ("ました", "polite-past"),
                          ("れば", "cond"),
                          ("ない", "neg"), ("なかった", "neg-past"),
                          ("なくて", "neg-te"), ("なければ", "neg-cond")):
            out.append((s[:-1] + tail, r[:-1] + tail, f"{name}-{sub}"))

    return out
