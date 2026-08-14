"""`aksal find` -- go from an anime name to a ready-to-run phase 1.

The point is that it feels like ONE process. Searching the web yourself and
then typing a phase1 command is a perfectly good workflow; a CLI that only
replaces the searching half is not worth using. So this ends by offering to run
phase 1 immediately, with everything it just gathered.

Every step is confirmable and nothing is guessed silently, because each of the
services involved fails in a way that looks like success:

    anime -> song      databases match the wrong series and say nothing
    song  -> track     YouTube's top hit for a song is often a MAD or a cover
    song  -> lyrics    LRCLIB offers a famous English song with the same title

The verification is what makes it usable unattended-ish: the reference track is
fingerprinted against the episode before it is accepted, and lyric hints are
checked against that track's duration.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog, fetch, lyrics as lyrics_mod, tools


@dataclass
class Found:
    theme: catalog.Theme | None = None
    lyrics_url: str = ""
    reference: Path | None = None
    synced: int = 0
    notes: list[str] = field(default_factory=list)


def ask(prompt: str, default: str = "") -> str:
    """Prompt, or fall back to the default when there is no terminal.

    `find` must remain usable from a script or a pipe: without a tty, every
    question takes its default rather than raising EOFError halfway through.
    """
    if not sys.stdin or not sys.stdin.isatty():
        return default
    try:
        got = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return got or default


def choose(items: list, render, prompt: str, auto: int | None = None,
           log=print):
    """Show a numbered menu and return the chosen item, or None to skip."""
    if not items:
        return None
    for i, it in enumerate(items, 1):
        log(f"   {i:2d}. {render(it)}")
    if auto is not None:
        pick = str(auto)
        log(f"  auto-selecting {pick}")
    else:
        pick = ask(f"  {prompt} [1-{len(items)}, or blank to skip]: ", "")
    if not pick.isdigit() or not (1 <= int(pick) <= len(items)):
        return None
    return items[int(pick) - 1]


def pick_theme(anime: str, kind: str | None, auto: int | None,
               log=print) -> catalog.Theme | None:
    log(f"\nsearching for {anime!r}")
    themes = catalog.search(anime, kind, log=log)
    if not themes:
        log("  no database knows this show. Pass --song and --artist directly.")
        return None

    log("\n  candidates (check the SERIES column -- a database that matched the "
        "wrong\n  show reports nothing unusual):")

    def render(t: catalog.Theme) -> str:
        score = catalog.series_score(anime, t.series)
        flag = " " if score >= 0.7 else "?"
        return (f"{flag} {score:4.2f}  {t.series[:30]:30s}  {t.describe()}"
                f"   [{t.source}]")

    return choose(themes, render, "which song?", auto, log=log)


def get_lyrics_url(theme: catalog.Theme, auto: bool, context: str = "",
                   log=print) -> str:
    log("\nlooking for lyrics on Uta-Net")
    urls = lyrics_mod.search_utanet(theme.title, theme.artist or context, log=log)
    for url in urls[:3]:
        try:
            res = lyrics_mod.fetch_utanet(url)
        except Exception:                              # noqa: BLE001
            continue
        log(f"  {url}")
        log(f"    {res.title!r} / {res.artist!r} -- {len(res.lines)} lines")
        if auto or ask("  use these lyrics? [Y/n]: ", "y").lower().startswith("y"):
            return url
    log("  search did not find it. Open this and paste the song URL:")
    log(f"    {lyrics_mod.utanet_search_url(theme.title, theme.artist)}")
    return ask("  Uta-Net song URL (blank to skip): ", "")


def get_reference(theme: catalog.Theme, video: Path, dest: Path,
                  search_start: float, search_dur: float,
                  auto: bool, context: str = "", log=print) -> Path | None:
    """Download and FINGERPRINT-VERIFY a reference track.

    Candidates are tried in order until one verifies. That loop is the whole
    value: the top YouTube hit for a song is very often a MAD or a cover, and
    only the fingerprint can tell.
    """
    log("\nlooking for the official track")
    try:
        query = fetch.normalise_query(theme.title, theme.artist, context)
        log(f"  searching: {query!r}")
        cands = fetch.plausible(fetch.search(query))
    except fetch.FetchError as exc:
        log(f"  {exc}")
        return None
    if not cands:
        log("  nothing plausible found; pass --reference FILE instead.")
        return None

    if not auto:
        chosen = choose(cands, lambda c: c.describe(),
                        "which to try first?", None, log=log)
        if chosen is not None:
            cands = [chosen] + [c for c in cands if c is not chosen]

    for cand in cands[:4]:
        log(f"\n  trying: {cand.describe()}")
        try:
            got = fetch.download_audio(cand.ident, dest)
        except fetch.FetchError as exc:
            log(f"  {exc}")
            continue
        if fetch.verify(got, video, search_start, search_dur, log=log):
            return got
        got.unlink(missing_ok=True)
    log("  no candidate matched the episode's audio.")
    return None


def run(anime: str, video: Path, out: Path, kind: str | None = None,
        song_start: float | None = None, duration: float = 92.0,
        auto: bool = False, pick: int | None = None, log=print) -> Found:
    found = Found()

    theme = pick_theme(anime, kind, pick, log=log)
    if theme is None:
        return found
    found.theme = theme
    log(f"\nselected: {theme.describe()}   (series: {theme.series})")

    found.lyrics_url = get_lyrics_url(theme, auto, context=anime, log=log)

    s_start = max((song_start or 0.0) - 120.0, 0.0)
    s_dur = duration + 240.0
    found.reference = get_reference(
        theme, video, out.parent / f"{out.name.split('.')[0]}.reference.m4a",
        s_start, s_dur, auto, context=anime, log=log)

    if found.reference is not None:
        dur = _duration_of(found.reference)
        hit = lyrics_mod.fetch_lrclib_verified(
            theme.query(), dur, theme.artist, log=log)
        if hit is not None and hit.timings:
            found.synced = len(hit.timings)
    return found


def _duration_of(path: Path) -> float | None:
    import subprocess

    try:
        out = subprocess.run(
            [tools.ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception:                                  # noqa: BLE001
        return None


def phase1_command(found: Found, video: Path, out: Path,
                   song_start: float | None) -> list[str]:
    cmd = ["aksal", "phase1", "--video", str(video), "-o", str(out)]
    cmd += ["--lyrics", found.lyrics_url or "LYRICS.txt"]
    if found.reference is not None:
        cmd += ["--reference", str(found.reference)]
    elif song_start is not None:
        cmd += ["--song-start", f"{int(song_start) // 60}:{int(song_start) % 60:02d}"]
    return cmd
