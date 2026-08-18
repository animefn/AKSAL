"""Find and, where possible, acquire AKSAL's external command-line tools.

Every audio path here shells out to ffmpeg, so without it nothing works at all --
and "ffmpeg is not recognised as an internal or external command" is a poor first
impression for someone who just unzipped a folder. So the tool asks, once, and
remembers the answer.

Three ways out, in the order they are offered where a native download exists:

    A  download a static build into AKSAL's user-data directory
    B  point at an ffmpeg already on this machine
    C  stop, and add it to PATH yourself

The executable may live in a read-only location such as /Applications or
/usr/local/bin, so configuration and downloaded helper tools use per-user
storage. Packaged builds keep model downloads in a visible ``models`` directory
beside the executable whenever that directory is writable. ``AKSAL_HOME``,
``AKSAL_CACHE_HOME``, and ``AKSAL_MODEL_HOME`` override their respective
defaults for portable or centrally managed installations.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

# BtbN publishes matching static Windows and Linux builds.  macOS is omitted
# because that release has no macOS asset; offering a Windows-looking download
# there is worse than giving the correct Homebrew instruction.
FFMPEG_RELEASE_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
YTDLP_RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"

_resolved: dict[str, str] = {}


def _home() -> Path:
    """Writable per-user data: configuration and downloaded executables."""
    override = os.environ.get("AKSAL_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "AKSAL" if base else Path.home() / ".aksal"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AKSAL"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base).expanduser() if base else
            Path.home() / ".local" / "share") / "aksal"


def home() -> Path:
    """Public alias: other modules keep user-editable files here too."""
    return _home()


def cache_home() -> Path:
    """Writable per-user cache for temporary, reproducible downloads."""
    override = os.environ.get("AKSAL_CACHE_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) / "AKSAL" if base else Path.home() / ".aksal"
        return root / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "AKSAL"
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base).expanduser() if base else
            Path.home() / ".cache") / "aksal"


def _writable_directory(path: Path) -> bool:
    """Create *path* and verify it accepts files without leaving a probe."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".aksal-write-", dir=path):
            pass
        return True
    except OSError:
        return False


def configure_model_home(*, log=print) -> Path | None:
    """Select Hugging Face storage for a frozen, portable AKSAL build.

    A caller-supplied ``HF_HOME`` remains authoritative. Packaged builds then
    prefer ``AKSAL_MODEL_HOME`` or a visible ``models`` directory beside the
    executable. Only a genuinely read-only installation falls back to the
    native user cache. Source installs retain Hugging Face's normal defaults.
    """
    explicit_hf = os.environ.get("HF_HOME")
    if explicit_hf:
        selected = Path(explicit_hf).expanduser()
        os.environ.setdefault("TORCH_HOME", str(selected / "torch"))
        return selected
    if not getattr(sys, "frozen", False):
        return None

    override = os.environ.get("AKSAL_MODEL_HOME")
    preferred = (Path(override).expanduser() if override else
                 Path(sys.executable).resolve().parent / "models")
    if _writable_directory(preferred):
        os.environ["HF_HOME"] = str(preferred)
        os.environ.setdefault("TORCH_HOME", str(preferred / "torch"))
        return preferred

    fallback = cache_home() / "models"
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(fallback)
    os.environ.setdefault("TORCH_HOME", str(fallback / "torch"))
    log(f"AKSAL cannot write to {preferred}; models will be stored in "
        f"{fallback} instead.")
    return fallback


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


def _works(path: str, version_arg: str = "-version") -> bool:
    try:
        proc = subprocess.run(
            [path, version_arg], capture_output=True, timeout=20)
        return proc.returncode == 0
    except Exception:                                   # noqa: BLE001
        return False


def _architecture() -> str | None:
    machine = platform.machine().lower().replace("_", "-")
    if machine in {"amd64", "x86-64", "x64"}:
        return "x64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return None


def ffmpeg_asset() -> str | None:
    """Exact BtbN asset for this host, or None when none is published."""
    arch = _architecture()
    if not arch:
        return None
    if sys.platform == "win32":
        flavor = "win64" if arch == "x64" else "winarm64"
        return f"ffmpeg-master-latest-{flavor}-lgpl.zip"
    if sys.platform.startswith("linux"):
        flavor = "linux64" if arch == "x64" else "linuxarm64"
        return f"ffmpeg-master-latest-{flavor}-lgpl.tar.xz"
    return None


def ytdlp_asset() -> str | None:
    """Official yt-dlp standalone asset for this OS and architecture."""
    arch = _architecture()
    if not arch:
        return None
    if sys.platform == "win32":
        return "yt-dlp.exe" if arch == "x64" else "yt-dlp_arm64.exe"
    if sys.platform.startswith("linux"):
        return "yt-dlp_linux" if arch == "x64" else "yt-dlp_linux_aarch64"
    if sys.platform == "darwin":
        return "yt-dlp_macos"
    return None


