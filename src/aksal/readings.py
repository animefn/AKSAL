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
from functools import lru_cache
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


# Furigana as lyric sheets print it: kanji, then a parenthesised all-kana gloss.
# Deliberately narrow -- it fires only when the parenthetical is entirely kana
# AND directly follows kanji, so ordinary asides ("(2回)", "(yeah)") survive.
RUBY = re.compile(r"[一-鿿々]+[（(]([ぁ-ゖァ-ヺー]+)[）)]")


def strip_ruby(line: str) -> str:
    """Replace furigana with the gloss, because the gloss is what is sung.

    Sheets use this for coined readings the kanji do not carry -- a word
    written 冒険 but sung as a loanword, say. Kept as literal text it is not a
    note the singer sings: the aligner is handed the kanji reading AND the
    gloss, and the karaoke comes out with every such word doubled.

    The gloss wins because that is the sound. The kanji is orthography.
    """
    return RUBY.sub(lambda m: m.group(1), line)


# Ideographic variation selectors pick a GLYPH, never a sound, and the old-new
# kanji mapping emits them for characters that have registered variants: 辿
# comes back as 辿 + U+E0100. Left in place the selector becomes a token of its
# own AND strips the kanji of its reading, so a correctly-read word is
# destroyed -- silently, which is precisely the failure this normalisation
# exists to prevent.
_VARIATION_SELECTOR = re.compile(r"[︀-️󠄀-󠇯]")

_YOSINA = None
_YOSINA_TRIED = False


def _character_normaliser():
    """Old kanji forms and stray character variants, or None if yosina is absent.

    These fail SILENTLY, which is why they are worth a dependency. A lyric
    sheet written with old forms gives 戀 the reading レン instead of コイ, and
    孃 no reading at all -- so the aligner is handed a character it cannot
    pronounce and simply hunts for sounds nobody sang. Nothing in the output
    looks wrong.

    Only the transformations that change what is SUNG are enabled. Width and
    spacing conversions are left to jaconv, and nothing here rewrites kana into
    other kana: the analyser's readings must stay the singer's readings.
    """
    global _YOSINA, _YOSINA_TRIED
    if not _YOSINA_TRIED:
        _YOSINA_TRIED = True
        try:
            import yosina

            _YOSINA = yosina.make_transliterator(
                yosina.TransliterationRecipe(
                    kanji_old_new=True,
                    replace_combined_characters=True,
                    replace_ideographic_annotations=True,
                    replace_suspicious_hyphens_to_prolonged_sound_marks=True,
                ))
        except Exception:                   # pragma: no cover - optional
            _YOSINA = None
    return _YOSINA


def normalise_surface(line: str) -> str:
    """Canonicalise a lyric line before it is analysed.

    Order matters. Width and combining marks are folded first, so that a
    half-width or decomposed character is a real character by the time anything
    else looks at it -- か + U+3099 is otherwise split into two units and
    aligned as two sounds. Old kanji forms are resolved next, then ruby, then
    the full-width spaces lyric sheets use as phrase separators.

    This is the ANALYSED text only. Romaji input is displayed from the raw line
    it was read from, so none of this can alter what the user typed.
    """
    line = jaconv.normalize(line)
    tr = _character_normaliser()
    if tr is not None:
        line = _VARIATION_SELECTOR.sub("", tr(line))
    return strip_ruby(line.replace("　", " ")).strip()


