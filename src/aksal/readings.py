"""Surface text -> kana reading.

A morphological analyser gets most lines right, but song lyrics are exactly
where analysers fail: ateji, coined readings, furigana that contradicts the
kanji, and digits. So readings live in an editable override table keyed by
SURFACE TEXT, not by line number -- that way a correction survives you
splitting, merging or reordering lines between phases.
"""
from __future__ import annotations

import os
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
_TAGGER_ARGS = ""


def tagger():
    """The analyser, pinned to unidic-lite ON PURPOSE.

    `fugashi.Tagger()` with no arguments uses whichever dictionary happens to
    be installed, preferring full UniDic over unidic-lite. So merely having
    `unidic` in the environment -- for some unrelated project -- silently
    changes every reading this tool produces, and changes them for the worse:
    UniDic 3.1 reads 方 in その方が良い as カタ where unidic-lite reads ホウ.

    Nothing in the output would say so. Pinning it costs one argument and makes
    the readings a property of AKSAL rather than of the machine it runs on.
    """
    global _TAGGER
    if _TAGGER is None:
        import fugashi
        import unidic_lite

        global _TAGGER_ARGS
        _TAGGER_ARGS = tagger_args(unidic_lite.DICDIR)
        _TAGGER = fugashi.Tagger(_TAGGER_ARGS)
    return _TAGGER


def tagger_args(dicdir: str | Path) -> str:
    """MeCab arguments selecting `dicdir`, quoted so a space cannot split it.

    MeCab takes its arguments as ONE STRING and tokenises it on whitespace, so
    an unquoted path breaks in half the moment it contains a space -- and the
    halves become two separate arguments, the second of which is nonsense.
    Measured: `-d C:/a b/dicdir` arrives as [b'-d', b'C:/a', b'b/dicdir'].

    That is not an exotic case. It fires on `C:/Program Files`, on any user
    folder with a space in the name, and on the folder a browser creates when
    you download the same archive twice -- `aksal-windows (1)`. It was reported
    from exactly that path.

    MeCab's tokeniser does honour double quotes, which is the whole fix. A
    literal double quote in a path cannot be handled and cannot occur: Windows
    forbids the character in filenames outright.
    """
    return f'-d "{Path(dicdir).as_posix()}"'


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
# comes back as 辿 + U+E0100.
#
# Left in place the selector becomes a token of its own AND splits the word
# around itself, so the kanji is analysed alone and loses its reading. Measured
# over the 229 lyric lines of the test corpus, without this five kanji are
# affected across about twelve word instances: 辿, 疼 and 逢 lose their reading
# entirely, while 出, 嘲 and the 着く forms keep theirs but gain a spurious
# karaoke cell. The split also leaves debris -- り, く, って and friends
# analysed as standalone words.
#
# All of it silent, which is precisely the failure this normalisation exists to
# prevent.
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


# Single words the analyser simply reads wrong. Applied last, so it overrides
# the analyser, the compound repair and the phrase lexicon alike.
#
# THE BAR FOR ENTRY IS HIGH, because this is a blunt instrument: a word here is
# read the same way in every song, so a context-dependent reading MUST NOT be
# listed. Both of these were mined from 109 verified songs and then checked in
# isolation and in phrases -- each is wrong in EVERY context, not merely the
# usual one:
#
#   僕等   the analyser gives ぼくとう, which is not a reading this word has.
#   屍     it gives かばね, an archaic reading; singers used しかばね 3 times
#          out of 3, and no occurrence of かばね was found.
#
# Deliberately NOT here, and worth recording so they are not added later:
#
#   間     ambiguous for real. あいだ and ま are both ordinary and mean
#          different things; the analyser already gets ま right on its own.
#   明日   あす and あした are both correct. Singers prefer あした (7 songs),
#          but they differ in mora count, so forcing one changes the TIMING of
#          every line containing it. A 55% majority does not justify that.
WORD_READINGS: dict[str, str] = {
    "僕等": "ぼくら",
    "屍": "しかばね",
}


