"""Finding ffmpeg, and getting it if it is missing.

Every audio path here shells out to ffmpeg, so without it nothing works at all --
and "ffmpeg is not recognised as an internal or external command" is a poor first
impression for someone who just unzipped a folder. So the tool asks, once, and
remembers the answer.

Three ways out, in the order they are offered:

    A  download a static build next to the executable
    B  point at an ffmpeg already on this machine
    C  stop, and add it to PATH yourself

The choice is stored beside the executable rather than in the registry or the
user profile, so a folder you move keeps working and a folder you delete leaves
nothing behind.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# BtbN publishes static Windows builds on GitHub with a predictable release
# asset name. The "essentials" variant carries the codecs needed here and is a
# fraction of the size of the full build.
FFMPEG_RELEASE_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
FFMPEG_ASSET_HINT = "win64-gpl"
YTDLP_RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_ASSET = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"

_resolved: dict[str, str] = {}


def _home() -> Path:
    """Where this installation keeps things it downloads."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.home() / ".aksal"


def _config_path() -> Path:
    return _home() / "aksal.config.json"


def _load_config() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        return {}


def _save_config(cfg: dict) -> None:
    try:
        _config_path().parent.mkdir(parents=True, exist_ok=True)
        _config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:                                   # noqa: BLE001
        pass                    # a read-only install still works, just not sticky


def _works(path: str) -> bool:
    try:
        subprocess.run([path, "-version"], capture_output=True, timeout=20)
        return True
    except Exception:                                   # noqa: BLE001
        return False


def find(name: str) -> str | None:
    """Locate `ffmpeg` or `ffprobe`: remembered, then bundled, then PATH."""
    if name in _resolved:
        return _resolved[name]

    exe = f"{name}.exe" if os.name == "nt" else name
    candidates: list[str] = []

    saved = _load_config().get(f"{name}_path")
    if saved:
        candidates.append(saved)
    candidates.append(str(_home() / "ffmpeg" / "bin" / exe))
    found = shutil.which(name)
    if found:
        candidates.append(found)

    for cand in candidates:
        if cand and Path(cand).exists() and _works(cand):
            _resolved[name] = cand
            return cand
    return None


def ffmpeg() -> str:
    return find("ffmpeg") or "ffmpeg"


def ffprobe() -> str:
    return find("ffprobe") or "ffprobe"


# --- acquiring it --------------------------------------------------------------

def download(log=print) -> bool:
    """Fetch a static build and unpack it beside the executable."""
    import urllib.request

    dest = _home() / "ffmpeg"
    try:
        log("  asking GitHub for the latest static build")
        req = urllib.request.Request(
            FFMPEG_RELEASE_API, headers={"User-Agent": "aksal", "Accept": "application/vnd.github+json"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        url = next((a["browser_download_url"] for a in data.get("assets", [])
                    if FFMPEG_ASSET_HINT in a["name"] and a["name"].endswith(".zip")), None)
        if not url:
            log("  no suitable build found in the latest release")
            return False

        dest.mkdir(parents=True, exist_ok=True)
        archive = dest / "ffmpeg.zip"
        log(f"  downloading {url.rsplit('/', 1)[-1]} (about 80 MB)")
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "aksal"}),
                timeout=600) as r, open(archive, "wb") as fh:
            shutil.copyfileobj(r, fh)

        log("  unpacking")
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                # The archive nests everything under a versioned directory;
                # only the binaries are wanted, flattened into ffmpeg/bin.
                if "/bin/" not in member or member.endswith("/"):
                    continue
                target = dest / "bin" / Path(member).name
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        archive.unlink(missing_ok=True)
    except Exception as exc:                            # noqa: BLE001
        log(f"  download failed: {type(exc).__name__}: {exc}")
        return False

    _resolved.clear()
    ok = find("ffmpeg") is not None and find("ffprobe") is not None
    log("  ffmpeg is ready" if ok else "  downloaded, but the binaries are not where expected")
    return ok


def use_path(folder: str, log=print) -> bool:
    """Accept a user-supplied ffmpeg location and remember it."""
    p = Path(folder.strip().strip('"'))
    exe = ".exe" if os.name == "nt" else ""
    for base in (p, p / "bin"):
        cand_ff, cand_fp = base / f"ffmpeg{exe}", base / f"ffprobe{exe}"
        if cand_ff.exists() and cand_fp.exists() and _works(str(cand_ff)):
            cfg = _load_config()
            cfg["ffmpeg_path"] = str(cand_ff)
            cfg["ffprobe_path"] = str(cand_fp)
            _save_config(cfg)
            _resolved.clear()
            log(f"  using {cand_ff}")
            return True
    # A path to the executable itself, rather than to its folder. `is_file` and
    # not `exists`: a directory satisfies `exists`, so a folder holding only
    # ffmpeg was accepted here and failed later on the first ffprobe call.
    if p.is_file() and _works(str(p)):
        sibling = p.with_name(f"ffprobe{exe}")
        if not sibling.is_file():
            log(f"  found ffmpeg but no ffprobe beside it at {p.parent}")
            return False
        cfg = _load_config()
        cfg["ffmpeg_path"] = str(p)
        cfg["ffprobe_path"] = str(sibling)
        _save_config(cfg)
        _resolved.clear()
        return True
    log(f"  no ffmpeg and ffprobe found at {p}")
    return False


