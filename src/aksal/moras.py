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


def group_by_word(owner: list[int]) -> list[tuple[int, int]]:
    """Inclusive (first, last) unit index for each word."""
    spans: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(owner) + 1):
        if i == len(owner) or owner[i] != owner[start]:
            spans.append((start, i - 1))
            start = i
    return spans


def split(kana: str) -> list[str]:
    """Split a hiragana string into mora units."""
    units: list[str] = []
    pending_sokuon = False

    for ch in kana:
        if ch.isspace():
            continue
        if ch in SMALL_ATTACH and units:
            units[-1] += ch
            continue
        if ch in PROLONG and units:
            units[-1] += ch
            continue
        if ch in SOKUON:
            pending_sokuon = True
            continue
        units.append(("っ" if pending_sokuon else "") + ch)
        pending_sokuon = False

    if pending_sokuon:          # trailing sokuon: rare, but do not lose it
        units.append("っ")
    return units
