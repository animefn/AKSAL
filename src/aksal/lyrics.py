"""Lyrics input: a local file, a Uta-Net page, or an LRCLIB lookup.

`--lyrics` is deliberately polymorphic, because the whole point of the tool is
not doing tedious things by hand:

    --lyrics lyrics.txt                        a file you already have
    --lyrics https://www.uta-net.com/song/N/   a Uta-Net song page
    --lyrics https://lrclib.net/tracks/N        an LRCLIB track page
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
LRCLIB_TRACK_PATH = re.compile(r"^/tracks/([1-9]\d*)/?$")
LRCLIB_HOSTS = {"lrclib.net", "www.lrclib.net"}


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


def verify_lrclib(results: list[dict], duration: float | None,
                  artist: str = "", tolerance: float = 10.0) -> dict | None:
    """Pick an LRCLIB hit only when it is verifiably the right recording.

    LRCLIB is a bonus, never a foundation. Measured across the test set it held
    2 of 8 songs -- and, far worse, a loose query returns confident nonsense: a
    search for "Ray of light" offers Madonna, "Dream" offers an indie band,
    "TRUTH" offers twenty English songs. Every one carries synced lyrics and
    looks exactly like a hit.

    Two things separate the real match from the impostors:

      * the query must be PRECISE. An exact title, ideally with the artist,
        returns one correct hit or nothing at all. That is the caller's job.
      * the DURATION must match the track we already hold. Madonna's Ray of
        Light is 267s against our 242s; the correct Narrative is 198s against
        our 194s. Nothing else distinguishes them reliably.

    Without a duration to check against there is no verification available, so
    nothing is returned rather than something plausible.
    """
    usable = [r for r in results if r.get("syncedLyrics")
              and not r.get("instrumental")]
    if not usable or duration is None:
        return None

    # The artist is CORROBORATING EVIDENCE, not a gate. Requiring it to match
    # rejects correct hits, because name readings are genuinely ambiguous: the
    # analyser reads 月詠み as "tsukiyomi" and LRCLIB files it as "Tsukuyomi",
    # and no amount of string handling settles which reading of 月 is right.
    #
    # So a confirmed artist buys a loose duration tolerance, and an unconfirmed
    # one demands a tight match. Madonna's "Ray Of Light" is 8.4s from the
    # OUTER-TRIBE track and unconfirmed, so it fails; the correct "Narrative" is
    # 3.7s away and passes even when the artist cannot be confirmed.
    # Three states, not two. A supplied artist that DISAGREES is not the same as
    # no artist at all -- it is positive evidence against, and must reject
    # outright. Without that, searching "Dream" while knowing the artist is
    # OUTER-TRIBE still accepts a track by Dream Ami whose duration happens to
    # land nearby.
    wants = artist_keys(artist) if artist else set()

    scored = []
    for r in usable:
        got = _fold(r.get("artistName") or "")
        if wants:
            if not any(_artist_matches(w, got) for w in wants):
                continue                      # contradicted
            limit = tolerance                 # confirmed
        else:
            limit = tolerance * 0.5           # unknown: duration must be tight
        scored.append((abs((r.get("duration") or 0) - duration), limit, r))
    if not scored:
        return None
    scored.sort(key=lambda p: p[0])
    delta, limit, best = scored[0]
    return best if delta <= limit else None


def artist_keys(artist: str) -> set[str]:
    """Every spelling of an artist name worth comparing against.

    LRCLIB stores Japanese artists romanised far more often than not -- 月詠み
    is filed as "Tsukuyomi" -- so comparing the Japanese name alone rejects the
    correct hit. The tool already knows how to read Japanese and romanise it, so
    it romanises the name and compares both forms.
    """
    keys = {_fold(artist)}
    if any("぀" <= c <= "ヿ" or "一" <= c <= "鿿"
           for c in artist):
        try:
            from . import moras, readings, romaji

            kana = readings.analyse(readings.normalise_surface(artist))
            keys.add(_fold("".join(romaji.line(moras.split(kana)))))
        except Exception:               # analyser missing or unhappy: skip
            pass
    return {k for k in keys if k}


def _artist_matches(want: str, got: str) -> bool:
    """Folded artist names, either containing the other.

    Containment rather than equality because the databases disagree about
    decoration: "OUTER-TRIBE" against "OUTER TRIBE", a featured artist appended
    on one side only, a label suffix.
    """
    if not want or not got:
        return False
    if want in got or got in want:
        return True
    # Near-misses are the norm, not the exception: a romanised Japanese name
    # can differ by one vowel purely because the reading of a kanji is
    # ambiguous (tsukiyomi / tsukuyomi).
    import difflib

    return difflib.SequenceMatcher(None, want, got).ratio() >= 0.82


def match_timings(lines: list[str], timings: list[tuple[float, str]],
                  ) -> dict[int, float]:
    """Map lyric line index -> start time, but ONLY where the text agrees.

    LRCLIB and Uta-Net do not agree about where lines break, so pairing them by
    index would put one sheet's timing on another sheet's words and be wrong
    from the first mismatch onward. Matching on normalised text instead means a
    disagreement costs that line its hint and nothing more.

    Matching is monotonic: a hint may only be taken from a timing later than the
    previous line's, so a repeated refrain cannot pull a line backwards.
    """
    out: dict[int, float] = {}
    cursor = 0
    keyed = [(t, _fold(text)) for t, text in timings]
    for i, line in enumerate(lines):
        key = _fold(line)
        if not key:
            continue
        for j in range(cursor, len(keyed)):
            if keyed[j][1] == key:
                out[i] = keyed[j][0]
                cursor = j + 1
                break
    return out


def _fold(text: str) -> str:
    """Comparison key: case, spacing and punctuation carry no meaning here."""
    import unicodedata

    s = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿]", "", s)


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


DDG_ENDPOINTS = ("https://html.duckduckgo.com/html/?q=",
                 "https://lite.duckduckgo.com/lite/?q=")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SONG_IN_URL = re.compile(r"uta-net\.com(?:%2F|/)song(?:%2F|/)(\d+)", re.I)


def parse_song_ids(page: str) -> list[str]:
    """Uta-Net song ids in the order a search engine ranked them."""
    out: list[str] = []
    for m in SONG_IN_URL.finditer(page):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def search_utanet(title: str, artist: str = "", log=print) -> list[str]:
    """Uta-Net song URLs for a title, via a site-restricted web search.

    Uta-Net has no API, and its own /search/ endpoint is unusable from here --
    404 from Europe, 403 through a VPN, whatever the headers. A site-restricted
    web search reaches the same pages and is what a human does anyway.

    DuckDuckGo is used because it needs no API key. Two endpoints are tried, and
    a total failure returns an empty list rather than raising: this is a
    convenience, and `--lyrics <uta-net URL>` always remains available.
    """
    query = "site:uta-net.com " + " ".join(x for x in (title, artist) if x)
    for base in DDG_ENDPOINTS:
        try:
            req = urllib.request.Request(
                base + urllib.parse.quote(query), headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                page = r.read().decode("utf-8", "replace")
        except Exception:                                # noqa: BLE001
            continue
        ids = parse_song_ids(page)
        if ids:
            return [f"https://www.uta-net.com/song/{i}/" for i in ids]
    log("  no Uta-Net page found by search; open the search URL by hand")
    return []


def utanet_search_url(title: str, artist: str = "") -> str:
    """A Uta-Net search URL for a human to open.

    Deliberately NOT scraped. Uta-Net has no API, and its /search/ endpoint
    returns 404 to every request this tool can make, whatever the headers -- so
    a scraper here would be fragile at best and is impossible at worst. Song
    PAGES fetch fine, so the flow is: open this, click the song, paste the URL.
    """
    q = " ".join(x for x in (title, artist) if x)
    return "https://www.uta-net.com/search/?Aselect=2&Keyword=" + urllib.parse.quote(q)


def fetch_lrclib_verified(query: str, duration: float | None, artist: str = "",
                          log=print) -> LyricsResult | None:
    """LRCLIB, but only when the hit can be verified against a known duration.

    Returns None rather than a guess. See `verify_lrclib` for why that matters.
    """
    try:
        results = json.loads(
            _get("https://lrclib.net/api/search?"
                 + urllib.parse.urlencode({"q": query})))
    except Exception as exc:                            # noqa: BLE001
        log(f"  LRCLIB unavailable ({type(exc).__name__})")
        return None
    if not isinstance(results, list) or not results:
        return None

    best = verify_lrclib(results, duration, artist)
    if best is None:
        synced = sum(1 for r in results if r.get("syncedLyrics"))
        log(f"  LRCLIB: {len(results)} hit(s), {synced} synced, "
            "none matching this track's duration -- ignoring")
        return None

    lines, timings = parse_lrc(best.get("syncedLyrics") or "")
    log(f"  LRCLIB: {best.get('trackName')} / {best.get('artistName')} "
        f"({best.get('duration')}s) -- {len(timings)} synced line(s)")
    return LyricsResult(lines=clean_lines("\n".join(lines)), source="lrclib",
                        title=str(best.get("trackName") or ""),
                        artist=str(best.get("artistName") or ""),
                        timings=timings)


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

    return _lrclib_result(best)


def _lrclib_result(track: dict) -> LyricsResult:
    """Turn one validated LRCLIB API track into AKSAL's common result."""
    if track.get("instrumental"):
        raise ValueError("the selected LRCLIB track is instrumental")
    body = track.get("syncedLyrics") or track.get("plainLyrics") or ""
    if not isinstance(body, str) or not body.strip():
        raise ValueError("the selected LRCLIB track has no usable lyrics")
    lines, timings = parse_lrc(body)
    return LyricsResult(lines=clean_lines("\n".join(lines)), source="lrclib",
                        title=str(track.get("trackName") or ""),
                        artist=str(track.get("artistName") or ""),
                        timings=timings)


