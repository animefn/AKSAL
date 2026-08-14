"""Kana -> mora units.

The unit boundaries defined here are the single source of truth for BOTH the
Japanese and the Romaji karaoke tracks, which is what keeps their `\\k` splits
identical by construction rather than by coincidence.

Rules, chosen so that every unit has a romaji rendering of its own:

  * small ya/yu/yo and small vowels attach BACKWARD  (き + ゃ -> きゃ / kya)
  * the long-vowel mark attaches BACKWARD            (か + ー -> かー / kaa)
  * sokuon attaches FORWARD                          (っ + か -> っか / kka)
  * ん stands alone                                   (ん / n)

Sokuon is the interesting one. Left standing alone it would need a `\\k` cell
with no romaji to put in it, so the two tracks could no longer line up. Attached
forward it becomes the gemination of the syllable it belongs to, which is what
it actually is.
"""
from __future__ import annotations

SMALL_ATTACH = set("ゃゅょぁぃぅぇぉゎ")
PROLONG = set("ーｰ―‐")
SOKUON = set("っッ")


def split_words(words: list[str]) -> tuple[list[str], list[int]]:
    """Split each word into units, keeping track of which word each came from.

    Returns (units, owner) where owner[i] is the index of the word unit i
    belongs to. The two tracks are still built from ONE unit list, so their
    `\\k` splits stay identical -- word membership only changes where spaces and
    group boundaries go, never the timing.
    """
    units: list[str] = []
    owner: list[int] = []
    for i, word in enumerate(words):
        parts = split(word)
        units.extend(parts)
        owner.extend([i] * len(parts))
    return units, owner


def split_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """`split`, carrying each kana's source text along with it.

    Mirrors `split` rule for rule -- it must, or the cells built from the user's
    own spelling would not line up one-to-one with the cells built from kana,
    and the karaoke would be silently misattributed.

    Input is (kana, source) pairs from `romaji.to_kana_spans`; output is
    (unit_kana, unit_source) where a unit's source is the concatenation of every
    kana's source that merged into it. So "kitte" -> き='ki', っ='t', て='te'.
    """
    units: list[list[str]] = []
    latin_run = False

    def merge(src: str) -> None:
        units[-1][1] += src

    for ch, src in pairs:
        if ch.isspace():
            latin_run = False
            if units:
                merge(src)
            continue
        if ch in LATIN:
            if latin_run:
                units[-1][0] += ch
                merge(src)
            else:
                units.append([ch, src])
                latin_run = True
            continue
        latin_run = False
        if (ch in SMALL_ATTACH or ch in PROLONG) and units:
            units[-1][0] += ch
            merge(src)
            continue
        units.append(["っ" if ch in SOKUON else ch, src])
    return [(k, s) for k, s in units]


def group_by_word(owner: list[int]) -> list[tuple[int, int]]:
    """Inclusive (first, last) unit index for each word."""
    spans: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(owner) + 1):
        if i == len(owner) or owner[i] != owner[start]:
            spans.append((start, i - 1))
            start = i
    return spans


LATIN = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'’0123456789")


def split(kana: str) -> list[str]:
    """Split a hiragana string into mora units.

    っ gets a unit of its own. It is a mora -- one of the three special moras
    (特殊拍) with ん and the long-vowel mark -- so it occupies a beat, and
    singers give it one. Its romaji is the doubled consonant of the FOLLOWING
    mora, which is why `romaji.line` resolves it with lookahead rather than
    `romaji.unit` doing it alone.

    A run of latin characters is ONE unit. Splitting it per letter, which is
    what falling through to the per-character path does, turns "everyday" into
    eight karaoke cells. Where the lyric is not Japanese there is no mora
    structure to find, and word level is the honest granularity.
    """
    units: list[str] = []
    latin_run = False

    for ch in kana:
        if ch.isspace():
            latin_run = False
            continue
        if ch in LATIN:
            if latin_run:
                units[-1] += ch
            else:
                units.append(ch)
                latin_run = True
            continue
        latin_run = False
        if ch in SMALL_ATTACH and units:
            units[-1] += ch
            continue
        if ch in PROLONG and units:
            units[-1] += ch
            continue
        units.append("っ" if ch in SOKUON else ch)
    return units
