"""Get the official track, and prove it is the right one.

Downloading a song by name is the easy half. The hard half is that a search for
"<artist> <title> full" returns covers, nightcore edits, MADs, live versions and
TV sizes labelled "full" -- and every one of them plays back as a plausible
song. A wrong reference does not make phase 1 fail; it makes phase 1 produce
confident nonsense, which is worse.

So nothing downloaded here is used until it has been **verified against the
episode by fingerprint**. That check already exists for locating the song, and
it answers this question for free: if no chunk of the candidate matches the
episode's audio, it is not the track this episode uses.

yt-dlp is an optional dependency, deliberately. It breaks against YouTube
regularly and needs updating often; auto-updating it mid-run would change
behaviour silently, so a failure is reported with the command to run instead.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import tools

MIN_SUPPORT = 400          # a real match scores thousands; noise scores tens
MIN_COVER_SEC = 20.0       # a TV size is ~90s, so 20s of agreement is plenty


@dataclass
class Candidate:
    ident: str = ""
    title: str = ""
    uploader: str = ""
    duration: float = 0.0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.ident}"

    def describe(self) -> str:
        mins = f"{int(self.duration) // 60}:{int(self.duration) % 60:02d}"
        who = f" [{self.uploader}]" if self.uploader else ""
        return f"{mins:>6s}  {self.title[:64]}{who}"


class FetchError(RuntimeError):
    pass


def have_ytdlp() -> bool:
    return tools.ytdlp() is not None


def require_ytdlp() -> str:
    """Return the resolved executable, offering AKSAL's downloader once."""
    executable = tools.ytdlp()
    if executable is None and tools.ensure_ytdlp():
        executable = tools.ytdlp()
    if executable is None:
        raise FetchError(
            "yt-dlp was not found.\n"
            "  It is an optional dependency, used only to fetch a reference "
            "track.\n"
            "    pip install -U yt-dlp\n"
            "  Or download the song yourself and pass --reference FILE.")
    return executable


def _run(args: list[str], timeout: float = 300) -> str:
    proc = subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = err[-1] if err else "no output"
        if "403" in tail or "429" in tail or "unable to download" in tail.lower():
            raise FetchError(
                f"YouTube refused the request: {tail}\n"
                "  This is usually yt-dlp being out of date. Update it:\n"
                "    pip install -U yt-dlp\n"
                "  (It is deliberately NOT auto-updated -- a dependency that "
                "changes itself mid-run changes results silently.)")
        raise FetchError(f"yt-dlp failed: {tail}")
    return proc.stdout


def parse_search(stdout: str) -> list[Candidate]:
    """One JSON object per line, as `--print '%(...)j'` emits them."""
    out: list[Candidate] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(Candidate(
            ident=str(d.get("id") or ""),
            title=str(d.get("title") or ""),
            uploader=str(d.get("uploader") or d.get("channel") or ""),
            duration=float(d.get("duration") or 0.0)))
    return [c for c in out if c.ident]


def plausible(candidates: list[Candidate], want: float | None = None,
              lo: float = 60.0, hi: float = 600.0) -> list[Candidate]:
    """Drop what cannot be a full single: clips, concerts, album uploads.

    Not a substitute for the fingerprint check -- a nightcore edit is exactly
    the right length -- just a way to avoid downloading 40 minutes of concert.
    """
    keep = [c for c in candidates if lo <= c.duration <= hi]
    if want:
        keep.sort(key=lambda c: abs(c.duration - want))
    return keep


def search(query: str, limit: int = 8) -> list[Candidate]:
    executable = require_ytdlp()
    out = _run([executable, f"ytsearch{limit}:{query}", "--flat-playlist",
                "--no-warnings", "--print",
                '{"id":%(id)j,"title":%(title)j,"uploader":%(uploader)j,'
                '"duration":%(duration)j}'], timeout=120)
    return parse_search(out)


def download_audio(ident_or_url: str, dest: Path) -> Path:
    """Best available audio, converted to m4a at `dest`.

    Paths are built by string, never with `Path.with_suffix`. AKSAL's filenames
    carry several dots -- `OP.lines.reference.m4a` -- and `with_suffix` treats
    `.reference` as the suffix, so it silently produces `OP.lines.m4a` and every
    download then appears to vanish.
    """
    executable = require_ytdlp()
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = str(dest)
    if base.lower().endswith(".m4a"):
        base = base[:-4]
    _run([executable, "-f", "bestaudio", "-x", "--audio-format", "m4a",
          "--audio-quality", "0", "--no-warnings",
          "-o", base + ".%(ext)s", ident_or_url], timeout=600)
    got = Path(base + ".m4a")
    if not got.exists():
        raise FetchError(f"yt-dlp reported success but {got.name} is missing")
    return got


def verify(reference: Path, video: Path, search_start: float = 0.0,
           search_dur: float | None = 420.0, log=print) -> bool:
    """Is this actually the track this episode uses?

    The whole point of the module. A cover, a remix or the wrong song entirely
    downloads and plays perfectly well; only the fingerprint distinguishes it
    from the real thing, and it does so decisively -- a genuine match scores
    thousands of hashes, an unrelated track scores tens.
    """
    from . import locate

    try:
        segments = locate.locate_by_fingerprint(
            reference, video, search_start, search_dur, log=lambda *a, **k: None)
    except Exception as exc:                          # noqa: BLE001
        log(f"  could not verify ({type(exc).__name__})")
        return False

    if not segments:
        log("  REJECTED: no part of this track appears in the episode")
        return False
    best = max(s.support for s in segments)
    covered = sum(s.ep_end - s.ep_start for s in segments)
    if best < MIN_SUPPORT or covered < MIN_COVER_SEC:
        log(f"  REJECTED: only {covered:.0f}s matched, best support {best} "
            "-- a cover or a different mix, not this episode's track")
        return False
    log(f"  verified: {covered:.0f}s of this track is in the episode "
        f"(support {best})")
    return True


def normalise_query(title: str, artist: str, context: str = "") -> str:
    """A search string precise enough to find the right recording.

    `context` -- the anime name -- is used when the artist is unknown, which is
    common: AnimeThemes often has the song title and no performer. Searching
    YouTube for a bare "TRUTH" returns a rapper and a news clip; "Cross Fight
    B-Daman TRUTH" returns the anime's opening.
    """
    bits = [b for b in (artist, title) if b]
    if not artist and context:
        bits.insert(0, context)
    return re.sub(r"\s+", " ", " ".join(bits)).strip()
