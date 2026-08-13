"""Anime title -> its theme songs.

The problem this solves: you know the show, not the song. Every downstream
lookup -- lyrics, the official track, synced timings -- needs the SONG title,
and searching those services with an anime name returns nothing useful.

Three databases are queried, because measured against the test set each one
fails differently and none is sufficient alone:

    show                     AnimeThemes            MAL/Jikan   ANN
    Duel Masters LOST        wrong series (VSR)     503/504     correct
    Cross Fight B-Daman      correct                503/504     nothing
    Cross Fight B-Daman eS   wrong series (non-eS)  503/504     nothing

AnimeThemes' fuzzy search is the dangerous one: asked for "eS" it silently
returns the themes of the show without "eS" and reports nothing unusual. So
every result carries the SERIES NAME IT ACTUALLY MATCHED, and the caller is
expected to show it. Nothing here ever picks for the user -- a wrong series is
obvious to a human reading "Duel Masters VSR" and invisible to any heuristic
worth writing.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "aksal/0.1 (personal karaoke timing tool)"
TIMEOUT = 20

# Both ANN and MyAnimeList print themes as:  "TITLE" by ARTIST (eps 1-13)
# ANN uses typographic or HTML-escaped quotes depending on the endpoint.
THEME_LINE = re.compile(
    r'["“「]\s*(?P<title>.+?)\s*["”」]'
    r'(?:\s*by\s*(?P<artist>.+?))?'
    r'(?:\s*\((?P<eps>[^)]*ep[^)]*)\))?\s*$',
    re.I)


@dataclass
class Theme:
    kind: str = ""            # "OP" | "ED"
    sequence: str = ""        # "1", "2", "" when a show has only one
    title: str = ""
    artist: str = ""
    episodes: str = ""        # free text, e.g. "eps 1-13"
    source: str = ""          # which database said so
    series: str = ""          # the series name that ACTUALLY matched
    year: int | None = None

    @property
    def label(self) -> str:
        return f"{self.kind}{self.sequence}".strip()

    def describe(self) -> str:
        bits = [f"{self.label or '??':4s} {self.title}"]
        if self.artist:
            bits.append(f"by {self.artist}")
        if self.episodes:
            bits.append(f"({self.episodes})")
        return "  ".join(bits)

    def query(self) -> str:
        """The most precise search string available for this song.

        Precision is everything downstream: measured on LRCLIB, a bare title
        like "Dream" or "TRUTH" returns twenty famous English songs, while the
        exact title returns one correct hit or nothing at all.
        """
        return f"{self.title} {self.artist}".strip() if self.artist else self.title


# --- pure parsers -------------------------------------------------------------

def parse_theme_text(text: str) -> tuple[str, str, str]:
    """Split a `"TITLE" by ARTIST (eps 1-13)` string. Never raises."""
    text = (text or "").replace("&quot;", '"').replace("&amp;", "&").strip()
    m = THEME_LINE.match(text)
    if not m:
        # No quotes: take everything before " by " as the title.
        if " by " in text:
            title, artist = text.split(" by ", 1)
            return title.strip(), artist.strip(), ""
        return text, "", ""
    return (m.group("title") or "").strip(), \
           (m.group("artist") or "").strip(), \
           (m.group("eps") or "").strip()


def split_kind(raw: str) -> tuple[str, str]:
    """"Opening Theme" / "OP2" / "ED" -> ("OP"|"ED", sequence)."""
    raw = (raw or "").strip()
    kind = "OP" if re.search(r"open|^op", raw, re.I) else (
        "ED" if re.search(r"end|^ed", raw, re.I) else "")
    seq = ""
    m = re.search(r"(\d+)", raw)
    if m:
        seq = m.group(1)
    return kind, seq


def parse_animethemes(payload: dict) -> list[Theme]:
    out: list[Theme] = []
    for anime in payload.get("anime", []) or []:
        series = anime.get("name") or ""
        year = anime.get("year")
        for th in anime.get("animethemes", []) or []:
            song = th.get("song") or {}
            title = (song.get("title") or "").strip()
            if not title:
                continue
            artists = ", ".join(a.get("name", "") for a in song.get("artists", [])
                                if a.get("name"))
            kind, seq = split_kind(str(th.get("type") or ""))
            if th.get("sequence"):
                seq = str(th["sequence"])
            out.append(Theme(kind=kind, sequence=seq, title=title, artist=artists,
                             source="animethemes", series=series, year=year))
    return out


def parse_ann(xml_text: str) -> list[Theme]:
    """ANN's encyclopedia XML. Editors curate it, so it is right when present."""
    out: list[Theme] = []
    series = ""
    m = re.search(r'<anime[^>]*\sname="([^"]*)"', xml_text)
    if m:
        series = m.group(1).replace("&amp;", "&")
    year = None
    m = re.search(r"<vintage>(\d{4})", xml_text)
    if m:
        year = int(m.group(1))

    for m in re.finditer(
            r'<info[^>]*type="(Opening|Ending) Theme"[^>]*>(.*?)</info>',
            xml_text, re.S | re.I):
        body = re.sub(r"<[^>]+>", "", m.group(2))
        title, artist, eps = parse_theme_text(body)
        if not title:
            continue
        kind, seq = split_kind(m.group(1))
        # ANN writes the number inside the text ("#2: ..."), not the attribute.
        mm = re.match(r"#?(\d+)[:.]?\s*(.*)", title)
        if mm:
            seq, title = mm.group(1), mm.group(2).strip()
            title, artist2, eps2 = parse_theme_text(title)
            artist = artist or artist2
            eps = eps or eps2
        out.append(Theme(kind=kind, sequence=seq, title=title, artist=artist,
                         episodes=eps, source="ann", series=series, year=year))
    return out