def analyse_words(text: str) -> list[tuple[str, str]]:
    """Tokenise a line into (surface, kana) pairs, one per word.

    The word boundaries matter as much as the readings: romaji rendered without
    them is one unbroken run and unreadable. The analyser already produces them,
    so the only thing required is not to throw them away.

    An explicit space in the source is treated as a hard boundary -- lyric
    sheets use it to mark phrasing, and that intent should outrank the
    analyser's own tokenisation.
    """
    out: list[tuple[str, str, str]] = []      # (surface, kana, pos1)
    prev_pos1 = prev_pos2 = ""
    for chunk in text.split():
        first_in_chunk = True
        chunk_start = len(out)
        for word in tagger()(chunk):
            feat = word.feature
            pos1 = str(getattr(feat, "pos1", "") or "")
            pos2 = str(getattr(feat, "pos2", "") or "")
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
            if pos1 == "助詞":
                pron = getattr(feat, "pron", None)
                if pron and pron not in ("*", "") and word.surface in "はへを":
                    kana = pron

            kana = jaconv.kata2hira(kana)
            if out and not first_in_chunk and _attaches(prev_pos1, pos1, pos2,
                                                       word.surface, prev_pos2):
                surface, prev_kana, prev_tag = out[-1]
                out[-1] = (surface + word.surface, prev_kana + kana, prev_tag)
                # The merged word keeps its HEAD's part of speech. Without this
                # 行くんだ stalled: ん merges onto the verb, prev_pos1 became
                # 助詞, and だ then had nothing verbal to attach to. Widening the
                # auxiliary rule to compensate broke 的 + な into "tekina".
                pos1 = prev_tag
            else:
                out.append((word.surface, kana, pos1))
            prev_pos1, prev_pos2 = pos1, pos2
            first_in_chunk = False

        # Compounds are repaired per chunk, so an explicit space in the source
        # still stops a merge from crossing it.
        repaired = repair_compounds(out[chunk_start:])
        out[chunk_start:] = repaired

    return [(surface, kana) for surface, kana, _pos in out]


_IPADIC = None
_IPADIC_TRIED = False


def compound_tagger():
    """A second opinion for compound nouns, or None if ipadic is absent.

    unidic-lite and ipadic disagree usefully. unidic has the better grammar --
    its POS tags are what drive particle and inflection handling -- but its
    lexicon splits set-phrase compounds that ipadic knows as single entries:

        門前払い   unidic-lite: 門 + 前払い (モン + マエバライ)
                  ipadic:      門前払い    (モンゼンバライ)

    That is not merely a spacing difference: the READING is wrong, so the
    aligner would hunt for sounds that were never sung. Lyrics are full of such
    compounds, so it is worth asking.
    """
    global _IPADIC, _IPADIC_TRIED
    if not _IPADIC_TRIED:
        _IPADIC_TRIED = True
        try:
            import fugashi
            import ipadic

            _IPADIC = fugashi.GenericTagger(ipadic.MECAB_ARGS)
        except Exception:               # pragma: no cover - optional extra
            _IPADIC = None
    return _IPADIC


def compound_reading(surface: str) -> str | None:
    """Kana reading if ipadic sees `surface` as exactly ONE word, else None."""
    tagger_ = compound_tagger()
    if tagger_ is None or not surface:
        return None
    try:
        toks = list(tagger_(surface))
    except Exception:                   # pragma: no cover
        return None
    if len(toks) != 1:
        return None
    feat = list(toks[0].feature)
    if len(feat) < 8:
        return None
    reading = feat[7]
    if not reading or reading == "*":
        return None
    return jaconv.kata2hira(reading)


def repair_compounds(words: list[tuple[str, str, str]]
                     ) -> list[tuple[str, str, str]]:
    """Rejoin consecutive nouns that ipadic recognises as one compound.

    Greedy longest-match within each run of nouns, so 門 + 前払い becomes one
    word carrying ipadic's reading. Only runs of nouns are considered: merging
    across a verb or particle would be wrong regardless of what any dictionary
    says.
    """
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(words):
        if words[i][2] != "名詞":
            out.append(words[i])
            i += 1
            continue

        run_end = i
        while run_end + 1 < len(words) and words[run_end + 1][2] == "名詞":
            run_end += 1

        while i <= run_end:
            merged = None
            for j in range(run_end, i, -1):          # longest first
                surface = "".join(w[0] for w in words[i:j + 1])
                reading = compound_reading(surface)
                if reading is not None:
                    merged = (surface, reading, "名詞")
                    i = j + 1
                    break
            if merged is not None:
                out.append(merged)
            else:
                out.append(words[i])
                i += 1
    return out


