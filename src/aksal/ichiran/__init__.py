"""Dictionary-driven segmentation and readings, ported from ichiran.

Ported from ichiran by Timofei Shatrov (MIT), with readings from JMdict
(CC BY-SA 4.0). See THIRD-PARTY.md.

WHY THIS EXISTS ALONGSIDE THE ANALYSER. UniDic is a morphological analyser: it
segments into short units and gives each its citation reading. That is right
for grammar and wrong for idiom. Handed 夜が明けても it produces 夜 (よる) + が
+ 明けて, because nothing in a short-unit analysis can know that 夜 is read よ
inside this phrase -- while JMdict simply has 夜が明ける as an entry.

The difference is a dictionary, and the search over it. This package supplies
the whole of ichiran's mechanism:

    conjugate.py    every inflected form, generated into the index
    suffixes.py     auxiliaries attached DURING the search (〜ていた, 〜ちゃう,
                    〜なきゃ), each with ichiran's connector and score
    counters.py     numbers and counters computed, not looked up: 10冊 is
                    じゅっさつ by euphonic rule
    scoring.py      calc-score's arithmetic, constants verbatim
    segmenter.py    the best-path search that weighs all of the above

    analyse_words(text)      -> [(surface, kana), ...]
    analyse_candidates(text) -> [(surface, [kana, ...]), ...]
    word_readings(text)      -> [kana, ...]

are the public entry points. `analyse_words` is shaped to match
`readings.analyse_words` so the rest of the pipeline neither knows nor cares
which engine produced its chosen reading. The other two preserve Ichiran's
alternative-reading output: `word_readings` is the port of the Lisp
`word-info-from-text` exact lookup, and `analyse_candidates` applies it to the
words in a sentence.
"""
from __future__ import annotations

import re
from pathlib import Path

import jaconv

from . import numbers
from .segmenter import Index, Segmenter

__all__ = [
    "analyse_candidates",
    "analyse_words",
    "available",
    "index_path",
    "load",
    "rivals",
    "word_readings",
]

# The index ships with the package: 25 MB beside a 630 MB acoustic model is
# not worth a download step, and shipping it means the tool works offline and
# the readings are pinned to the release rather than to whenever JMdict was
# last fetched.
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
    # ONLY ALL-KANA GRAMMATICAL PATTERNS. This started as "split whenever the
    # reading survives", which fires on ordinary words too: どこか rejoins from
    # どこ + か, so a correct parse どこか|ら|か was being shredded into
    # どこ|か|ら|か. Preserving the kana is necessary but nowhere near
    # sufficient -- almost any compound preserves it.
    #
    # So the rule is narrow on purpose. `exp` marks a grammatical pattern
    # rather than a word, and requiring it to be kana-only keeps と共に
    # (totomoni) whole while still letting ように become "you ni".
    if entry.pos != "exp" or any(_is_kanji(c) for c in entry.surface):
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


# NOMINATION IS NOT PARSE SELECTION, and conflating the two is what lost the
# gikun. `cull_segments` keeps readings within HALF the best score, which is
# right when choosing a parse and wrong when choosing what to ask the audio:
# 永遠 scores 156 as えいえん and 65 as とわ, so the reading singers actually
# use was dropped before anything could nominate it. A rival only has to be
# plausible enough to be worth a listen, so the floor here is far lower.
RIVAL_FLOOR = 0.15
MAX_RIVALS = 3

# The bundled index deliberately carries less metadata than Ichiran's
# PostgreSQL database. In particular, its integer commonness band slightly
# overvalues some secondary readings: 度【たんび】 scores 11 against 16 for
# 度【ど／たび】 here, while upstream Ichiran omits it from sentence output.
# Three quarters reproduces upstream's visible choices for that case and also
# removes 方【がた／さま／へ】 (5 against 16). Exhaustive dictionary lookup is
# still available explicitly through `word_readings(..., exhaustive=True)`.
WORD_READING_SCORE_FLOOR = 0.75