def lrclib_track_id(url: str) -> str | None:
    """Return a direct LRCLIB page's numeric track id, or None for another host.

    A URL on LRCLIB itself is considered intentional input, so a malformed
    track path raises a specific error instead of falling through to the generic
    unsupported-URL message.
    """
    parsed = urllib.parse.urlsplit(url)
    if (parsed.hostname or "").lower() not in LRCLIB_HOSTS:
        return None
    match = LRCLIB_TRACK_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError(
            f"invalid LRCLIB track URL: {url}. Expected "
            "https://lrclib.net/tracks/<numeric-id>.")
    return match.group(1)


def fetch_lrclib_track(track_id: str) -> LyricsResult:
    """Fetch one exact track through LRCLIB's official id endpoint."""
    if not re.fullmatch(r"[1-9]\d*", str(track_id)):
        raise ValueError(f"invalid LRCLIB track id: {track_id!r}")
    try:
        track = json.loads(_get(f"https://lrclib.net/api/get/{track_id}"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "unexpected non-JSON response from LRCLIB track endpoint") from exc
    if not isinstance(track, dict):
        raise ValueError("unexpected response from LRCLIB track endpoint")
    return _lrclib_result(track)


# --- dispatch -----------------------------------------------------------------

def resolve(spec: str, cache: Path | None = None, refresh: bool = False,
            log=print) -> LyricsResult:
    """Resolve a file, Uta-Net/LRCLIB track URL, or LRCLIB search."""
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
        elif (track_id := lrclib_track_id(spec)) is not None:
            log(f"  fetching LRCLIB track {track_id}")
            result = fetch_lrclib_track(track_id)
        else:
            raise ValueError(
                f"no parser for {spec}. Supported: a local file, a Uta-Net song "
                "URL, an LRCLIB track URL, or a search term for LRCLIB.")
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
