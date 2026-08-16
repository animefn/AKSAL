"""Dictionary segmentation: a port of ichiran's best-path search.

Ported from ichiran by Timofei Shatrov (MIT), `find-best-path` in dict.lisp.
Scoring lives in scoring.py and is ichiran's own arithmetic; this file is the
search that uses it. Four ideas do the work:

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

  COMPOUNDS     a span can also be root+suffix (狂って+いた, suffixes.py) or
                number+counter (２３+冊, counters.py). Neither is an index row,
                because both are productive: the suffixes conjugate and the
                numbers are unbounded. They enter the same search as segments
                and win or lose on the same scores.
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass, field
from pathlib import Path

from . import counters, scoring, suffixes


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
    form: str = "base"  # which inflection: te/stem/past/... (suffix roots)


@dataclass
class Segment:
    start: int
    end: int
    entry: Entry
    score: float
    # A compound with a space connector is one match but two sung words
    # (学生です -> gakusei desu). None means the entry itself is the one word.
    parts: list[tuple[str, str]] | None = field(default=None)

    @property
    def is_gap(self) -> bool:
        return self.entry.pos == "gap"


NUMERALS = set("〇一二三四五六七八九十百千万億兆")


class Index:
    """Surface -> entries, with the longest key length so lookup can stop."""

    def __init__(self) -> None:
        self.by_surface: dict[str, list[Entry]] = {}
        self.max_len = 1

    @classmethod
    def load(cls, path: Path,
             max_entries_per_key: int | None = None) -> "Index":
        """Read the built index.

        Several entries share a surface -- 夜 is よ and よる and や -- and all
        are kept, because choosing between them is the segmenter's job and the
        audio's, not the loader's. Callers may request a cap for constrained
        environments, but the default retains the complete index so exact-word
        lookup can enumerate rare readings too. The segmenter performs its own
        score culling before candidates enter the search.
        """
        idx = cls()
        with gzip.open(path, "rt", encoding="utf-8") as f:
            next(f)                                   # header
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) < 9:
                    continue
                idx.by_surface.setdefault(c[0], []).append(
                    Entry(c[0], c[1], c[2], c[3],
                          int(c[4]), int(c[5]), int(c[6]), int(c[7]), c[8]))
                idx.max_len = max(idx.max_len, len(c[0]))
        for surface, bucket in idx.by_surface.items():
            # Commonest first, then primary reading first. `common` is a RANK,
            # so absent (-1) has to sort last rather than first.
            bucket.sort(key=lambda e: (e.common if e.common >= 0 else 9999,
                                       e.ord))
            if max_entries_per_key is not None:
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

    def _span_segments(self, text: str, i: int,
                       exclude_whole: bool = False) -> list[Segment]:
        """Every candidate segment starting at `i`: dictionary matches,
        root+suffix compounds, and number(+counter) readings."""
        n = len(text)
        out: list[Segment] = []

        for length, entries in self.index.lookup(text, i):
            if exclude_whole and i == 0 and length == n:
                continue
            final = (i + length) == n
            # Score every reading of this span, then cull the ones far below
            # the best BEFORE they reach the search. A rare reading that
            # survives here can be carried by its neighbours later.
            scored = [(scoring.calc_score(e, final=final), e)
                      for e in entries]
            for score, entry in scoring.cull_segments(
                    scored)[:self.candidates_per_span]:
                out.append(Segment(i, i + length, entry, score))

        # Root+suffix compounds. The root always starts at i; every span end
        # that yields a known suffix is a candidate, scored through the root
        # with ichiran's use-length tail.
        limit = min(n, i + self.index.max_len + 8)
        for j in range(i + 2, limit + 1):
            span = text[i:j]
            if exclude_whole and i == 0 and j == n:
                continue
            for root, rule, (surface, reading, parts, use_len) in \
                    suffixes.candidates(self.index, span):
                score = scoring.calc_score(root, final=(j == n),
                                           use_length=use_len,
                                           score_mod=rule.score)
                entry = Entry(surface, reading.replace(" ", ""), root.base,
                              root.pos, root.common, root.ord, root.uk, 1,
                              "compound")
                out.append(Segment(i, j, entry, score,
                                   parts=parts if len(parts) > 1 else None))

        # Numbers and counters: 二十三 as a number, 二十三冊 with its counter.
        if text[i] in NUMERALS:
            r = i
            while r < n and text[r] in NUMERALS:
                r += 1
            value = counters.parse_kanji_number(text[i:r])
            if value is not None:
                out.extend(self._counter_segments(text, i, r, value, n))
        return out

    def _counter_segments(self, text: str, i: int, r: int,
                          value: int, n: int) -> list[Segment]:
        out = []
        number = text[i:r]
        if r > i + 1 or number in ("〇",):
            # A bare multi-char number is its own word; single numerals are
            # already ordinary dictionary entries.
            kana = counters.number_to_kana(value)
            entry = Entry(number, kana, number, "num", 0, 0, 0, 0, "counter")
            out.append(Segment(i, r, entry,
                               scoring.calc_score(entry, final=(r == n))))
        for cl in (1, 2):
            if r + cl > n:
                break
            surface = text[r:r + cl]
            ctr = next((e for e in self.index.by_surface.get(surface, ())
                        if e.pos == "ctr"), None)
            special = surface in counters.SPECIAL_SURFACES
            if ctr is None and not special:
                continue
            kana = counters.read_counter(value, surface,
                                         ctr.reading if ctr else None)
            if kana is None:
                continue
            common = ctr.common if ctr else 0
            entry = Entry(number + surface, kana, number + surface, "ctr",
                          common, 0, 0, 0, "counter")
            out.append(Segment(i, r + cl, entry,
                               scoring.calc_score(entry,
                                                  final=(r + cl == n))))
        return out

    def segment(self, text: str, limit: int | None = None) -> list[Parse]:
        """The `limit` best segmentations, best first.

        A dynamic program over positions: `best[i]` holds the surviving parses
        of text[:i]. Each is extended by every candidate starting at i, and by
        a one-character gap so an unknown word cannot dead-end the search. The
        gap matters more here than in a reading tool: every character must end
        up with a reading, so the search may never fail.
        """
        return self._run(text, limit or self.beam, exclude_whole=False)

    def subdivide(self, text: str) -> list[Segment] | None:
        """Re-segment `text` without the entry that spans all of it.

        Used to ask whether a joined unit could be written as smaller words.
        The whole-span match is excluded, or the answer would trivially be
        itself.
        """
        parses = self._run(text, limit=5, exclude_whole=True)
        if not parses:
            return None
        top = parses[0]
        return top.segments if len(top.segments) > 1 else None

    def _run(self, text: str, limit: int,
             exclude_whole: bool) -> list[Parse]:
        n = len(text)
        # *force-kanji-break*: ichiran's own errata forces a break inside
        # です, halving anything that treats its halves as words -- で + す
        # is otherwise a common particle plus a (final) particle, and no
        # scoring separates that from the copula.
        breaks = {p + 1 for p in _find_all(text, "です")}
        best: list[list[Parse]] = [[] for _ in range(n + 1)]
        best[0] = [Parse([], 0.0)]
        for i in range(n):
            if not best[i]:
                continue
            for seg in self._span_segments(text, i, exclude_whole):
                if seg.score > 0 and (seg.start in breaks or
                                      seg.end in breaks):
                    seg.score /= 2
                self._extend(best, i, seg.end, seg, limit)
            gap = Segment(i, i + 1,
                          Entry(text[i], "", text[i], "gap", -1, 0, 0, 0),
                          scoring.gap_penalty(i, i + 1))
            self._extend(best, i, i + 1, gap, limit)
        return sorted(best[n], key=lambda p: -p.score)[:limit]

    @staticmethod
    def _extend(best: list[list[Parse]], i: int, j: int,
                seg: Segment, limit: int) -> None:
        for parse in best[i]:
            if not _may_follow(parse, seg):
                continue
            score = parse.score + seg.score
            if parse.segments:
                score += _pair_score(parse.segments[-1], seg)
            best[j].append(Parse(parse.segments + [seg], score))
        best[j].sort(key=lambda p: -p.score)
        del best[j][limit:]


def _find_all(text: str, needle: str) -> list[int]:
    out, p = [], text.find(needle)
    while p != -1:
        out.append(p)
        p = text.find(needle, p + 1)
    return out


# --- synergies and penalties (dict-grammar.lisp) -------------------------------
# Bonuses for two adjacent segments that belong together, and one penalty.
# ichiran filters by JMdict sequence sets; the surface+pos pair is the
# equivalent selector here. Scores are ichiran's.

_NOUN_PARTICLES = frozenset({
    "は", "が", "に", "で", "へ", "だけ", "ごろ", "まで", "も", "など",
    "には", "の", "のみ", "を", "さえ", "でさえ", "すら", "と", "とか",
    "として", "とは", "や", "にとって"})
_NOUNISH = frozenset({"n", "pn", "num", "ctr", "name"})


def _pair_score(left: Segment, right: Segment) -> float:
    le, re_ = left.entry, right.entry
    bonus = 0.0
    if le.pos in _NOUNISH:
        # synergy-noun-particle: +10 + 4 per particle character.
        if re_.pos == "prt" and re_.surface in _NOUN_PARTICLES:
            bonus += 10 + 4 * (right.end - right.start)
        # synergy-noun-da: the plain copula after a noun.
        elif re_.surface == "だ" and re_.pos in ("cop", "v"):
            bonus += 10
    # synergy-no-da: のだ / んだ / のです and friends.
    if le.surface in ("の", "ん") and le.pos == "prt" \
            and re_.surface in ("だ", "です", "だろう", "でしょう"):
        bonus += 15
    # penalty-short: two adjacent one-character kana words is nearly always a
    # parse falling apart (で+す); と is excused as the quoting particle.
    if (left.end - left.start) == 1 and (right.end - right.start) == 1 \
            and not left.is_gap and not right.is_gap \
            and re_.surface != "と" \
            and not _has_kanji(le.surface) and not _has_kanji(re_.surface):
        bonus -= 9
    return bonus


def _has_kanji(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in s)


# A SUFFIX IS NOT A WORD. 月 is がつ as a suffix (一月, 三月) and つき as a
# noun, and both scored exactly 200 -- so the tie was broken by whichever came
# first in the index, and 月が消えても read "gatsu ga kiete mo".
#
# ichiran never faces this: its suffixes are reachable only through the suffix
# machinery, never as standalone candidates. The same restriction is expressed
# here as a constraint on what a segment may follow -- a suffix needs something
# to attach to, and a particle or a gap is not it.
_ATTACHABLE = ("n", "v", "adj", "num", "pn", "name", "ctr", "suf")


def _may_follow(parse: "Parse", seg: Segment) -> bool:
    if seg.entry.pos != "suf":
        return True
    if not parse.segments:
        return False                       # nothing to attach to
    return parse.segments[-1].entry.pos in _ATTACHABLE
