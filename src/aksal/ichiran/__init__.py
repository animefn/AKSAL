"""Dictionary-driven segmentation and readings, ported from ichiran.

Ported from ichiran by Timofei Shatrov (MIT), with readings from JMdict
(CC BY-SA 4.0). See THIRD-PARTY.md.

WHY THIS EXISTS ALONGSIDE THE ANALYSER. UniDic is a morphological analyser: it
segments into short units and gives each its citation reading. That is right
for grammar and wrong for idiom. Handed 夜が明けても it produces 夜 (よる) + が
+ 明けて, because nothing in a short-unit analysis can know that 夜 is read よ
inside this phrase -- while JMdict simply has 夜が明ける as an entry.

The difference is a dictionary, and the search over it. This package supplies
both: a JMdict index including generated inflections, and ichiran's best-path
search to choose among the matches.

    units_and_words(text) -> [(surface, kana), ...]

is the entry point, shaped to match `readings.analyse_words` so the rest of the
pipeline neither knows nor cares which engine produced its readings.
"""
from __future__ import annotations

import re
from pathlib import Path

import jaconv

from . import numbers
from .segmenter import Index, Segmenter

__all__ = ["analyse_words", "available", "index_path", "load"]

# The index ships with the package: 8 MB beside a 630 MB acoustic model is not
# worth a download step, and shipping it means the tool works offline and the
# readings are pinned to the release rather than to whenever JMdict was last
# fetched.
INDEX_NAME = "jmdict-index.tsv.gz"

# Foreign words are left whole. JMdict contains single-letter entries, so
# segmenting "listen" returns l|i|s|t|e|n -- six tokens where a singer sings
# one word.
LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'’\-]*")

# A particle is written one way and sung another. ichi.moe romanises these as
# their sound, and so does AKSAL, so the two agree here by design.
SUNG_PARTICLE = {"は": "わ", "へ": "え", "を": "お"}

_SEGMENTER: Segmenter | None = None


def index_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / INDEX_NAME


def available() -> bool:
    return index_path().exists()


def load(beam: int = 5) -> Segmenter:
    """The segmenter, built once and reused.

    Loading parses a million rows and costs several seconds, so it is done on
    first use rather than on import -- a run that never touches Japanese text
    should not pay for it.
    """
    global _SEGMENTER
    if _SEGMENTER is None:
        _SEGMENTER = Segmenter(Index.load(index_path()), beam=beam)
    return _SEGMENTER


# The grammatical particles, listed rather than taken from the dictionary's
# part-of-speech tag. JMdict tags a surprising number of one-character entries
# `prt` -- ま among them -- so trusting the tag let そのまま decompose into
# その + ま + ま, which keeps the kana intact and is nonsense as words.
PARTICLES = set("はがをにでとへもやかねよなのさぞぜ")


def _is_kanji(c: str) -> bool:
    return "一" <= c <= "鿿"


def _subdivide(seg, entry) -> list[tuple[str, str]] | None:
    """Smaller words for a joined unit, but ONLY when the reading is unchanged.

    A dictionary unit is not a karaoke cell. ように and そのまま are single
    JMdict entries, so the dictionary returns them whole where a human timer
    writes "you ni" and "sono mama" -- measured at 19 run-on words against
    UniDic's 5 over the hand-timed corpus.

    The test for whether a unit may be split is whether splitting COSTS
    ANYTHING. Re-segment it without itself, and if the parts' readings join
    back to exactly the same kana, the joined entry was contributing nothing
    but coarseness, so the finer boundaries are free.

    Where the join IS doing work the readings differ and the unit stays whole:
    夜が明けて is よがあけて, while its parts give よるがあけて -- 夜 is よ
    only inside the phrase. That is the entire reason this engine exists, so
    the rule protects it by construction rather than by a list of exceptions.
    """
    if len(entry.surface) < 3 or not entry.reading:
        return None
    # AN INFLECTED FORM IS ONE WORD. 歌われる decomposes into 歌 + われる with
    # the kana intact, and われる is not a word anyone would time separately --
    # preserving the reading says nothing about whether a boundary is real
    # when the tail is an ending rather than a word.
    if entry.conj:
        return None
    # AN EXPRESSION WRITTEN WITH KANJI IS A DELIBERATE JOIN. と共に is
    # totomoni, and splitting it to と + 共に gives the same kana while losing
    # the unit the writer chose. An all-kana pattern like ように is different:
    # it is grammar, and human timers do split it.
    if entry.pos == "exp" and any(_is_kanji(c) for c in entry.surface):
        return None
    parts = seg.subdivide(entry.surface)
    if not parts:
        return None
    got = "".join(p.entry.reading or p.entry.surface for p in parts)
    if got != entry.reading:
        return None

    # A LONE KANA IS ONLY A WORD IF IT IS A PARTICLE. Preserving the reading is
    # necessary but not sufficient: そのまま decomposes into その + ま + ま,
    # which keeps the kana intact and is nonsense as words. Requiring every
    # single-character part to be a particle keeps the の of 心の奥 and the に
    # of ように while rejecting that.
    for p in parts:
        if len(p.entry.surface) == 1 and not _is_kanji(p.entry.surface) \
                and p.entry.surface not in PARTICLES:
            return None
    out = []
    for p in parts:
        kana = p.entry.reading or p.entry.surface
        if p.entry.pos == "prt" and p.entry.surface in SUNG_PARTICLE:
            kana = SUNG_PARTICLE[p.entry.surface]
        out.append((p.entry.surface, jaconv.kata2hira(kana)))
    return out


def analyse_words(text: str) -> list[tuple[str, str]]:
    """(surface, kana) per word, as `readings.analyse_words` returns.

    An explicit space in the source is a hard boundary: lyric sheets use it to
    mark phrasing, and that intent outranks any segmentation this can compute.
    """
    seg = load()
    out: list[tuple[str, str]] = []
    for chunk in numbers.normalise_digits(text).split():
        if not chunk:
            continue
        if LATIN_RUN.fullmatch(chunk):
            out.append((chunk, chunk))
            continue
        parses = seg.segment(chunk, limit=1)
        if not parses:
            out.append((chunk, chunk))
            continue
        for s in parses[0].segments:
            surface = s.entry.surface
            if s.is_gap:
                # Nothing in the dictionary covers this character. It is
                # returned as itself so the caller can decide -- readings.py
                # hands these to UniDic, which always has an answer.
                out.append((surface, ""))
                continue
            parts = _subdivide(seg, s.entry)
            if parts:
                out.extend(parts)
                continue
            kana = s.entry.reading or surface
            if s.entry.pos == "prt" and surface in SUNG_PARTICLE:
                kana = SUNG_PARTICLE[surface]
            # HIRAGANA, ALWAYS. JMdict records a katakana word's reading in
            # katakana, and the acoustic model's vocabulary is hiragana -- a
            # katakana kana is simply not in it, so the aligner would receive a
            # character it cannot pronounce and silently lose the mora.
            out.append((surface, jaconv.kata2hira(kana)))
    return out
