"""Japanese numbers and counters: ichiran's algorithm, not a lookup table.

Ported from ichiran by Timofei Shatrov (MIT), numbers.lisp and
dict-counters.lisp.

WHY AN ALGORITHM. JMdict has 一人 and 三日 as entries, but not 23冊 or ４時 or
十五年 -- number+counter is productive, so no dictionary enumerates it. ichiran
reads any of them with three pieces, all ported here:

  NUMBER READING   二万三百四 -> にまんさんびゃくよん, with the sandhi the
                   groups impose on each other: 三+百 voices (さんびゃく),
                   一+千 geminates (いっせん), 八+百 does both (はっぴゃく).

  COUNTER JOIN     the number's last mora and the counter's first sound
                   interact: 一 + 冊 -> いっさつ, 十 + 匹 -> じゅっぴき. The
                   rule depends only on the digit and the counter's first
                   kana row, so it covers counters no table lists.

  SPECIALS         the counters whose readings are irregular by list: 一人 is
                   ひとり, 二十歳 is はたち, ３日 is みっか, 月 as a month is
                   がつ and only for 1-12. Copied from ichiran's
                   def-special-counter entries, not reinvented.

Generic counters take their kana from the dictionary index (a JMdict entry
tagged `ctr`), so the coverage is JMdict's counter list with ichiran's
euphonics on top.
"""
from __future__ import annotations

# --- number reading (numbers.lisp) -------------------------------------------

DIGIT_KANA = {0: "れい", 1: "いち", 2: "に", 3: "さん", 4: "よん", 5: "ご",
              6: "ろく", 7: "なな", 8: "はち", 9: "きゅう"}
POWER_KANA = {1: "じゅう", 2: "ひゃく", 3: "せん", 4: "まん", 8: "おく",
              12: "ちょう"}

_DIGIT_OF = {c: i for i, c in enumerate("〇一二三四五六七八九")}
_POWER_OF = {"十": 1, "百": 2, "千": 3, "万": 4, "億": 8, "兆": 12}

_DAKUTEN = {"は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ",
            "か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
            "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
            "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど"}
_HANDAKUTEN = {"は": "ぱ", "ひ": "ぴ", "ふ": "ぷ", "へ": "ぺ", "ほ": "ぽ"}

# The kana rows that trigger euphonics, by the counter's FIRST character.
# UNVOICED ONLY, exactly as ichiran's case lists: 一時 is いちじ and 一度 is
# いちど -- a counter that already starts voiced never geminates the number.
_ROW = {}
for _row_name, _chars in (("k", "かきくけこ"), ("s", "さしすせそ"),
                          ("t", "たちつてと"), ("h", "はひふへほ"),
                          ("p", "ぱぴぷぺぽ")):
    for _c in _chars:
        _ROW[_c] = _row_name


def geminate(kana: str) -> str:
    """いち -> いっ, じゅう -> じゅっ: the final mora closes to っ."""
    return kana[:-1] + "っ"


def rendaku(kana: str, handakuten: bool = False) -> str:
    table = _HANDAKUTEN if handakuten else _DAKUTEN
    head = table.get(kana[0])
    return (head + kana[1:]) if head else kana


def _sandhi(prev_kind, prev_val, kind, val, left: str, right: str):
    """num-sandhi: adjustments where two number groups meet."""
    if prev_kind == "d" and kind == "p":
        if prev_val == 1 and val in (3, 12):
            left = geminate(left)                        # いっせん, いっちょう
        elif prev_val == 3 and val in (2, 3):
            right = rendaku(right)                       # さんびゃく, さんぜん
        elif prev_val == 6 and val == 2:
            left, right = geminate(left), rendaku(right, True)   # ろっぴゃく
        elif prev_val == 8:
            if val == 2:
                left, right = geminate(left), rendaku(right, True)  # はっぴゃく
            elif val in (3, 12):
                left = geminate(left)                    # はっせん
    elif prev_kind == "p" and kind == "p" and prev_val == 1 and val == 12:
        left = geminate(left)                            # じゅっちょう
    return left + right


