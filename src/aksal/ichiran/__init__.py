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
            kana = s.entry.reading or surface
            if s.entry.pos == "prt" and surface in SUNG_PARTICLE:
                kana = SUNG_PARTICLE[surface]
            # HIRAGANA, ALWAYS. JMdict records a katakana word's reading in
            # katakana, and the acoustic model's vocabulary is hiragana -- a
            # katakana kana is simply not in it, so the aligner would receive a
            # character it cannot pronounce and silently lose the mora.
            out.append((surface, jaconv.kata2hira(kana)))
    return out
