"""Surface text -> kana reading.

A morphological analyser gets most lines right, but song lyrics are exactly
where analysers fail: ateji, coined readings, furigana that contradicts the
kanji, and digits. So readings live in an editable override table keyed by
SURFACE TEXT, not by line number -- that way a correction survives you
splitting, merging or reordering lines between phases.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import jaconv

DIGITS = re.compile(r"[0-9０-９]")
LATIN = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")
KANJI = re.compile(r"[一-鿿]")
KANA_ONLY = re.compile(r"^[ぁ-ゖー\s]*$")

_TAGGER = None


def tagger():
    global _TAGGER
    if _TAGGER is None:
        import fugashi

        _TAGGER = fugashi.Tagger()
    return _TAGGER


def normalise_surface(line: str) -> str:
    """Full-width spaces are phrase separators in lyric sheets, not characters."""
    return line.replace("　", " ").strip()


def analyse_words(text: str) -> list[tuple[str, str]]:
    """Tokenise a line into (surface, kana) pairs, one per word.

    The word boundaries matter as much as the readings: romaji rendered without
    them is one unbroken run and unreadable. The analyser already produces them,
    so the only thing required is not to throw them away.

    An explicit space in the source is treated as a hard boundary -- lyric
    sheets use it to mark phrasing, and that intent should outrank the
    analyser's own tokenisation.
    """
    out: list[tuple[str, str]] = []
    for chunk in text.split():
        for word in tagger()(chunk):
            feat = word.feature
            kana = (getattr(feat, "kana", None)
                    or getattr(feat, "pron", None)
                    or getattr(feat, "kanaBase", None))
            if kana in (None, "*", ""):
                kana = word.surface

            # Particles are written one way and sung another: は->wa, へ->e,
            # を->o. The analyser's `pron` field knows this, but it cannot be
            # used wholesale -- it also collapses long vowels (今日 becomes
            # キョー rather than キョウ), which would merge two sung beats into
            # one cell. So take `pron` for exactly the particles that need it.
            if str(getattr(feat, "pos1", "")) == "助詞":
                pron = getattr(feat, "pron", None)
                if pron and pron not in ("*", "") and word.surface in "はへを":
                    kana = pron

            out.append((word.surface, jaconv.kata2hira(kana)))
    return out


def analyse(text: str) -> str:
    """Best-effort kana reading for one line, as hiragana."""
    return "".join(kana for _surface, kana in analyse_words(text))


def flags_for(surface: str, reading: str, source: str = "jp") -> str:
    """Flag rows a human should look at. Kept quiet on purpose -- a flag on
    every line is the same as no flags at all."""
    reasons = []
    if DIGITS.search(surface):
        reasons.append("digits")
    # Latin text is an anomaly in a Japanese sheet, but it is the whole point
    # of a romaji one.
    if source != "romaji" and LATIN.search(surface):
        reasons.append("latin")
    if KANJI.search(reading):
        reasons.append("unresolved-kanji")
    if source == "romaji" and "'" not in surface:
        # n + vowel is the one genuinely ambiguous romaji construction: "kani"
        # could be か-に or か-ん-い, and only an apostrophe disambiguates it.
        if re.search(r"n[aiueo]", surface.lower()):
            reasons.append("n-vowel-ambiguous")
    return ",".join(reasons)


def load_overrides(path: Path) -> dict[str, str]:
    """Read the editable TSV into {surface: reading}."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) >= 4 and parts[3].strip():
            out[parts[2].strip()] = unicodedata.normalize(
                "NFKC", parts[3]).strip()
    return out


def resolve(surface: str, overrides: dict[str, str],
            source: str = "jp") -> str:
    """Reading for one line: a manual override if present, else derived.

    With `source="romaji"` there is no morphological analysis to do -- romaji
    already IS the reading, so it is parsed straight back to kana. That skips
    the single largest error source in the Japanese path (the analyser guessing
    a reading the singer does not use).
    """
    return "".join(resolve_words(surface, overrides, source))


def resolve_words(surface: str, overrides: dict[str, str],
                  source: str = "jp") -> list[str]:
    """Kana for one line, split into words.

    Where the boundaries come from, in order:

      * A manual override -- **spaces in the reading column mark word breaks.**
        An override without spaces is one word, which is what earlier tables
        already meant, so existing corrections keep working unchanged.
      * Romaji input -- the spaces are already there and are authoritative. No
        analyser is involved at all, which makes romaji lyrics strictly better
        than Japanese ones for this particular purpose.
      * Otherwise the morphological analyser.
    """
    key = normalise_surface(surface)
    if key in overrides:
        parts = overrides[key].split()
        return parts if parts else [overrides[key]]
    if source == "romaji":
        from . import romaji

        return [romaji.to_kana(w) for w in key.split() if w] or [romaji.to_kana(key)]
    return [kana for _surface, kana in analyse_words(key)]


def write_table(path: Path, rows: list[tuple[int, str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# line\tflag\tsurface\treading\n")
        f.write("# Fix the `reading` column wherever the flag column is set, and\n")
        f.write("# anywhere the analyser guessed a reading the singer does not use.\n")
        f.write("# Readings must be hiragana. Rows are matched by SURFACE text,\n")
        f.write("# so you may reorder or renumber freely.\n")
        for n, flag, surface, reading in rows:
            f.write(f"{n}\t{flag}\t{surface}\t{reading}\n")


def detect_source(lyrics: Path) -> str:
    """'romaji' if the sheet is predominantly latin script, else 'jp'."""
    from . import romaji

    return "romaji" if romaji.looks_like_romaji(
        lyrics.read_text(encoding="utf-8")) else "jp"


def from_lyrics(lyrics: Path, overrides: dict[str, str] | None = None,
                source: str = "jp") -> list[tuple[int, str, str]]:
    """Parse a lyrics file into [(line_no, surface, reading)], skipping blanks."""
    overrides = overrides or {}
    rows: list[tuple[int, str, str]] = []
    for i, raw in enumerate(lyrics.read_text(encoding="utf-8").splitlines(), 1):
        surface = normalise_surface(raw)
        if not surface:
            continue
        rows.append((i, surface, resolve(surface, overrides, source)))
    return rows