def _ytdlp_filename() -> str:
    return "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"


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
    """Fetch the native static FFmpeg build into writable user data."""
    import urllib.request

    asset = ffmpeg_asset()
    if not asset:
        log("  no automatic FFmpeg download is available for this platform")
        log("  " + _ffmpeg_install_hint())
        return False
    dest = _home() / "ffmpeg"
    archive = dest / asset
    try:
        log("  asking GitHub for the latest static build")
        req = urllib.request.Request(
            FFMPEG_RELEASE_API, headers={"User-Agent": "aksal", "Accept": "application/vnd.github+json"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        url = next((a["browser_download_url"] for a in data.get("assets", [])
                    if a.get("name") == asset), None)
        if not url:
            log("  no suitable build found in the latest release")
            return False

        dest.mkdir(parents=True, exist_ok=True)
        log(f"  downloading {asset}")
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "aksal"}),
                timeout=600) as r, open(archive, "wb") as fh:
            shutil.copyfileobj(r, fh)

        log("  unpacking")
        shutil.rmtree(dest / "bin", ignore_errors=True)
        wanted = {"ffmpeg.exe", "ffprobe.exe"} if sys.platform == "win32" \
            else {"ffmpeg", "ffprobe"}
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle:
                members = ((name, bundle.open(name)) for name in bundle.namelist()
                           if "/bin/" in name and Path(name).name in wanted)
                for name, source in members:
                    with source:
                        _write_binary(source, dest / "bin" / Path(name).name)
        else:
            with tarfile.open(archive, mode="r:xz") as bundle:
                for member in bundle.getmembers():
                    if (not member.isfile() or "/bin/" not in member.name or
                            Path(member.name).name not in wanted):
                        continue
                    source = bundle.extractfile(member)
                    if source is not None:
                        with source:
                            _write_binary(
                                source, dest / "bin" / Path(member.name).name)
    except Exception as exc:                            # noqa: BLE001
        log(f"  download failed: {type(exc).__name__}: {exc}")
        return False
    finally:
        archive.unlink(missing_ok=True)

    _resolved.clear()
    ok = find("ffmpeg") is not None and find("ffprobe") is not None
    log("  ffmpeg is ready" if ok else "  downloaded, but the binaries are not where expected")
    return ok


def _write_binary(source, target: Path) -> None:
    """Flatten one trusted named binary out of a release archive."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as output:
        shutil.copyfileobj(source, output)
    if os.name != "nt":
        target.chmod(0o755)


def use_path(folder: str, log=print) -> bool:
    """Accept a user-supplied ffmpeg location and remember it."""
    p = Path(folder.strip().strip('"'))
    exe = ".exe" if os.name == "nt" else ""
    for base in (p, p / "bin"):
        cand_ff, cand_fp = base / f"ffmpeg{exe}", base / f"ffprobe{exe}"
        if (cand_ff.exists() and cand_fp.exists() and _works(str(cand_ff)) and
                _works(str(cand_fp))):
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
        if not sibling.is_file() or not _works(str(sibling)):
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


def _ffmpeg_install_hint() -> str:
    if sys.platform == "win32":
        return "Install with `winget install Gyan.FFmpeg`, or add FFmpeg to PATH."
    if sys.platform == "darwin":
        return "Install with `brew install ffmpeg`, or add FFmpeg to PATH."
    return ("Install FFmpeg with your package manager (for example "
            "`sudo apt install ffmpeg`), or add it to PATH.")


def _missing_message() -> str:
    options = []
    if ffmpeg_asset():
        options.append("  A  download a native static build now")
    options += ["  B  I already have it -- let me point at the folder",
                "  C  stop; I will put it on PATH myself"]
    return ("ffmpeg was not found, and every audio step here needs it.\n\n" +
            "\n".join(options))


def ensure(log=print) -> None:
    """Make sure ffmpeg and ffprobe are usable, asking if they are not."""
    if find("ffmpeg") and find("ffprobe"):
        return

    log("\n" + _missing_message())
    interactive = bool(sys.stdin and sys.stdin.isatty())
    if not interactive:
        raise SystemExit(
            "ffmpeg is required. " + _ffmpeg_install_hint())

    while True:
        try:
            choice = input("  choose [A/B/C]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "c"
        if choice == "a" and ffmpeg_asset():
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
            raise SystemExit(_ffmpeg_install_hint())


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
    for cand in (saved, str(_home() / "yt-dlp" / _ytdlp_filename()),
                 shutil.which("yt-dlp")):
        if cand and Path(cand).exists() and _works(cand, "--version"):
            _resolved["yt-dlp"] = cand
            return cand
    return None


def download_ytdlp(log=print) -> bool:
    import urllib.request

    asset = ytdlp_asset()
    if not asset:
        log("  no official standalone yt-dlp build supports this platform")
        return False
    dest = _home() / "yt-dlp"
    try:
        req = urllib.request.Request(
            YTDLP_RELEASE_API,
            headers={"User-Agent": "aksal", "Accept": "application/vnd.github+json"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        url = next((a["browser_download_url"] for a in data.get("assets", [])
                    if a["name"] == asset), None)
        if not url:
            log(f"  {asset} not in the latest release")
            return False
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / _ytdlp_filename()
        temporary = target.with_name(target.name + ".download")
        log(f"  downloading {asset} ({data.get('tag_name', '')})")
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "aksal"}),
                timeout=300) as r, open(temporary, "wb") as fh:
            shutil.copyfileobj(r, fh)
        if os.name != "nt":
            temporary.chmod(0o755)
        temporary.replace(target)
    except Exception as exc:                            # noqa: BLE001
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)
        log(f"  download failed: {type(exc).__name__}: {exc}")
        return False

    _resolved.pop("yt-dlp", None)
    ok = ytdlp() is not None
    log("  yt-dlp is ready" if ok else "  downloaded, but it does not run")
    return ok


YTDLP_MISSING = """yt-dlp was not found. Fetching a reference URL needs it.

  A  download the native standalone program now
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
            if p.is_file() and _works(str(p), "--version"):
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
    import importlib.util

    try:
        return importlib.util.find_spec("demucs") is not None
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
