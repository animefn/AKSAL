"""Arabic digits, so that 1人 reads like 一人.

WHY THIS IS SMALL. ichiran spends `numbers.lisp` and `dict-counters.lisp` -- and
by the author's account, years -- on Japanese counters, because every counter
has its own euphonic exceptions: 一人 is ひとり, 三日 is みっか, 十回 is じゅっかい.
Reproducing that table is not the job here, because JMDICT ALREADY HAS IT:
一人, 三日, 二つ and hundreds more are dictionary entries with their irregular
readings attached, and the segmenter reads them correctly already.

What it cannot read is the same word written with an Arabic digit. Lyric sheets
mix the two freely, and a digit reaches the aligner as a character with no
reading at all -- the failure is total rather than merely wrong.

So the whole of this module is: rewrite digit runs as kanji numerals, and let
the dictionary supply the reading it already knows. That converts an unsolved
problem into one that is already solved, and inherits every exception JMdict
records rather than restating them here.
"""
from __future__ import annotations

import re

DIGITS = "〇一二三四五六七八九"
DIGIT_RUN = re.compile(r"[0-9０-９]+")

# Full-width digits are common in Japanese text and must normalise identically.
_FULLWIDTH = {ord("０") + i: str(i) for i in range(10)}


def to_kanji_numeral(n: int) -> str:
    """Japanese numeral for a non-negative integer, as it is written.

    Positional style (10 -> 十, 23 -> 二十三, 100 -> 百): the leading 一 is
    dropped for 十, 百 and 千, because 一十 is not how anyone writes ten and a
    dictionary lookup of it would find nothing.
    """
    if n == 0:
        return "〇"
    if n >= 10 ** 8:                       # beyond anything a lyric needs
        return "".join(DIGITS[int(c)] for c in str(n))

    out = []
    for unit_value, unit in ((10 ** 8, "億"), (10 ** 4, "万"),
                             (1000, "千"), (100, "百"), (10, "十")):
        count, n = divmod(n, unit_value)
        if not count:
            continue
        if unit_value >= 10 ** 4:
            out.append(to_kanji_numeral(count) + unit)
        else:
            # 一千 and 一百 are wrong; 一万 is right, which is why the large
            # units above take the recursive branch and these do not.
            out.append(("" if count == 1 else DIGITS[count]) + unit)
    if n:
        out.append(DIGITS[n])
    return "".join(out)


def normalise_digits(text: str) -> str:
    """Rewrite every run of Arabic digits as a Japanese numeral.

    A run is converted as one number -- "10" is 十, not 一〇 -- because that is
    what makes the counter after it read correctly.
    """
    def convert(match: re.Match) -> str:
        run = match.group(0).translate(_FULLWIDTH)
        try:
            return to_kanji_numeral(int(run))
        except ValueError:                 # pragma: no cover - unreachable
            return run

    return DIGIT_RUN.sub(convert, text)