def number_to_kanji(n: int) -> str:
    """Positional Japanese numeral: 23 -> 二十三, 10 -> 十, 10000 -> 一万."""
    if n == 0:
        return "〇"
    if n >= 10 ** 16:
        return "".join("〇一二三四五六七八九"[int(c)] for c in str(n))
    out = []
    for power, unit in ((12, "兆"), (8, "億"), (4, "万"),
                        (3, "千"), (2, "百"), (1, "十")):
        count, n = divmod(n, 10 ** power)
        if not count:
            continue
        if power >= 4:
            out.append(number_to_kanji(count) + unit)
        else:
            # 一千 and 一百 are not how anyone writes them; 一万 is.
            out.append(("" if count == 1 else "〇一二三四五六七八九"[count])
                       + unit)
    if n:
        out.append("〇一二三四五六七八九"[n])
    return "".join(out)


def parse_kanji_number(text: str) -> int | None:
    """The value of a kanji numeral: 二十三 -> 23, 十 -> 10, 二万三百四 -> 20304.

    ichiran's parse-number*: the highest power in the string splits it into
    a multiplier and a remainder, recursively. Plain digit runs (二〇二四)
    read positionally.
    """
    if not text or any(c not in _DIGIT_OF and c not in _POWER_OF
                       for c in text):
        return None

    def parse(chars) -> int:
        best_p, best_i = 0, None
        for i, c in enumerate(chars):
            p = _POWER_OF.get(c, 0)
            if p > best_p:
                best_p, best_i = p, i
        if best_i is None:
            value = 0
            for c in chars:
                value = value * 10 + _DIGIT_OF[c]
            return value
        head = parse(chars[:best_i]) if best_i else 1
        rest = parse(chars[best_i + 1:]) if best_i + 1 < len(chars) else 0
        return head * 10 ** best_p + rest

    return parse(text)


def number_to_kana(n: int) -> str:
    """Read a number aloud, ichiran's way: via its kanji spelling, in groups.

    A group is a digit plus the powers that scale it (三百 -> さんびゃく);
    groups follow each other with sandhi applied inside each pair.
    """
    if n == 0:
        return DIGIT_KANA[0]
    out = ""
    prev = (None, None)
    for ch in number_to_kanji(n):
        if ch in _POWER_OF:
            kind, val = "p", _POWER_OF[ch]
            kana = POWER_KANA[val]
        else:
            kind, val = "d", _DIGIT_OF[ch]
            kana = DIGIT_KANA[val]
        out = _sandhi(prev[0], prev[1], kind, val, out, kana) if out else kana
        prev = (kind, val)
    return out


# --- counter joining (dict-counters.lisp) -------------------------------------

def _last_digit(n: int) -> int:
    """The digit that touches the counter: 23 -> 3, 20 -> 10, 300 -> 100."""
    d = n % 10
    if d:
        return d
    for p in (10, 100, 1000, 10000):
        if n % (p * 10):
            return p
    return 10000


def counter_join(n: int, number_kana: str, counter_kana: str,
                 digit_opts: dict | None = None) -> str:
    """number + counter with ichiran's euphonics.

    `digit_opts` maps a digit to its exceptions: "g" geminate the number,
    "r"/"h" voice the counter (dakuten/handakuten), or a replacement string
    for the digit's kana (時 uses {4: "よ", 7: "しち", 9: "く"}).
    """
    digit = _last_digit(n)
    head = _ROW.get(counter_kana[0])

    opts = (digit_opts or {}).get(digit)
    if opts is not None:
        for opt in (opts if isinstance(opts, (list, tuple)) else (opts,)):
            if opt == "g":
                number_kana = geminate(number_kana)
            elif opt == "r":
                counter_kana = rendaku(counter_kana)
            elif opt == "h":
                counter_kana = rendaku(counter_kana, True)
            elif isinstance(opt, str) and opt.startswith("c:"):
                counter_kana = opt[2:]
            elif isinstance(opt, str):
                # Replace the digit's own kana at the end of the number.
                stem = DIGIT_KANA[digit] if digit < 10 else \
                    POWER_KANA[len(str(digit)) - 1]
                number_kana = number_kana[:-len(stem)] + opt
        return number_kana + counter_kana

    if digit == 1 and head in ("k", "s", "t"):
        number_kana = geminate(number_kana)
    elif digit == 1 and head == "h":
        number_kana = geminate(number_kana)
        counter_kana = rendaku(counter_kana, True)
    elif digit == 3 and head == "h":
        counter_kana = rendaku(counter_kana, True)
    elif digit == 6 and head in ("k", "p"):
        number_kana = geminate(number_kana)
    elif digit == 6 and head == "h":
        number_kana = geminate(number_kana)
        counter_kana = rendaku(counter_kana, True)
    elif digit in (8, 10) and head in ("k", "s", "t", "p"):
        number_kana = geminate(number_kana)
    elif digit in (8, 10) and head == "h":
        number_kana = geminate(number_kana)
        counter_kana = rendaku(counter_kana, True)
    elif digit == 100 and head == "k":
        number_kana = geminate(number_kana)
    elif digit == 100 and head == "h":
        number_kana = geminate(number_kana)
        counter_kana = rendaku(counter_kana, True)
    elif digit in (1000, 10000) and head == "h":
        counter_kana = rendaku(counter_kana, True)
    return number_kana + counter_kana