MISSING = """ffmpeg was not found, and every audio step here needs it.

  A  download it now (about 80 MB, kept beside this tool)
  B  I already have it -- let me point at the folder
  C  stop; I will put it on PATH myself
"""


def ensure(log=print) -> None:
    """Make sure ffmpeg and ffprobe are usable, asking if they are not."""
    if find("ffmpeg") and find("ffprobe"):
        return

    log("\n" + MISSING)
    interactive = bool(sys.stdin and sys.stdin.isatty())
    if not interactive:
        raise SystemExit(
            "ffmpeg is required. Install it and put it on PATH, or run this "
            "once from a terminal to be offered a download.")

    while True:
        try:
            choice = input("  choose [A/B/C]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "c"
        if choice == "a":
            if download(log=log):
                return
            log("  that did not work; try B or C.")
        elif choice == "b":
            try:
                where = input("  folder containing ffmpeg: ").strip()
            except (EOFError, KeyboardInterrupt):
                where = ""
            if where and use_path(where, log=log):
                return
        elif choice == "c":
            raise SystemExit(
                "Add ffmpeg to PATH and run again.\n"
                "  https://www.gyan.dev/ffmpeg/builds/  or  winget install ffmpeg")


# --- yt-dlp ---------------------------------------------------------------
#
# Only `find` needs it, and only to fetch a reference track. It is a single
# self-contained executable, so the same offer that works for ffmpeg works here:
# download it, point at it, or go without.
#
# It is deliberately never auto-updated. yt-dlp breaks against YouTube often
# enough that updating itself mid-run would change results without anyone
# asking, which is a worse failure than a clear message saying it is stale.


def ytdlp() -> str | None:
    """The yt-dlp binary, if there is one."""
    if "yt-dlp" in _resolved:
        return _resolved["yt-dlp"]
    saved = _load_config().get("ytdlp_path")
    for cand in (saved, str(_home() / "yt-dlp" / YTDLP_ASSET),
                 shutil.which("yt-dlp")):
        if cand and Path(cand).exists() and _works(cand):
            _resolved["yt-dlp"] = cand
            return cand
    return None


def download_ytdlp(log=print) -> bool:
    import urllib.request

    dest = _home() / "yt-dlp"
    try:
        req = urllib.request.Request(
            YTDLP_RELEASE_API,
            headers={"User-Agent": "aksal", "Accept": "application/vnd.github+json"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        url = next((a["browser_download_url"] for a in data.get("assets", [])
                    if a["name"] == YTDLP_ASSET), None)
        if not url:
            log(f"  {YTDLP_ASSET} not in the latest release")
            return False
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / YTDLP_ASSET
        log(f"  downloading {YTDLP_ASSET} ({data.get('tag_name', '')})")
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "aksal"}),
                timeout=300) as r, open(target, "wb") as fh:
            shutil.copyfileobj(r, fh)
        if os.name != "nt":
            target.chmod(0o755)
    except Exception as exc:                            # noqa: BLE001
        log(f"  download failed: {type(exc).__name__}: {exc}")
        return False

    _resolved.pop("yt-dlp", None)
    ok = ytdlp() is not None
    log("  yt-dlp is ready" if ok else "  downloaded, but it does not run")
    return ok


YTDLP_MISSING = """yt-dlp was not found. `find` needs it to fetch the official track.

  A  download it now (a single file, kept beside this tool)
  B  I already have it -- let me point at it
  C  skip; I will supply --reference myself
"""


def ensure_ytdlp(log=print) -> bool:
    """Offer the same three ways out as ffmpeg. False means carry on without."""
    if ytdlp():
        return True

    log("\n" + YTDLP_MISSING)
    if not (sys.stdin and sys.stdin.isatty()):
        log("  not a terminal: continuing without yt-dlp")
        return False

    while True:
        try:
            choice = input("  choose [A/B/C]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if choice == "a":
            if download_ytdlp(log=log):
                return True
            log("  that did not work; try B or C.")
        elif choice == "b":
            try:
                where = input("  path to yt-dlp: ").strip().strip('"')
            except (EOFError, KeyboardInterrupt):
                return False
            p = Path(where)
            if p.is_file() and _works(str(p)):
                cfg = _load_config()
                cfg["ytdlp_path"] = str(p)
                _save_config(cfg)
                _resolved.pop("yt-dlp", None)
                return True
            log(f"  {p} does not look like a working yt-dlp")
        elif choice == "c":
            return False


# --- demucs ---------------------------------------------------------------
#
# Deliberately NOT offered as a download. ffmpeg and yt-dlp are single
# self-contained executables; demucs is a Python library with its own model
# weights, and there is nothing to fetch that a frozen application could import
# at runtime. Pretending otherwise would produce a confusing failure, so the
# message says plainly what the two real options are.


def demucs_available() -> bool:
    try:
        import demucs  # noqa: F401

        return True
    except Exception:                                   # noqa: BLE001
        return False


def require_demucs() -> None:
    if demucs_available():
        return
    raise SystemExit(
        "--separate-audio needs demucs, which is not installed.\n\n"
        "  Unlike ffmpeg and yt-dlp, demucs is a Python library rather than a\n"
        "  single executable, so it cannot be fetched into a packaged build at\n"
        "  runtime. Either:\n"
        "    * run AKSAL from source, with:  pip install aksal[separate]\n"
        "    * or leave it off -- measured across eight songs, separation is a\n"
        "      wash for syllable timing and costs about four times the runtime.")
