"""ichiran's suffix machinery: auxiliaries attached during the search.

Ported from ichiran by Timofei Shatrov (MIT), dict-grammar.lisp.

WHY SUFFIXES ARE NOT INDEX ROWS. 狂っていた is 狂って + いた, and いる itself
conjugates -- いた, いて, います, いました, いない, てる, てた. Pre-generating
every root x auxiliary x auxiliary-inflection product explodes the index and
still misses forms; an earlier attempt did exactly that and could not express
〜ていました without another sixteen rows per verb. ichiran instead attaches
the auxiliary during the search: one mechanism, closed under conjugation,
because the suffix strings themselves are GENERATED from the auxiliary's own
conjugation table at load time.

EACH SUFFIX CARRIES A CONNECTOR, and this is the part no pre-generation can
express: `""` joins root and suffix into one sung word (狂っていた is
kurutteita), `" "` keeps them separate words under one match (学生です is
"gakusei desu"). The connector decides how many karaoke cells the compound
becomes, which for a karaoke tool is not a detail.

Scores are ichiran's :score values verbatim. An int is a per-mora modifier
(apply-score-mod: score * prop_score * suffix_moras); a callable is a constant
bonus (`(constantly 200)` for です).

WHAT IS DELIBERATELY NOT PORTED: suffixes whose root test needs JMdictDB
queries with no equivalent field here (:suru -- our index already conjugates
every vs noun directly), and rare literary abbreviations (ざる, しましょ).
Each omission is a smaller cache, not a differently-shaped mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import conjugate as C
from .scoring import mora_length

# ---------------------------------------------------------------------------
# The suffix cache: suffix string -> [(keyword, ...)], generated at load time
# from the auxiliaries' own conjugations, exactly as init-suffixes does with
# get-kana-forms. Keyed by what the text can END WITH.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    keyword: str        # ichiran's suffix class keyword
    kana: str           # the suffix string as sung (identical to its surface)
    connector: str      # "" joins into one word, " " keeps two words
    score: object       # int per-mora modifier, or callable constant
    root: str           # which root forms attach: te/stem/adj-stem/...
    drop: int = 0       # abbreviations: kana chars the suffix replaces


def _forms(base: str, cls: str) -> list[tuple[str, str]]:
    """(form, name) pairs of a kana auxiliary, via the shared conjugator."""
    return [(s, name) for s, _r, name in C.forms(base, base, cls)]


def _build() -> dict[str, list[Rule]]:
    cache: dict[str, list[Rule]] = {}

    def put(rule: Rule) -> None:
        bucket = cache.setdefault(rule.kana, [])
        if not any(r.keyword == rule.keyword and r.root == rule.root
                   for r in bucket):
            bucket.append(rule)

    # --- auxiliaries on the te-form (suffix-te and friends) -------------------
    # いる gets special treatment in ichiran: the full form is :teiru+ (score
    # 6), and the form MINUS its leading い is registered too -- that single
    # line is where てる, てた, てない and てました come from.
    for form, _name in _forms("いる", C.ICHIDAN):
        put(Rule(":teiru+", form, "", 6, "te"))
        if len(form) > 1:
            put(Rule(":teiru", form[1:], "", 3, "te"))

    for aux, cls in (("おる", C.GODAN), ("ある", C.GODAN), ("おく", C.GODAN),
                     ("しまう", C.GODAN), ("くる", C.KURU)):
        base = "来る" if aux == "くる" else aux
        forms = C.forms(base, aux, cls) if aux != "くる" else \
            [(r, r, n) for _s, r, n in C.forms("来る", "くる", C.KURU)]
        for s, _r, _n in forms:
            put(Rule(":te", s, "", 0, "te"))

    # いく: forms keep their reading; the short form (く, った...) only fills
    # gaps, exactly ichiran's `(unless (gethash tkf-short *suffix-cache*))`.
    iku_forms = [s for s, _r, _n in C.forms("いく", "いく", C.GODAN_IKU)]
    for s in iku_forms:
        put(Rule(":te", s, "", 0, "te"))
    for s in iku_forms:
        if len(s) > 1 and s[1:] not in cache:
            put(Rule(":te", s[1:], "", 0, "te"))

    # ても/でも: "even if", sung as one word (消えても is kietemo).
    put(Rule(":te", "も", "", 0, "te"))

    # ~てくれる / ~てもらう / ~ていただく: separate words in romaji.
    for aux, cls in (("くれる", C.ICHIDAN), ("もらう", C.GODAN),
                     ("いただく", C.GODAN)):
        for s, _n in _forms(aux, cls):
            put(Rule(":te+space", s, " ", 3, "te"))

    put(Rule(":teii", "いい", " ", 1, "te"))
    put(Rule(":teii", "もいい", " ", 1, "te"))
    put(Rule(":kudasai", "ください", " ", lambda p: 360, "te"))

    # --- contractions built on the te-form (stem 1) ---------------------------
    # ちゃう/じゃう: root's te-form loses its て/で and the contraction takes
    # its place: 狂って + ちゃった -> 狂っちゃった.
    for aux in ("ちゃう", "ちまう"):
        for s, _n in _forms(aux, C.GODAN):
            put(Rule(":chau", s, "", 5, "te-contract"))
    for aux in ("じゃう", "じまう"):
        for s, _n in _forms(aux, C.GODAN):
            put(Rule(":chau", s, "", 5, "te-contract"))
    for s, _n in _forms("とく", C.GODAN):
        put(Rule(":to", s, "", 0, "te-contract"))
    for s, _n in _forms("どく", C.GODAN):
        put(Rule(":to", s, "", 0, "te-contract"))

    # --- on the continuative stem (conj-type 13) ------------------------------
    for s, _n in _forms("たい", C.ADJ_I):
        put(Rule(":tai", s, "", 5, "stem"))
    for s, _n in _forms("すぎる", C.ICHIDAN):
        put(Rule(":ren", s, "", 5, "stem"))
    for kana in ("つつ", "がち"):
        put(Rule(":ren", kana, "", 5, "stem"))
    for kana in ("にくい", "がたい", "がい"):
        put(Rule(":ren-", kana, "", 0, "stem"))
    put(Rule(":neg", "なく", "", 5, "neg-stem"))

    # そう "looking like": 消えそう, 泣きそう. ichiran scores this a constant
    # 70 -- it has to beat 相 and 僧 without help from length.
    for kana in ("そう", "そうだ", "そうな", "そうに"):
        put(Rule(":sou", kana, "", lambda p: 70, "stem"))
        put(Rule(":sou", kana, "", lambda p: 70, "adj-stem"))

    # --- on the adjective stem -------------------------------------------------
    put(Rule(":sa", "さ", "", 2, "adj-stem"))
    put(Rule(":iadj", "げ", "", 1, "adj-stem"))
    put(Rule(":iadj", "め", "", 1, "adj-stem"))
    for s, _n in _forms("がる", C.GODAN):
        put(Rule(":garu", s, "", 0, "adj-stem"))

    # --- on other forms ---------------------------------------------------------
    put(Rule(":rou", "ろう", "", 1, "past"))
    for s, _n in _forms("らしい", C.ADJ_I):
        put(Rule(":rashii", s, "", 3, "base"))
    for s, _n in _forms("なる", C.GODAN):
        put(Rule(":naru", s, "", 1, "adv"))
    put(Rule(":ra", "ら", "", 1, "pn"))
    for kana in ("です", "でしょう", "でしょ"):
        score = 200 if kana == "です" else 300
        put(Rule(":desu", kana, " ", (lambda p, s=score: s), "neg"))
        put(Rule(":desu", kana, " ", (lambda p, s=score: s), "neg-past"))
    for s, _n in _forms("とする", C.SURU):
        put(Rule(":tosuru", s, " ", 3, "vol"))
    for kana in ("くらい", "ぐらい"):
        put(Rule(":kurai", kana, " ", 3, "past"))

    # --- abbreviations: the suffix REPLACES the tail of an inflected form -----
    # ~ない -> ~ん / ~ねえ / ~ず / ~ぬ  (分からん, 知らねえ, 消えず)
    for kana in ("ん", "ねえ", "ねぇ", "ねー", "ず", "ぬ"):
        put(Rule(":nai", kana, "", 0, "neg", drop=2))
    # ~なければ -> ~なきゃ / ~なくちゃ  (行かなきゃ)
    for kana in ("なきゃ", "なくちゃ"):
        put(Rule(":nakereba", kana, "", 0, "neg-cond", drop=4))
    # ~えば -> ~ゃ  (行けば -> 行きゃ, 待てば -> 待ちゃ)
    for kana in ("ちゃ", "りゃ", "きゃ", "ぎゃ", "にゃ", "びゃ", "みゃ", "しゃ"):
        put(Rule(":eba", kana, "", 0, "cond", drop=2))

    return cache


_CACHE: dict[str, list[Rule]] | None = None
_MAX_LEN = 0


def cache() -> dict[str, list[Rule]]:
    global _CACHE, _MAX_LEN
    if _CACHE is None:
        _CACHE = _build()
        _MAX_LEN = max(len(k) for k in _CACHE)
    return _CACHE


def candidates(index, span: str):
    """Every root+suffix reading of `span`, as (root_entry, rule, compound).

    compound is (surface, reading, parts, use_length, score_mod):
      surface     the whole span
      reading     kana with the connector applied
      parts       [(surface, kana), ...] -- two entries when the connector is
                  a space, one when the compound is a single sung word
      use_length  mora length of the whole compound, for scoring the root
    """
    table = cache()
    out = []
    for cut in range(1, min(_MAX_LEN, len(span) - 1) + 1):
        suffix = span[-cut:]
        rules = table.get(suffix)
        if not rules:
            continue
        root_text = span[:-cut]
        for rule in rules:
            for root, reading, parts in _roots(index, root_text, suffix, rule):
                use_length = mora_length(root.surface + suffix)
                out.append((root, rule, (span, reading, parts, use_length)))
    return out


def _roots(index, root_text: str, suffix: str, rule: Rule):
    """Root entries `rule` allows for `root_text`, with the assembled kana."""
    # ちゃう-type contractions rebuild the te-form: the root text lost its
    # て/で to the contraction, so it is restored for the lookup and dropped
    # from the reading.
    if rule.root == "te-contract":
        te = {"ち": "て", "と": "て", "じ": "で", "ど": "で"}.get(suffix[0])
        if not te:
            return
        for e in index.by_surface.get(root_text + te, ()):
            if e.form == "te":
                kana = e.reading[:-1] + suffix
                yield e, kana, [(root_text + suffix, kana)]
        return

    if rule.root == "pn":
        for e in index.by_surface.get(root_text, ()):
            if e.pos == "pn":
                kana = e.reading + suffix
                yield e, kana, [(root_text + suffix, kana)]
        return

    if rule.drop:
        # Abbreviation: root_text + (inflected tail) is in the index; the
        # suffix replaces the tail's last `drop` kana. 分から+ん looks up
        # 分からない and drops ない; 行+きゃ looks up 行けば and drops けば --
        # the conditional's e-row char is recovered from the contraction's
        # first char (ちゃ<-てば, りゃ<-れば, きゃ<-けば ...).
        if rule.root == "cond":
            eba = {"ちゃ": "てば", "りゃ": "れば", "きゃ": "けば",
                   "ぎゃ": "げば", "にゃ": "ねば", "びゃ": "べば",
                   "みゃ": "めば", "しゃ": "せば"}
            tail = eba[suffix]
        else:
            tail = {"neg": "ない", "neg-cond": "なければ"}[rule.root]
        for e in index.by_surface.get(root_text + tail, ()):
            if e.form != rule.root or len(e.reading) < rule.drop:
                continue
            kana = e.reading[:-rule.drop] + suffix
            yield e, kana, [(root_text + suffix, kana)]
        return

    allowed = {"te": ("te",), "stem": ("stem",),
               "neg-stem": ("stem", "neg-stem"), "adj-stem": ("adj-stem",),
               "adv": ("adv",), "past": ("past",), "vol": ("vol",),
               "neg": ("neg",), "neg-past": ("neg-past",),
               "base": ("base",), "cond": ("cond",)}[rule.root]
    for e in index.by_surface.get(root_text, ()):
        # A secondary conjugation keeps its ancestry in the name: "pass-te"
        # (葬られて) is still a te-form to the auxiliary that follows it.
        form = e.form.rsplit("-", 1)[-1] if e.form.startswith(
            ("pot-", "pass-", "caus-")) else e.form
        if form not in allowed:
            continue
        # te-check: the root must genuinely end in て/で and not BE で.
        if rule.root == "te" and (root_text == "で"
                                  or root_text[-1] not in "てで"):
            continue
        # teiru-check: ichiran refuses いて as a root of いる forms.
        if rule.keyword in (":teiru", ":teiru+") and root_text == "いて":
            continue
        if rule.keyword == ":tai" and root_text == "い":
            continue
        if rule.connector == " ":
            kana = e.reading + " " + suffix
            parts = [(root_text, e.reading), (suffix, suffix)]
        else:
            kana = e.reading + suffix
            parts = [(root_text + suffix, kana)]
        yield e, kana, parts