def word_readings(surface: str, *, exhaustive: bool = False) -> list[str]:
    """Contextually plausible readings for one exact spelling, best first.

    This is the Python counterpart of Ichiran's Lisp `word-info-from-text`:
    look up the complete surface directly and score every dictionary entry.
    It is deliberately an EXACT lookup rather than a parse. A spelling such
    as 度 is a grammatical suffix and therefore cannot begin a segmented
    sentence, but asking for the readings of that exact spelling must still
    return たび, ど, and the rarer たんび instead of an unexplained gap.

    Sentence-facing output applies a score floor so rare suffix-only readings
    are not presented as equal candidates for a bare word. Pass
    `exhaustive=True` to enumerate every distinct reading in the index instead.
    Callers that need a short nomination list for audio arbitration should use
    `rivals`, whose separate floor and limit are intentional.

    Distinct dictionary entries can share a reading, so kana are de-duplicated
    after scoring.  Generated forms such as number+counter combinations are
    handled by the sentence analyser and have no exact index rows here.
    """
    if not available() or not surface:
        return []

    from . import scoring

    entries = load().index.by_surface.get(surface)
    if not entries:
        return []
    scored = sorted(((scoring.calc_score(entry), entry)
                     for entry in entries), key=lambda pair: -pair[0])
    cutoff = (None if exhaustive
              else scored[0][0] * WORD_READING_SCORE_FLOOR)
    out: list[str] = []
    for score, entry in scored:
        if cutoff is not None and score < cutoff:
            break
        kana = jaconv.kata2hira(entry.reading or entry.surface)
        if kana and kana not in out:
            out.append(kana)
    return out


def analyse_candidates(text: str, *,
                       exhaustive: bool = False) -> list[tuple[str, list[str]]]:
    """Sentence words paired with every plausible exact reading.

    Segmentation and reading enumeration are separate in the original Lisp
    implementation.  `analyse_words` chooses the best path, while
    `word-info-from-text` retains competing readings for each exact spelling.
    Keeping that separation here avoids changing the long-standing
    `(surface, chosen_kana)` contract of `analyse_words`.

    The path's chosen reading is listed first when it exists.  For a known
    suffix at the start of the input, where sentence grammar intentionally
    leaves a gap, exact lookup supplies the candidates instead.
    """
    out: list[tuple[str, list[str]]] = []
    for surface, chosen in analyse_words(text):
        candidates = word_readings(surface, exhaustive=exhaustive)
        if chosen:
            candidates = [chosen] + [kana for kana in candidates
                                     if kana != chosen]
        if not candidates:
            candidates = [chosen]
        out.append((surface, candidates))
    return out


def rivals(surface: str, chosen: str, limit: int = MAX_RIVALS) -> list[str]:
    """Other readings JMdict records for this exact surface, best first.

    The audio decides between them; this only proposes. Returns [] for a
    surface with one reading, which is the overwhelming majority.
    """
    if not available() or not surface:
        return []
    import jaconv as _jaconv

    from . import scoring

    seg = load()
    entries = seg.index.by_surface.get(surface)
    if not entries:
        return []
    scored = sorted(((scoring.calc_score(e), e) for e in entries),
                    key=lambda pair: -pair[0])
    if not scored or scored[0][0] <= 0:
        return []
    floor = scored[0][0] * RIVAL_FLOOR
    out: list[str] = []
    for score, entry in scored:
        if score < floor:
            break
        kana = _jaconv.kata2hira(entry.reading or entry.surface)
        if kana and kana != chosen and kana not in out:
            out.append(kana)
        if len(out) >= limit:
            break
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
            if s.parts:
                # A compound whose connector is a space: one dictionary match,
                # several sung words (学生です is "gakusei desu"). The suffix
                # machinery decided the split; it is passed through as-is.
                out.extend((p_surface, jaconv.kata2hira(p_kana))
                           for p_surface, p_kana in s.parts)
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