def parse_jikan(series: str, year: int | None, themes: dict) -> list[Theme]:
    out: list[Theme] = []
    for key, kind in (("openings", "OP"), ("endings", "ED")):
        for i, raw in enumerate(themes.get(key) or [], start=1):
            title, artist, eps = parse_theme_text(str(raw))
            if not title:
                continue
            seq = ""
            mm = re.match(r"#?(\d+)[:.]?\s*(.*)", title)
            if mm:
                seq, rest = mm.group(1), mm.group(2).strip()
                title, a2, e2 = parse_theme_text(rest)
                artist = artist or a2
                eps = eps or e2
            out.append(Theme(kind=kind, sequence=seq or (str(i) if i > 1 else ""),
                             title=title, artist=artist, episodes=eps,
                             source="mal", series=series, year=year))
    return out


def dedupe(themes: list[Theme]) -> list[Theme]:
    """Collapse the same song reported by several databases.

    Keeps the first occurrence but prefers one that carries an artist, since the
    artist is what makes the downstream LRCLIB query precise enough to trust.
    """
    best: dict[tuple[str, str], Theme] = {}
    order: list[tuple[str, str]] = []
    for t in themes:
        key = (t.kind, re.sub(r"\W+", "", t.title).lower())
        if key not in best:
            best[key] = t
            order.append(key)
        elif not best[key].artist and t.artist:
            merged = best[key]
            merged.artist = t.artist
            merged.source += f"+{t.source}"
    return [best[k] for k in order]


def filter_kind(themes: list[Theme], kind: str | None) -> list[Theme]:
    return [t for t in themes if not kind or t.kind == kind] or themes


def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def series_score(query: str, series: str) -> float:
    """How well the series a database matched resembles the one asked for.

    This is the antidote to the failure that matters: asked for "Cross Fight
    B-Daman eS", AnimeThemes returns the themes of "Cross Fight B-Daman" and
    reports nothing unusual. Sorting by resemblance puts the plausible series
    first and drops "Cross Game" to the bottom, while the score itself is shown
    so a poor match looks poor.
    """
    import difflib

    q, s = _norm_title(query), _norm_title(series)
    if not q or not s:
        return 0.0
    ratio = difflib.SequenceMatcher(None, q, s).ratio()
    qt, st = set(q.split()), set(s.split())
    overlap = len(qt & st) / max(len(qt), 1)
    return round(0.5 * ratio + 0.5 * overlap, 3)


def rank(themes: list[Theme], query: str) -> list[Theme]:
    """Best-matching series first, then OP before ED, then sequence."""
    def key(t: Theme):
        return (-series_score(query, t.series),
                0 if t.kind == "OP" else 1,
                t.sequence or "")
    return sorted(themes, key=key)


# --- network ------------------------------------------------------------------

def _get(url: str, raw: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read().decode("utf-8", "replace")
    return body if raw else json.loads(body)


def from_animethemes(query: str) -> list[Theme]:
    return parse_animethemes(_get(
        "https://api.animethemes.moe/anime?" + urllib.parse.urlencode(
            {"q": query, "include": "animethemes.song.artists",
             "page[size]": 3})))


def from_ann(query: str) -> list[Theme]:
    return parse_ann(_get(
        "https://cdn.animenewsnetwork.com/encyclopedia/api.xml?"
        + urllib.parse.urlencode({"title": "~" + query}), raw=True))


def from_jikan(query: str) -> list[Theme]:
    hits = _get("https://api.jikan.moe/v4/anime?"
                + urllib.parse.urlencode({"q": query, "limit": 1})).get("data", [])
    if not hits:
        return []
    top = hits[0]
    themes = _get(f"https://api.jikan.moe/v4/anime/{top['mal_id']}/themes")
    return parse_jikan(top.get("title") or "", top.get("year"),
                       themes.get("data", {}) or {})


PROVIDERS = (("AnimeThemes", from_animethemes),
             ("ANN", from_ann),
             ("MyAnimeList", from_jikan))


def search(query: str, kind: str | None = None, log=print) -> list[Theme]:
    """Every theme any database reports for `query`, deduped, never filtered
    down to one. A failing provider is reported and skipped -- MyAnimeList was
    returning 504 for every call while this was written, and one dead service
    must not take the feature with it."""
    found: list[Theme] = []
    for name, fn in PROVIDERS:
        try:
            got = fn(query)
        except Exception as exc:                       # noqa: BLE001
            log(f"  {name}: unavailable ({type(exc).__name__})")
            continue
        log(f"  {name}: {len(got)} theme(s)"
            + (f" for {got[0].series!r}" if got else ""))
        found.extend(got)
    return rank(filter_kind(dedupe(found), kind), query)