# --- special counters (def-special-counter), the ones lyrics meet -------------

_HIFUMI = {1: "ひと", 2: "ふた", 3: "み", 4: "よ", 5: "いつ",
           6: "む", 7: "なな", 8: "や", 9: "ここの", 10: "と"}

_DAYS_KUN = {1: "ついたち", 2: "ふつか", 3: "みっか", 4: "よっか",
             5: "いつか", 6: "むいか", 7: "なのか", 8: "ようか",
             9: "ここのか", 10: "とおか", 14: "じゅうよっか",
             20: "はつか", 24: "にじゅうよっか", 30: "みそか"}


def _special(surface: str, n: int) -> str | None:
    """Irregular counter readings, per ichiran's def-special-counter table."""
    if surface == "つ":
        full = {1: "ひとつ", 2: "ふたつ", 3: "みっつ", 4: "よっつ",
                5: "いつつ", 6: "むっつ", 7: "ななつ", 8: "やっつ",
                9: "ここのつ"}
        return full.get(n)
    if surface == "人":
        if n == 1:
            return "ひとり"
        if n == 2:
            return "ふたり"
        return counter_join(n, number_to_kana(n), "にん",
                            {4: "よ", 7: "しち"})
    if surface == "日":
        if n in _DAYS_KUN:
            return _DAYS_KUN[n]
        if n > 10:
            return counter_join(n, number_to_kana(n), "にち")
        return None
    if surface == "月":
        if 1 <= n <= 12:
            return counter_join(n, number_to_kana(n), "がつ",
                                {4: "し", 7: "しち", 9: "く"})
        return None
    if surface in ("歳", "才"):
        if n == 20:
            return "はたち"
        return counter_join(n, number_to_kana(n), "さい")
    return None


# digit_opts per counter, from the def-special-counter entries. A counter not
# listed here and not handled above uses the generic rules with its dictionary
# reading -- which is the majority, and is the point of the algorithm.
_DIGIT_OPTS = {
    "時": {4: "よ", 7: "しち", 9: "く"},
    "時間": {4: "よ", 9: "く"},
    "年": {4: "よ", 7: "しち", 9: "く"},
    "円": {4: "よ"},
    "字": {4: "よ"},
    "畳": {4: "よ", 7: "しち"},
    "分": {4: "h"},
    "分間": {4: "h"},
    "敗": {4: "h"},
    "泊": {4: "h"},
    "本": {3: "r"},
    "匹": {3: "r"},
    "杯": {3: "r"},
    "階": {3: "r"},
    "軒": {3: "r"},
    "遍": {3: "r"},
    "編": {3: "r"},
    "足": {3: "r"},
    "羽": {3: "c:ば", 6: ("g", "c:ぱ"), 10: ("g", "c:ぱ")},
    "段": {7: "しち"},
}


# Counters the segmenter should try even without a `ctr` entry in the index.
SPECIAL_SURFACES = frozenset(_DIGIT_OPTS) | frozenset(
    ("つ", "人", "日", "月", "歳", "才"))


def read_counter(n: int, surface: str, counter_kana: str | None) -> str | None:
    """The reading of number `n` + counter `surface`, or None if disallowed.

    `counter_kana` is the counter's dictionary reading (from the index); the
    specials above override it or restrict which numbers are valid.
    """
    got = _special(surface, n)
    if got is not None:
        return got
    if surface in ("日", "月"):        # handled above; other values invalid
        return None
    if not counter_kana:
        return None
    return counter_join(n, number_to_kana(n), counter_kana,
                        _DIGIT_OPTS.get(surface))
