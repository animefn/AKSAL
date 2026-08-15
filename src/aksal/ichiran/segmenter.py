"""Dictionary segmentation: a port of ichiran's best-path search.

Ported from ichiran by Timofei Shatrov (MIT), `find-best-path` in dict.lisp.
Scoring lives in scoring.py and is ichiran's own arithmetic; this file is the
search that uses it. Three ideas do the work:

  GAP PENALTY   characters no dictionary word covers cost score, so a parse
                that explains the whole line with real words beats one that
                leaves debris. A morphological analyser has no such notion --
                it always emits a full parse of short units, which is why
                UniDic splits 夜が明ける and cannot know it is wrong.

  BEAM          the N best paths survive, not one. That is where "there are
                several possible readings" comes from, and the rivals are worth
                more here than in a reading tool: the audio can settle them.

  LENGTH        scoring is multiplicative on a length coefficient, so a long
                match beats its own parts. See scoring.py -- getting this
                wrong is what made an earlier attempt fragment everything.
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path

from . import scoring


@dataclass(frozen=True)
class Entry:
    """One dictionary form, carrying exactly what `calc_score` reads."""
    surface: str
    reading: str
    base: str
    pos: str
    common: int        # ichiran rank: LOWER is commoner, -1 absent
    ord: int           # position of the reading in its entry; 0 is primary
    uk: int            # "usually written in kana alone"
    conj: int          # 1 when this is an inflected form


@dataclass
class Segment:
    start: int
    end: int
    entry: Entry
    score: float

    @property
    def is_gap(self) -> bool:
        return self.entry.pos == "gap"


class Index:
    """Surface -> entries, with the longest key length so lookup can stop."""

    def __init__(self) -> None:
        self.by_surface: dict[str, list[Entry]] = {}
        self.max_len = 1

    @classmethod
    def load(cls, path: Path, max_entries_per_key: int = 8) -> "Index":
        """Read the built index.

        Several entries share a surface -- 夜 is よ and よる and や -- and all
        are kept, because choosing between them is the segmenter's job and the
        audio's, not the loader's. The cap only stops a pathological key with
        dozens of rare readings from crowding out the common ones.
        """
        idx = cls()
        with gzip.open(path, "rt", encoding="utf-8") as f:
            next(f)                                   # header
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) < 8:
                    continue
                idx.by_surface.setdefault(c[0], []).append(
                    Entry(c[0], c[1], c[2], c[3],
                          int(c[4]), int(c[5]), int(c[6]), int(c[7])))
                idx.max_len = max(idx.max_len, len(c[0]))
        for surface, bucket in idx.by_surface.items():
            # Commonest first, then primary reading first. `common` is a RANK,
            # so absent (-1) has to sort last rather than first.
            bucket.sort(key=lambda e: (e.common if e.common >= 0 else 9999,
                                       e.ord))
            del bucket[max_entries_per_key:]
        return idx

    def lookup(self, text: str, start: int) -> list[tuple[int, list[Entry]]]:
        """Every dictionary match beginning at `start`, longest first."""
        out = []
        limit = min(self.max_len, len(text) - start)
        for length in range(limit, 0, -1):
            entries = self.by_surface.get(text[start:start + length])
            if entries:
                out.append((length, entries))
        return out


@dataclass
class Parse:
    segments: list[Segment]
    score: float

    @property
    def reading(self) -> str:
        """Kana for the whole span; an uncovered character stands for itself."""
        return "".join(s.entry.reading or s.entry.surface for s in self.segments)

    @property
    def gaps(self) -> int:
        return sum(1 for s in self.segments if s.is_gap)


class Segmenter:
    """ichiran's best-path search over a JMdict index."""

    def __init__(self, index: Index, beam: int = 5,
                 candidates_per_span: int = 3) -> None:
        self.index = index
        self.beam = beam
        self.candidates_per_span = candidates_per_span

    def segment(self, text: str, limit: int | None = None) -> list[Parse]:
        """The `limit` best segmentations, best first.

        A dynamic program over positions: `best[i]` holds the surviving parses
        of text[:i]. Each is extended by every dictionary match starting at i,
        and by a one-character gap so an unknown word cannot dead-end the
        search. The gap matters more here than in a reading tool: every
        character must end up with a reading, so the search may never fail.
        """
        limit = limit or self.beam
        n = len(text)
        best: list[list[Parse]] = [[] for _ in range(n + 1)]
        best[0] = [Parse([], 0.0)]

        for i in range(n):
            if not best[i]:
                continue
            for length, entries in self.index.lookup(text, i):
                final = (i + length) == n
                # Score every reading of this span, then cull the ones far
                # below the best BEFORE they reach the search. A rare reading
                # that survives here can be carried by its neighbours later.
                scored = [(scoring.calc_score(e, final=final), e)
                          for e in entries]
                for score, entry in scoring.cull_segments(
                        scored)[:self.candidates_per_span]:
                    seg = Segment(i, i + length, entry, score)
                    self._extend(best, i, i + length, seg, limit)
            gap = Segment(i, i + 1,
                          Entry(text[i], "", text[i], "gap", -1, 0, 0, 0),
                          scoring.gap_penalty(i, i + 1))
            self._extend(best, i, i + 1, gap, limit)

        return sorted(best[n], key=lambda p: -p.score)[:limit]

    @staticmethod
    def _extend(best: list[list[Parse]], i: int, j: int,
                seg: Segment, limit: int) -> None:
        for parse in best[i]:
            best[j].append(Parse(parse.segments + [seg], parse.score + seg.score))
        best[j].sort(key=lambda p: -p.score)
        del best[j][limit:]
