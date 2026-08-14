"""Mora unit -> modified Hepburn, with doubled long vowels.

Deliberately operates on ONE mora unit at a time, so the romaji track inherits
the Japanese track's `\\k` split exactly. Nothing here may merge or split units.

Style: modified Hepburn as used in fansub karaoke --
  * long vowels doubled, not macronised   (よう -> you, きょー -> kyoo)
  * ん is always "n"                       (かんぱい -> kanpai, not kampai)
  * を is "wo", preserving the kana identity singers are reading from
"""
from __future__ import annotations

import re

# Digraphs first: lookup tries the two-character form before the single.
TABLE: dict[str, str] = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "しぇ": "she",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "じぇ": "je",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "ちぇ": "che",
    "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du",
    "うぁ": "wa", "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo",

    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "wi", "ゑ": "we", "を": "wo", "ん": "n",
    "ゔ": "vu",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa",
}

PROLONG = "ーｰ―‐"
VOWELS = "aiueo"


def sokuon_romaji(nxt: str | None) -> str:
    """Romaji for a standalone っ: the doubled consonant of what follows.

    っ carries no sound of its own -- it is the closure before the next
    consonant -- so it can only be written by looking ahead. Hepburn geminates
    ch as "tch", so まっちゃ splits ma / t / cha.

    At the end of a line there is nothing to double: that is a glottal stop, and
    the cell is left empty rather than invented. The `\\k` still advances, so the
    two tracks stay aligned.
    """
    if not nxt:
        return ""
    r = unit(nxt)
    if not r:
        return ""
    return "t" if r.startswith("ch") else r[0]


def unit(mora: str) -> str:
    """Romanise a single mora unit produced by moras.split().

    A latin run passes through untouched -- it is already romaji, and there is
    nothing to transliterate.
    """
    if mora and mora[0] in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return mora
    if mora == "っ":
        # Only reachable if a caller romanises units one at a time; `line`
        # resolves it properly with the following mora.
        return ""
    sokuon = mora.startswith("っ")
    body = mora[1:] if sokuon else mora

    held = 0
    while body and body[-1] in PROLONG:
        held += 1
        body = body[:-1]

    r = TABLE.get(body)
    if r is None:
        r = "".join(TABLE.get(c, c) for c in body)
    if not r:
        return ""

    if sokuon:
        # Hepburn geminates ch as "tch", not "cch".
        r = "t" + r if r.startswith("ch") else r[0] + r
    if held and r[-1] in VOWELS:
        r += r[-1] * held
    return r


def line(units: list[str]) -> list[str]:
    """Romanise a whole line, unit for unit -- same length in, same length out.

    Driven over the list rather than mapped, because っ needs the mora after it.
    """
    return [sokuon_romaji(units[i + 1] if i + 1 < len(units) else None)
            if u == "っ" else unit(u)
            for i, u in enumerate(units)]


# --- annotation for the phase 1 lines file ------------------------------------
#
# The tool is for karaoke timers, who often cannot read Japanese. Phase 1's job
# is to hand back lines you correct in Aegisub -- which is impossible if you
# cannot tell which line is which. Prefixing each line with its romaji solves
# that: Aegisub's edit box shows raw text, so the timer reads it, while nothing
# renders on screen because players ignore unknown tag content.
#
# Removable with one regex that cannot damage a real override tag, since every
# genuine ASS tag begins with a backslash.

OPEN, CLOSE = "{*RO*", "*RO*}"
ANNOTATION = re.compile(r"\{\*RO\*.*?\*RO\*\}", re.DOTALL)


def annotate(text: str, romaji_text: str) -> str:
    """Prefix a line with its romaji, escaped so it cannot close early."""
    if not romaji_text:
        return text
    safe = (romaji_text.replace("*RO*", "*R0*")
            .replace("{", "(").replace("}", ")"))
    return f"{OPEN}{safe}{CLOSE}{text}"


def strip(text: str) -> str:
    """Remove annotations. Real override tags are untouched."""
    return ANNOTATION.sub("", text)


def is_annotated(text: str) -> bool:
    return bool(ANNOTATION.search(text))


def line_spaced(units: list[str], owner: list[int]) -> list[str]:
    """Romanise with word spacing, still one output per input unit.

    The space is appended to the LAST syllable of each word rather than emitted
    as its own cell. A cell of its own would need a duration, stealing time from
    a syllable and desynchronising the two tracks; carried inside the text it
    costs nothing and the `\\k` values stay identical to the Japanese track.
    """
    cells = line(units)             # one source of truth for the romaji itself
    out: list[str] = []
    for i, text in enumerate(cells):
        ends_word = i + 1 < len(units) and owner[i + 1] != owner[i]
        out.append(text + " " if ends_word else text)
    return out


# =============================================================================
# Reverse: romaji -> kana, for aligning from a romaji-only lyric sheet.
# =============================================================================