# 接続助詞 covers two different things under one tag, and the analyser cannot
# tell them apart for us:
#
#   inflectional   て で ば たり  -- part of the verb form.  切り捨て + て
#                                    is one word, "kirisutete".
#   clause joiners けど から ので のに し が ながら -- separate words.
#                                    葬られる + けど is "... kedo", two words.
#
# So the attaching set is listed explicitly and everything else stays separate.
# The default direction matters: a missed inflection costs one visible space,
# while a merged clause joiner produces a run-on word that a timer has to fix.
INFLECTIONAL_CONJUNCTIVE = {"て", "で", "ば", "たり", "だり", "ちゃ", "じゃ"}


def _attaches(prev_pos1: str, pos1: str, pos2: str, surface: str = "",
              prev_pos2: str = "") -> bool:
    """Should this token join the previous one into a single word?

    The analyser tokenises grammar, not orthography: 切り捨てて comes back as
    切り捨て + て, and romanising each as its own word gives "kirisute te".
    Inflections and attached auxiliaries belong to the word they inflect.

    The distinction that matters is what the auxiliary follows. ます on a verb
    is part of it (行きます -> ikimasu); です on a noun is not (学生です ->
    gakusei desu). Case and topic particles never attach, which is what keeps
    は as its own "wa".
    """
    if prev_pos1 == "接頭辞":
        # A prefix owns the word after it: お酒 is "osake", not "o sake". There
        # was no rule for this at all, and no song in the corpus happened to
        # contain one -- a gap found by comparing against cutlet's rules rather
        # than by testing more songs.
        return True
    if pos1 == "接尾辞":
        # Suffixes split two ways and the POS tag does not separate them, so
        # this is decided on the finer tag plus evidence from the hand-timed
        # corpus:
        #   形状詞的  的 / だらけ      -- a timer breaks the highlight here
        #   名詞的    さ / たち / 人 / さん -- part of the word (yasashisa,
        #                                    kodomotachi, sannin)
        # まみれ is 名詞的 and the corpus separates it, so it is a known miss;
        # the readings table is the override.
        return pos2 != "形状詞的"
    # NOT a rule: pronoun + か/も. Tried and reverted. The hand-timed corpus
    # joins 誰か, 何か and いつも but separates 君も, どれも and どこか -- the
    # same part-of-speech pattern with opposite conventions, because いつも is a
    # lexicalised adverb while どこか is built compositionally. That is a lexical
    # fact, not a grammatical one, and a POS rule cost five new run-ons trying
    # to express it. The readings table is where such words belong.
    if pos2 == "接続助詞":
        return surface in INFLECTIONAL_CONJUNCTIVE
    if pos1 == "助動詞":                     # た, ます, ない, だ
        # 接尾辞 included for 〜めいた, where the auxiliary lands on a
        # suffix rather than on the stem; 準体助詞 for 行くんだ.
        # 走るんだ is written "hashiru nda": the nominaliser ん starts a word of
        # its own and the copula joins IT, not the verb. Checked on the previous
        # token's fine tag, because 助詞 as a whole must never take a copula --
        # that would fuse は and を onto whatever follows.
        if prev_pos2 == "準体助詞":
            return True
        return prev_pos1 in ("動詞", "形容詞", "助動詞")
    return False


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


def romaji_to_kana(word: str) -> str:
    from . import romaji

    return romaji.to_kana(word)