# Which engine decides word boundaries and readings.
#
#   ichiran   JMdict entries chosen by ichiran's best-path search. The default,
#             because a dictionary knows things a morphological analyser cannot
#             derive: 夜が明ける is one entry read よがあける, where short-unit
#             analysis can only produce 夜 (よる) + が + 明ける.
#   unidic    the morphological analyser alone, which is what earlier releases
#             did. Kept because it is better at rare vocabulary and because a
#             switch costs nothing.
#
# Neither is trusted blindly: an ichiran run still hands anything its
# dictionary does not cover to UniDic, which always has an answer.
ENGINES = ("ichiran", "unidic")
# AKSAL_ANALYSER selects the engine for a process that has no CLI of its own --
# a test harness, or anything shelling out to a helper script. Without it the
# choice cannot cross a process boundary, and a subprocess silently reverts to
# the default while its caller believes it set something else.
ENGINE = os.environ.get("AKSAL_ANALYSER", "ichiran")
if ENGINE not in ENGINES:
    ENGINE = "ichiran"


def set_engine(name: str) -> None:
    if name not in ENGINES:
        raise ValueError(f"unknown analyser {name!r}; choose from {ENGINES}")
    global ENGINE
    ENGINE = name


def analyse_words(text: str) -> list[tuple[str, str]]:
    """Tokenise a line into (surface, kana) pairs, via the selected engine."""
    if ENGINE == "ichiran":
        got = _analyse_ichiran(text)
        if got is not None:
            return got
    return analyse_words_unidic(text)


def _analyse_ichiran(text: str) -> list[tuple[str, str]] | None:
    """The dictionary path, or None when it is unavailable.

    Characters no dictionary entry covers come back with an empty reading, and
    those spans go to UniDic rather than being dropped: every mora becomes a
    karaoke cell that has to be aligned, so a missing reading is not a degraded
    result but a broken line.
    """
    try:
        from . import ichiran
    except ImportError:                          # pragma: no cover
        return None
    if not ichiran.available():
        return None

    out: list[tuple[str, str]] = []
    for surface, kana in ichiran.analyse_words(text):
        if kana:
            out.append((surface, WORD_READINGS.get(surface, kana)))
        else:
            out.extend(analyse_words_unidic(surface))
    return out or None


def analyse_words_unidic(text: str) -> list[tuple[str, str]]:
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
        out[chunk_start:] = join_phrases(repaired)

    return [(surface, WORD_READINGS.get(surface, kana))
            for surface, kana, _pos in out]


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



# =============================================================================
# Lexicalised phrases
# =============================================================================

# UniDic emits SHORT unit words: it segments grammar, and grammatically 共に is
# 共 + に and どうにか is どう + に + か. Correct as grammar, wrong as words --
# every dictionary lists these as single entries, and a reader (and ichi.moe)
# treats them as one.
#
# An explicit list, NOT a rule. The rule was tried: "pronoun + か/も joins" cost
# five new run-ons, because no part-of-speech pattern separates いつも (a
# lexicalised adverb) from どれも (a pronoun and a particle). They are
# grammatically identical and lexically different, so only a lexicon can tell
# them apart.
#
# The value is an explicit reading, or None to concatenate the parts'. Mostly
# None -- but 何 is read ナン by the analyser, so 何か and 何も would come out
# nanka and nanmo rather than nanika and nanimo.
PHRASES: dict[str, str | None] = {
    # Indefinites. Deliberately NOT 君も / どれも / どこも: those are a noun and
    # a particle, not a word.
    "誰か": None, "何か": "なにか", "何も": "なにも",
    "いつか": None, "いつも": None, "どこか": None, "なぜか": None,
    # Adverbs written as particle strings.
    "どうにか": None, "どんなに": None, "そんなに": None,
    "こんなに": None, "あんなに": None,
    # Adverbial に-forms that are lexicalised. 本当に / 確かに / 同時に are
    # deliberately absent -- those read naturally as noun + に. Note UniDic
    # already joins 既に while splitting 共に, so it is not principled here
    # either; this is lexicon coverage, not grammar.
    "共に": None, "直ぐに": None, "すぐに": None,
    # Conjunctions. Split, these come out "da tte", "da kedo", "da kara".
    "だって": None, "だけど": None, "だから": None,
    "けれども": None, "それでも": None,
}

MAX_PHRASE_WORDS = 5

_RIVAL = None
_RIVAL_TRIED = False