# Invert TABLE, then pin the ambiguous cases. Every pair that collides here is
# a HOMOPHONE pair (じ/ぢ, ず/づ), so picking the common member costs nothing
# acoustically -- the aligner is matching sounds, not orthography.
REVERSE: dict[str, str] = {}
for _k, _r in TABLE.items():
    REVERSE.setdefault(_r, _k)
REVERSE.update({
    # "dzu" is a common fansub spelling of づ that no Hepburn table produces,
    # so it never round-trips: without it, tsudzukete fails to parse as romaji
    # at all and gets mistaken for a foreign word.
    "dzu": "づ", "dji": "ぢ",
    "ji": "じ", "zu": "ず", "o": "お", "wo": "を", "e": "え", "wa": "わ",
    "n": "ん", "shi": "し", "chi": "ち", "tsu": "つ", "fu": "ふ",
    "ha": "は", "he": "へ", "hi": "ひ",
})

VOWEL_SET = set("aiueo")


def to_kana(text: str) -> str:
    """Parse a romaji line into hiragana."""
    return "".join(k for k, _src in to_kana_spans(text))


def to_kana_spans(text: str) -> list[tuple[str, str]]:
    """Parse romaji into (kana, the characters that produced it) pairs.

    The spans are what lets the user's OWN spelling survive the round trip. A
    romaji sheet goes to kana to be aligned, and re-romanising the kana
    afterwards silently rewrites the author's text: "dzu" becomes "zu",
    "PURAIDO" becomes "puraido". Someone who typed the romaji expects to get it
    back.

    Positional, not keyed. A lookup table from kana to romaji cannot express two
    spellings of the same sound in one file, and adding occurrence indexes to it
    only rebuilds position badly -- word three of the input is word three of the
    output, and that is the whole mapping.

    Characters that produce no kana -- punctuation, stray spaces -- are absorbed
    into the following span rather than dropped, so the text reassembles exactly.
    """
    s = text.lower()
    out: list[tuple[str, str]] = []
    i = 0
    start = 0                       # where the pending span began in `text`

    def emit(kana: str, consumed: int) -> None:
        nonlocal i, start
        out.append((kana, text[start:i + consumed]))
        i += consumed
        start = i

    while i < len(s):
        ch = s[i]
        if not ch.isalpha() and ch != "'":
            i += 1                  # keep `start` put: it joins the next span
            continue

        if s.startswith("tch", i):
            emit("っ", 1)
            continue
        if ch not in VOWEL_SET and ch != "n" and i + 1 < len(s) and s[i + 1] == ch:
            emit("っ", 1)
            continue

        if ch == "n":
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == "'":
                emit("ん", 2)
                continue
            if nxt not in VOWEL_SET and nxt != "y":
                emit("ん", 1)
                continue

        for length in (3, 2, 1):
            if s[i:i + length] in REVERSE:
                emit(REVERSE[s[i:i + length]], length)
                break
        else:
            emit(ch, 1)             # unknown: kept so it shows up as missing

    if start < len(text) and out:   # trailing punctuation joins the last span
        kana, src = out[-1]
        out[-1] = (kana, src + text[start:])
    return out


def looks_like_romaji(text: str, threshold: float = 0.6) -> bool:
    """True if a lyric sheet is predominantly latin script."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) >= threshold

def line_sourced(source_line: str, words: list[str],
                 owner: list[int]) -> list[str] | None:
    """Romanise a line as the USER wrote it, not as we would spell it.

    Romaji input is converted to kana to be aligned, and re-romanising the kana
    afterwards quietly rewrites the author's text -- "dzu" comes back "zu",
    "PURAIDO" comes back "puraido", doubled spaces collapse. Someone who typed
    romaji did that work on purpose and expects it back.

    Returns None -- caller falls back to `line_spaced` -- whenever the source
    does not demonstrably line up with the kana it produced: a different word
    count, or a word whose spans do not regroup into the same moras. Better a
    correctly-spelled cell in our romanisation than the user's text attached to
    the wrong syllable.
    """
    from . import moras          # local: moras imports romaji at module level

    # Keep the separators, not just the words: the gap between two words is
    # the user's text too, and re-joining on a single space is one more silent
    # rewrite of what they typed.
    tokens = re.split(r"(\s+)", source_line.strip())
    src_words = tokens[0::2]
    gaps = tokens[1::2] + [""]
    if len(src_words) != len(words):
        return None

    cells: list[str] = []
    for kana_word, src_word in zip(words, src_words):
        want = moras.split(kana_word)
        if len(want) == 1:
            parts = [src_word]              # foreign run, kept whole
        else:
            grouped = moras.split_pairs(to_kana_spans(src_word))
            if [k for k, _s in grouped] != want:
                return None
            parts = [s for _k, s in grouped]
        cells.extend(parts)

    if len(cells) != len(owner):
        return None
    out = list(cells)
    for i in range(len(owner) - 1):
        if owner[i + 1] != owner[i]:
            out[i] += gaps[owner[i]] or " "
    return out

