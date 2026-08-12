"""Lyrics input: a local file, a Uta-Net page, or an LRCLIB lookup.

`--lyrics` is deliberately polymorphic, because the whole point of the tool is
not doing tedious things by hand:

    --lyrics lyrics.txt                        a file you already have
    --lyrics https://www.uta-net.com/song/N/   a Uta-Net song page
    --lyrics "朔日"                             an LRCLIB search

Whatever the source, the resolved text is cached to the project directory as a
plain file. Everything after that reads the cache, so a fetch happens once and
you can hand-correct the result without it being overwritten.

LRCLIB can also return **synced** lyrics -- line timings against the studio
track, which is exactly the timeline AKSAL aligns to. Those are kept alongside
the text; see `LyricsResult.timings`.

Parsing and IO are separated on purpose: `parse_*` are pure functions over text,
so they are testable without touching the network.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "aksal/0.1 (personal karaoke timing tool)"
TIMEOUT = 25

LRC_LINE = re.compile(r"^((?:\[\d+:\d+(?:[.:]\d+)?\])+)(.*)$")
LRC_STAMP = re.compile(r"\[(\d+):(\d+)(?:[.:](\d+))?\]")
UTANET_SONG = re.compile(r"uta-net\.com/song/(\d+)", re.I)


@dataclass
class LyricsResult:
    lines: list[str]
    source: str = ""
    title: str = ""
    artist: str = ""
    # (seconds, line) against the reference track, when the source supplies them
    timings: list[tuple[float, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def describe(self) -> str:
        who = " / ".join(x for x in (self.title, self.artist) if x)
        bits = [f"{len(self.lines)} lines from {self.source}"]
        if who:
            bits.append(who)
        if self.timings:
            bits.append(f"{len(self.timings)} synced line timings")
        return "  " + ", ".join(bits)


# --- pure parsers -------------------------------------------------------------

def clean_lines(raw: str) -> list[str]:
    """Normalise a lyric body into lines, dropping blanks at the edges only.

    Interior blank lines are KEPT: they mark verse boundaries, and AKSAL's line
    numbering is what the readings table and the user's corrections key on.
    """
    lines = [html_mod.unescape(l).replace("　", " ").rstrip()
             for l in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def parse_utanet(page: str) -> LyricsResult:
    """Extract lyrics from a Uta-Net song page.

    Prefers the schema.org `itemprop="text"` container over the `kashi_area`
    id: the microdata is part of a published contract with search engines and
    changes far less often than presentational markup.
    """
    body = None
    for pattern in (r'<div[^>]+itemprop="text"[^>]*>(.*?)</div>',
                    r'<div[^>]+id="kashi_area"[^>]*>(.*?)</div>'):
        m = re.search(pattern, page, re.S | re.I)
        if m:
            body = m.group(1)
            break
    if body is None:
        raise ValueError(
            "could not find the lyric body on this Uta-Net page -- their markup "
            "may have changed; save the lyrics to a file and pass that instead")

    text = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)

    # Take the name from the music entity only. A page carries several ld+json
    # blocks and the first `name` is usually the WebPage's -- which is the
    # browser title ("<artist> <song> 歌詞 - 歌ネット"), not the song.
    title = artist = ""
    for blob in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                           page, re.S | re.I):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if not isinstance(item, dict):
                continue
            kinds = item.get("@type") or ""
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if not any("Music" in str(k) for k in kinds):
                continue
            title = title or str(item.get("name") or "")
            by = item.get("byArtist")
            if isinstance(by, dict):
                artist = artist or str(by.get("name") or "")
            elif isinstance(by, str):
                artist = artist or by
    if not title:
        m = re.search(r"<h2[^>]*>(.*?)</h2>", page, re.S)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()

    return LyricsResult(lines=clean_lines(text), source="uta-net",
                        title=html_mod.unescape(title),
                        artist=html_mod.unescape(artist))


def parse_lrc(text: str) -> tuple[list[str], list[tuple[float, str]]]:
    """Parse LRC into (lines, timings). Plain text passes through untouched."""
    lines: list[str] = []
    timings: list[tuple[float, str]] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        m = LRC_LINE.match(raw.strip())
        if not m:
            lines.append(raw.rstrip())
            continue
        content = m.group(2).strip()
        stamps = LRC_STAMP.findall(m.group(1))
        # One line may carry several stamps (a repeated refrain).
        for mm, ss, frac in stamps:
            fraction = float(f"0.{frac}") if frac else 0.0
            timings.append((int(mm) * 60 + int(ss) + fraction, content))
        lines.append(content)
    timings.sort(key=lambda t: t[0])
    return lines, timings


def pick_lrclib(results: list[dict], query: str) -> dict | None:
    """Choose the best LRCLIB hit: synced beats plain, longer beats shorter.

    Artist matching is deliberately NOT used to filter. LRCLIB frequently stores
    a romanised artist ("Tsukuyomi") where the query is Japanese ("月詠み"), so
    filtering on artist silently returns nothing for exactly the songs we want.
    """
    usable = [r for r in results if not r.get("instrumental")
              and (r.get("syncedLyrics") or r.get("plainLyrics"))]
    if not usable:
        return None
    return max(usable, key=lambda r: (bool(r.get("syncedLyrics")),
                                      len(r.get("syncedLyrics")
                                          or r.get("plainLyrics") or "")))


# --- network ------------------------------------------------------------------

def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def fetch_utanet(url: str) -> LyricsResult:
    if not UTANET_SONG.search(url):
        raise ValueError(f"not a Uta-Net song URL: {url}")
    return parse_utanet(_get(url))


def fetch_lrclib(query: str) -> LyricsResult:
    results = json.loads(
        _get("https://lrclib.net/api/search?"
             + urllib.parse.urlencode({"q": query})))
    if not isinstance(results, list):
        raise ValueError("unexpected response from LRCLIB")
    best = pick_lrclib(results, query)
    if best is None:
        raise ValueError(
            f"LRCLIB has nothing usable for {query!r}. Try the song title alone "
            "-- LRCLIB often stores a romanised artist name, so including the "
            "Japanese artist can match nothing.")

    body = best.get("syncedLyrics") or best.get("plainLyrics") or ""
    lines, timings = parse_lrc(body)
    return LyricsResult(lines=clean_lines("\n".join(lines)), source="lrclib",
                        title=str(best.get("trackName") or ""),
                        artist=str(best.get("artistName") or ""),
                        timings=timings)


# --- dispatch -----------------------------------------------------------------

def resolve(spec: str, cache: Path | None = None, refresh: bool = False,
            log=print) -> LyricsResult:
    """Turn a --lyrics value into lyrics: file path, URL, or LRCLIB search."""
    if cache is not None and cache.exists() and not refresh:
        log(f"  using cached lyrics: {cache}")
        lines, timings = parse_lrc(cache.read_text(encoding="utf-8"))
        return LyricsResult(lines=clean_lines("\n".join(lines)),
                            source=str(cache), timings=timings)

    path = Path(spec)
    if path.exists():
        lines, timings = parse_lrc(path.read_text(encoding="utf-8-sig"))
        result = LyricsResult(lines=clean_lines("\n".join(lines)),
                              source=str(path), timings=timings)
    elif spec.lower().startswith(("http://", "https://")):
        if UTANET_SONG.search(spec):
            log(f"  fetching from Uta-Net: {spec}")
            result = fetch_utanet(spec)
        else:
            raise ValueError(
                f"no parser for {spec}. Supported: a local file, a Uta-Net song "
                "URL, or a search term for LRCLIB.")
    else:
        log(f"  searching LRCLIB for {spec!r}")
        result = fetch_lrclib(spec)

    if not result.lines:
        raise ValueError(f"no lyrics found in {spec!r}")

    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(result.text, encoding="utf-8")
        log(f"  cached to {cache} -- edit that file to correct it")
    return result