@lru_cache(maxsize=4096)
def is_foreign(word: str) -> bool:
    """True if a word in a romaji sheet is not Japanese at all.

    In a romaji sheet every word is latin script, so script tells you nothing --
    "kagayaki" and "dreamer" look alike. Two tests, because each catches what
    the other cannot:

      * it does not parse as romaji at all ("light", "stop" -- `l`, `st`)
      * it parses, but the analyser does not recognise the result ("narrative"
        is phonotactically perfect Japanese and still an English word)

    The analyser is asked about the whole word, inflection included, so
    conjugated forms like "hirogetara" stay Japanese -- a plain dictionary
    lookup of headwords calls 43% of real lyric words foreign.

    A Japanese word missing from unidic -- a coinage, a dialect form -- comes
    out as one un-split cell. That is visible in the phase 1 romaji hint and
    fixable in one row of the readings table, which is what the table is for.
    """
    kana = romaji_to_kana(word)
    if LATIN.search(kana):
        return True
    try:
        return any(t.is_unk for t in tagger()(kana))
    except Exception:
        # The analyser is optional to this decision, never fatal to the run.
        return False


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
        from . import romaji as _romaji

        # Derived from the SAME walk that builds the romaji cells, so the two
        # can never disagree. They used to be computed independently, and where
        # they differed the user's spelling was silently discarded.
        units, owner, _cells = _romaji.sourced_line(key, is_foreign)
        if not units:
            return [key]
        words: list[str] = []
        for unit, w in zip(units, owner):
            if w >= len(words):
                words.append(unit)
            else:
                words[-1] += unit
        return words
    return [kana for _surface, kana in analyse_words(key)]


def write_table(path: Path, rows: list[tuple[int, str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# line\tflag\tsurface\treading\n")
        f.write("# Fix the `reading` column wherever the flag column is set, and\n")
        f.write("# anywhere the analyser guessed a reading the singer does not use.\n")
        f.write("# Readings must be hiragana. Rows are matched by SURFACE text,\n")
        f.write("# so you may reorder or renumber freely.\n")
        f.write("# SPACES IN THE READING MARK WORD BREAKS. They set where the\n")
        f.write("# romaji karaoke puts its spaces; move one to re-split a word.\n")
        for n, flag, surface, reading in rows:
            f.write(f"{n}\t{flag}\t{surface}\t{reading}\n")


def detect_source(lyrics: Path) -> str:
    """'romaji' if the sheet is predominantly latin script, else 'jp'."""
    from . import romaji

    return "romaji" if romaji.looks_like_romaji(
        lyrics.read_text(encoding="utf-8")) else "jp"


def from_lyrics(lyrics: Path, overrides: dict[str, str] | None = None,
                source: str = "jp") -> list[tuple[int, str, str]]:
    """Parse a lyrics file into [(line_no, surface, reading)], skipping blanks.

    The reading keeps its **word boundaries as spaces**. That is not cosmetic:
    this row is what phase 1 writes to the readings TSV, and phase 2 reads that
    file back as an override, where `resolve_words` treats an unspaced reading
    as a single word. Joining the words with "" here therefore destroyed every
    word boundary in the finished karaoke -- the romaji track came out as one
    run-on string -- even though the analyser had the boundaries all along.

    Phase 1 skips whitespace when it builds alignment units, so the spaces cost
    nothing there.
    """
    overrides = overrides or {}
    rows: list[tuple[int, str, str]] = []
    for i, raw in enumerate(lyrics.read_text(encoding="utf-8").splitlines(), 1):
        surface = normalise_surface(raw)
        if not surface:
            continue
        rows.append((i, surface,
                     " ".join(resolve_words(surface, overrides, source))))
    return rows

def units_and_romaji(surface: str, overrides: dict[str, str],
                     source: str = "jp") -> tuple[list[str], list[int], list[str]]:
    """(units, owner, romaji cells) -- the one entry point callers should use.

    For a romaji sheet the three come out of a single walk of the user's line,
    so the romaji track is the characters they typed rather than our
    romanisation of the kana we derived from them. See `romaji.sourced_line`
    for why that has to be one walk and not two agreeing ones.

    A manual override still wins: it names the reading AND the word split, so
    the surface no longer describes the words and the sourced path cannot
    apply. Japanese input takes the analyser and our own romanisation, there
    being no user spelling to preserve.
    """
    from . import moras, romaji

    if source == "romaji" and normalise_surface(surface) not in overrides:
        return romaji.sourced_line(surface, is_foreign)

    words = resolve_words(surface, overrides, source)
    units, owner = moras.split_words(words)
    return units, owner, romaji.line_spaced(units, owner)

