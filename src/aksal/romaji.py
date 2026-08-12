"""Mora unit -> modified Hepburn, with doubled long vowels.

Deliberately operates on ONE mora unit at a time, so the romaji track inherits
the Japanese track's `\\k` split exactly. Nothing here may merge or split units.

Style: modified Hepburn as used in fansub karaoke --
  * long vowels doubled, not macronised   (よう -> you, きょー -> kyoo)
  * ん is always "n"                       (かんぱい -> kanpai, not kampai)
  * を is "wo", preserving the kana identity singers are reading from
"""
from __future__ import annotations

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


def unit(mora: str) -> str:
    """Romanise a single mora unit produced by moras.split()."""
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
    """Romanise a whole line, unit for unit -- same length in, same length out."""
    return [unit(u) for u in units]


def line_spaced(units: list[str], owner: list[int]) -> list[str]:
    """Romanise with word spacing, still one output per input unit.

    The space is appended to the LAST syllable of each word rather than emitted
    as its own cell. A cell of its own would need a duration, stealing time from
    a syllable and desynchronising the two tracks; carried inside the text it
    costs nothing and the `\\k` values stay identical to the Japanese track.
    """
    out: list[str] = []
    for i, u in enumerate(units):
        text = unit(u)
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
    "ji": "じ", "zu": "ず", "o": "お", "wo": "を", "e": "え", "wa": "わ",
    "n": "ん", "shi": "し", "chi": "ち", "tsu": "つ", "fu": "ふ",
    "ha": "は", "he": "へ", "hi": "ひ",
})

VOWEL_SET = set("aiueo")


def to_kana(text: str) -> str:
    """Parse a romaji line into hiragana.

    Longest-match, with the three constructions that are not a plain table
    lookup: gemination (doubled consonant, plus Hepburn's "tch"), syllabic n,
    and pass-through for anything unrecognised.

    Note the deliberate asymmetry with `unit()`: "kaa" comes back as か+あ, not
    かー. Those are acoustically identical and split into the same two cells, so
    it does not affect timing -- only how the kana would look if displayed.
    """
    s = text.lower().strip()
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if not ch.isalpha() and ch != "'":
            i += 1
            continue

        # Hepburn geminates ch as "tch"; everything else doubles its consonant.
        if s.startswith("tch", i):
            out.append("っ")
            i += 1
            continue
        if ch not in VOWEL_SET and ch != "n" and i + 1 < len(s) and s[i + 1] == ch:
            out.append("っ")
            i += 1
            continue

        # Syllabic n: "n" not followed by a vowel or y, or explicitly n'.
        if ch == "n":
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == "'":
                out.append("ん")
                i += 2
                continue
            if nxt not in VOWEL_SET and nxt != "y":
                out.append("ん")
                i += 1
                continue

        for length in (3, 2, 1):
            frag = s[i:i + length]
            if frag in REVERSE:
                out.append(REVERSE[frag])
                i += length
                break
        else:
            out.append(ch)          # unknown: keep it so it shows up as missing
            i += 1
    return "".join(out)


def looks_like_romaji(text: str, threshold: float = 0.6) -> bool:
    """True if a lyric sheet is predominantly latin script."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) >= threshold