def _rival_analyser():
    """An independent opinion on readings, or None if pykakasi is absent.

    Independent is the whole requirement. cutlet, Sudachi and full UniDic were
    all measured and all failed it -- they run the same UniDic lineage and tie
    with us on 42-47 lines out of 48, so they cannot contribute a second
    opinion. pykakasi has its own dictionary lineage and disagrees where that
    lineage differs, which is exactly where a reading is worth checking.

    Its overall quality is WORSE than ours (0.934 against 0.963 on the corpus,
    and it renders っ as "tsu"), so nothing it says is ever adopted. It only
    nominates; the audio decides.
    """
    global _RIVAL, _RIVAL_TRIED
    if not _RIVAL_TRIED:
        _RIVAL_TRIED = True
        try:
            import pykakasi

            _RIVAL = pykakasi.kakasi()
        except Exception:                   # pragma: no cover - optional
            _RIVAL = None
    return _RIVAL


def rival_reading(surface: str, ours: str) -> str | None:
    """A second engine's reading for one word, when it is worth arbitrating.

    Returns None unless every condition holds, because each one removes a class
    of disagreement that is not a real dispute:

      * the surface contains kanji -- kana spells its own reading, so there is
        nothing to arbitrate
      * it is not a particle -- を/は/へ are converted to their SUNG form here
        on purpose while pykakasi keeps the written one. Measured, that alone
        produced 15 of 16 apparent disputes, and since を and お are the same
        sound the audio cannot separate them anyway
      * the two readings have the same mora count -- comparing different
        lengths against audio does not work at all. CTC prefers the shorter
        candidate whatever was sung, because fewer tokens means fewer
        constraints and blank frames are nearly free. Equal-length pairs score
        88%; unequal ones are a coin flip or worse.
    """
    from . import moras

    if not KANJI.search(surface) or surface in "をはへ":
        return None
    kks = _rival_analyser()
    if kks is None:
        return None
    try:
        segs = kks.convert(surface)
    except Exception:                       # pragma: no cover
        return None
    if len(segs) != 1:
        return None
    theirs = jaconv.kata2hira(segs[0].get("kana") or "")
    if not theirs or theirs == ours:
        return None
    if len(moras.split(theirs)) != len(moras.split(ours)):
        return None
    return theirs

_USER_PHRASES_LOADED = False


def load_user_phrases() -> Path | None:
    """Merge `aksal.phrases.tsv` from the install directory, if present.

    Which sequences count as one word is a CONVENTION, not a fact, so the
    built-in list is a starting point rather than an answer -- 本当に is left
    split here and someone will reasonably want it joined. Two tab-separated
    columns: the surface, and optionally the reading when concatenating the
    parts' readings would be wrong (as it is for 何か).

    An empty second column means "concatenate", and a row with the surface
    alone and the word DELETE removes a built-in entry, so the list can be
    trimmed as well as extended.
    """
    global _USER_PHRASES_LOADED
    if _USER_PHRASES_LOADED:
        return None
    _USER_PHRASES_LOADED = True
    from . import tools

    path = tools.home() / "aksal.phrases.tsv"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        surface = parts[0].strip()
        value = parts[1].strip() if len(parts) > 1 else ""
        if not surface:
            continue
        if value.upper() == "DELETE":
            PHRASES.pop(surface, None)
        else:
            PHRASES[surface] = jaconv.kata2hira(value) if value else None
    return path


def join_phrases(words: list[tuple[str, str, str]]
                 ) -> list[tuple[str, str, str]]:
    """Merge consecutive words that form one lexicalised phrase.

    Longest match first, so どんなに wins over any shorter prefix of itself.
    Runs after `repair_compounds` and inside a chunk, so an explicit space in
    the lyric sheet still stops a merge from crossing it -- the writer's
    spacing outranks this list.

    The merged word keeps the analyser's part of speech for its FIRST element.
    Nothing downstream inspects it after this point, and inventing a tag would
    be a claim this function is not entitled to make.
    """
    load_user_phrases()
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(words):
        merged = None
        for n in range(min(MAX_PHRASE_WORDS, len(words) - i), 1, -1):
            surface = "".join(w[0] for w in words[i:i + n])
            if surface in PHRASES:
                reading = PHRASES[surface] or "".join(w[1] for w in words[i:i + n])
                merged = (surface, reading, words[i][2])
                i += n
                break
        if merged is not None:
            out.append(merged)
        else:
            out.append(words[i])
            i += 1
    return out

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

