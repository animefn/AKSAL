"""Check GitHub releases and safely update a frozen AKSAL installation.

AKSAL ships as a PyInstaller ``onedir`` bundle.  The running process cannot
replace DLLs loaded from ``_internal``, so an update is downloaded and checked
first, then handed to a tiny native-system helper.  The helper waits for this
process to exit, moves the old top-level bundle entries aside, installs the new
ones, starts the new executable as a smoke test, and rolls back on any failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import __version__
from .tools import cache_home, home

RELEASE_API = "https://api.github.com/repos/animefn/AKSAL/releases/latest"
RELEASES_URL = "https://github.com/animefn/AKSAL/releases/latest"
CHECK_INTERVAL = 24 * 60 * 60
_TAG_RE = re.compile(r"^v?(\d+(?:\.\d+){1,3})$")


@dataclass(frozen=True)
class Release:
    tag: str
    version: tuple[int, ...]
    page_url: str
    assets: tuple[dict, ...]


def _headers() -> dict[str, str]:
    return {
        "User-Agent": f"AKSAL/{__version__}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def version_tuple(value: str) -> tuple[int, ...] | None:
    """Parse stable numeric release tags without guessing about prereleases."""
    match = _TAG_RE.fullmatch(value.strip())
    if not match:
        return None
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (4 - len(parts))


def fetch_latest(timeout: float = 10.0) -> Release:
    request = urllib.request.Request(RELEASE_API, headers=_headers())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValueError("GitHub returned an invalid release response")
    tag = str(data.get("tag_name", ""))
    parsed = version_tuple(tag)
    if parsed is None:
        raise ValueError(f"latest release has an unsupported tag: {tag!r}")
    return Release(
        tag=tag,
        version=parsed,
        page_url=str(data.get("html_url") or RELEASES_URL),
        assets=tuple(asset for asset in data["assets"]
                     if isinstance(asset, dict)),
    )


def is_newer(release: Release, current: str = __version__) -> bool:
    parsed = version_tuple(current)
    return parsed is not None and release.version > parsed


def _check_cache_path() -> Path:
    return home() / "update-check.json"


def _read_cached_release() -> tuple[float, Release] | None:
    try:
        data = json.loads(_check_cache_path().read_text(encoding="utf-8"))
        parsed = version_tuple(str(data["tag"]))
        if parsed is None:
            return None
        return float(data["checked_at"]), Release(
            str(data["tag"]), parsed,
            str(data.get("page_url") or RELEASES_URL),
            tuple({"name": str(name)}
                  for name in data.get("asset_names", [])),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _cache_release(release: Release) -> None:
    path = _check_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "checked_at": time.time(),
            "tag": release.tag,
            "page_url": release.page_url,
            "asset_names": [asset.get("name") for asset in release.assets
                            if asset.get("name")],
        }, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


def notify_if_available(log=print) -> None:
    """Print at most one inexpensive update notice per day.

    Network failures are deliberately silent here: an update notification must
    never turn a successful alignment into a failed command.  Explicit
    ``aksal update`` reports those failures instead.
    """
    if os.environ.get("AKSAL_NO_UPDATE_CHECK"):
        return
    cached = _read_cached_release()
    now = time.time()
    if cached and now - cached[0] < CHECK_INTERVAL:
        release = cached[1]
    else:
        try:
            release = fetch_latest(timeout=3.0)
        except Exception:  # noqa: BLE001 - optional best-effort notification
            return
        _cache_release(release)
    if is_newer(release):
        log(f"\nAKSAL {release.tag} is available (installed: v{__version__}).")
        try:
            compatible_asset = select_asset(release)
        except RuntimeError:
            compatible_asset = None
        if getattr(sys, "frozen", False) and compatible_asset:
            log("  Run `aksal update` to install it.")
        else:
            log(f"  {release.page_url}")


def platform_asset_suffix() -> str | None:
    machine = platform.machine().lower().replace("_", "-")
    architecture = (
        "x64" if machine in {"amd64", "x86-64", "x64"}
        else "arm64" if machine in {"arm64", "aarch64"}
        else None
    )
    if architecture is None:
        return None
    if sys.platform == "win32":
        return f"-windows-{architecture}.zip"
    if sys.platform.startswith("linux"):
        return f"-linux-{architecture}.tar.gz"
    if sys.platform == "darwin":
        return f"-macos-{architecture}.tar.gz"
    return None


def select_asset(release: Release) -> dict:
    suffix = platform_asset_suffix()
    if suffix is None:
        raise RuntimeError("no AKSAL release build supports this platform")
    matches = [asset for asset in release.assets
               if str(asset.get("name", "")).endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(
            f"release {release.tag} has no unique {suffix[1:]} archive")
    return matches[0]


def _download(url: str, target: Path, *, timeout: float = 600.0) -> None:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with open(target, "wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)


def _expected_digest(release: Release, asset: dict,
                     work: Path) -> str:
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:") and len(digest) == 71:
        return digest[7:].lower()

    asset_name = str(asset.get("name", ""))
    sidecar_name = asset_name + ".sha256"
    sidecar = next((candidate for candidate in release.assets
                    if candidate.get("name") == sidecar_name), None)
    if sidecar is None:
        raise RuntimeError(
            f"release asset {asset_name} has no SHA-256 digest; refusing an "
            "unverified executable update")
    sidecar_path = work / sidecar_name
    _download(str(sidecar["browser_download_url"]), sidecar_path, timeout=60)
    token = sidecar_path.read_text(encoding="ascii").strip().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise RuntimeError(f"invalid checksum file for {asset_name}")
    return token


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    drive = bool(path.parts and re.fullmatch(r"[A-Za-z]:", path.parts[0]))
    if path.is_absolute() or drive or ".." in path.parts or not path.parts:
        raise RuntimeError(f"unsafe path in release archive: {name!r}")
    return path


def _extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                relative = _safe_member(info.filename)
                target = destination.joinpath(*relative.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                # Refuse Unix symlinks carried inside a zip.
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError(
                        f"links are not allowed in release archive: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)
                mode = (info.external_attr >> 16) & 0o777
                if mode and os.name != "nt":
                    target.chmod(mode)
        return

    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, mode="r:gz") as bundle:
            for member in bundle.getmembers():
                relative = _safe_member(member.name)
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise RuntimeError(
                        f"links are not allowed in release archive: {member.name}")
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError(f"cannot read archive member: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)
                if os.name != "nt":
                    target.chmod(member.mode & 0o777)
        return
    raise RuntimeError(f"unsupported release archive: {archive.name}")


def _payload_root(extracted: Path) -> Path:
    executable = "aksal.exe" if sys.platform == "win32" else "aksal"
    candidates = [extracted]
    entries = list(extracted.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        candidates.append(entries[0])
    for candidate in candidates:
        if ((candidate / executable).is_file() and
                (candidate / "_internal").is_dir()):
            return candidate
    raise RuntimeError(
        f"release archive is not an AKSAL onedir bundle ({executable} and "
        "_internal are required)")


def _install_root() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError(
            "automatic update is available only in a packaged AKSAL release; "
            "update this source/pip installation with its package manager")
    root = Path(sys.executable).resolve().parent
    if not (root / "_internal").is_dir():
        raise RuntimeError(
            "this is not an AKSAL onedir installation; download the latest "
            f"archive from {RELEASES_URL}")
    return root


def _write_manifest(payload: Path, work: Path) -> Path:
    # ``models`` is mutable user data. A release contains its explanatory
    # README, but an update must never replace already-downloaded weights.
    names = sorted(entry.name for entry in payload.iterdir()
                   if entry.name != "models")
    if not names or any("\n" in name or "\r" in name for name in names):
        raise RuntimeError("release archive has invalid top-level entries")
    manifest = work / "manifest.txt"
    manifest.write_text("".join(name + "\n" for name in names),
                        encoding="utf-8")
    return manifest


_WINDOWS_HELPER = r'''param(
  [int]$ParentPid,
  [string]$InstallDir,
  [string]$StagedDir,
  [string]$BackupDir,
  [string]$Manifest,
  [string]$Executable,
  [string]$LogFile
)
$ErrorActionPreference = "Stop"
function Log([string]$Message) {
  $line = "$(Get-Date -Format o) $Message"
  Write-Host $Message
  try { Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8 } catch {}
}
try { Wait-Process -Id $ParentPid -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 500
$names = Get-Content -LiteralPath $Manifest -Encoding UTF8
$installed = New-Object System.Collections.Generic.List[string]
try {
  New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
  foreach ($name in $names) {
    $old = Join-Path $InstallDir $name
    $saved = Join-Path $BackupDir $name
    if (Test-Path -LiteralPath $old) {
      Move-Item -LiteralPath $old -Destination $saved -Force
    }
  }
  foreach ($name in $names) {
    $source = Join-Path $StagedDir $name
    $target = Join-Path $InstallDir $name
    $installed.Add($name)
    Move-Item -LiteralPath $source -Destination $target -Force
  }
  $newExe = Join-Path $InstallDir $Executable
  & $newExe --version | ForEach-Object { Log $_ }
  if ($LASTEXITCODE -ne 0) { throw "the updated executable failed its startup check" }
  Log "AKSAL update installed successfully."
  try { Remove-Item -LiteralPath $BackupDir -Recurse -Force } catch {
    Log "The update succeeded, but the old backup could not be removed: $BackupDir"
  }
} catch {
  Log "AKSAL update failed; restoring the previous installation: $($_.Exception.Message)"
  foreach ($name in $installed) {
    $target = Join-Path $InstallDir $name
    if (Test-Path -LiteralPath $target) {
      Remove-Item -LiteralPath $target -Recurse -Force
    }
  }
  foreach ($name in $names) {
    $saved = Join-Path $BackupDir $name
    $old = Join-Path $InstallDir $name
    if (Test-Path -LiteralPath $saved) {
      Move-Item -LiteralPath $saved -Destination $old -Force
    }
  }
  exit 1
}
'''


_POSIX_HELPER = r'''#!/bin/sh
parent=$1
install=$2
staged=$3
backup=$4
manifest=$5
executable=$6
logfile=$7
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$logfile"; }
while kill -0 "$parent" 2>/dev/null; do sleep 1; done
sleep 1
mkdir -p "$backup" || exit 1
failed=0
installed_manifest="$manifest.installed"
: > "$installed_manifest"
while IFS= read -r name; do
  if [ -e "$install/$name" ]; then
    mv "$install/$name" "$backup/$name" || failed=1
  fi
done < "$manifest"
if [ "$failed" -eq 0 ]; then
  while IFS= read -r name; do
    printf '%s\n' "$name" >> "$installed_manifest"
    if mv "$staged/$name" "$install/$name"; then
      :
    else
      failed=1
    fi
  done < "$manifest"
fi
if [ "$failed" -eq 0 ] && "$install/$executable" --version >> "$logfile" 2>&1; then
  rm -rf "$backup"
  log "AKSAL update installed successfully."
  exit 0
fi
log "AKSAL update failed; restoring the previous installation."
while IFS= read -r name; do
  rm -rf "$install/$name"
done < "$installed_manifest"
while IFS= read -r name; do
  if [ -e "$backup/$name" ]; then mv "$backup/$name" "$install/$name"; fi
done < "$manifest"
exit 1
'''


def _launch_helper(install: Path, payload: Path, work: Path,
                   manifest: Path, tag: str) -> None:
    token = re.sub(r"[^A-Za-z0-9._-]", "-", tag)
    backup = install / f".aksal-update-backup-{token}"
    if backup.exists():
        try:
            backup.rmdir()  # empty remnant of a completed rollback
        except OSError:
            pass
    if backup.exists():
        raise RuntimeError(
            f"an earlier update backup still exists at {backup}; move or "
            "remove it after checking its contents")
    log_path = home() / "update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    executable = "aksal.exe" if sys.platform == "win32" else "aksal"

    if sys.platform == "win32":
        helper = work / "install-update.ps1"
        helper.write_text(_WINDOWS_HELPER, encoding="utf-8-sig")
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        powershell = system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [
            str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(helper), str(os.getpid()), str(install),
            str(payload), str(backup), str(manifest), executable, str(log_path),
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        helper = work / "install-update.sh"
        helper.write_text(_POSIX_HELPER, encoding="utf-8", newline="\n")
        helper.chmod(0o700)
        command = [
            "/bin/sh", str(helper), str(os.getpid()), str(install),
            str(payload), str(backup), str(manifest), executable, str(log_path),
        ]
        creationflags = 0
    subprocess.Popen(command, close_fds=True, creationflags=creationflags)


def install_latest(*, check_only: bool = False, force: bool = False,
                   log=print) -> bool:
    """Check or stage the latest GitHub release.

    Returns True when an update helper was launched, False when no installation
    was necessary.  Any download or validation failure is reported as a
    RuntimeError so the CLI can show one clean error rather than a traceback.
    """
    try:
        release = fetch_latest()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                "no stable published AKSAL release is available yet") from exc
        raise RuntimeError(
            f"could not check GitHub releases: HTTP {exc.code} {exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001 - turn transport errors into UX
        raise RuntimeError(
            f"could not check GitHub releases: {type(exc).__name__}: {exc}") from exc
    _cache_release(release)
    current = version_tuple(__version__)
    if current is None:
        raise RuntimeError(f"this build has an invalid version: {__version__!r}")
    if release.version <= current and not force:
        log(f"AKSAL is up to date ({__version__}).")
        return False
    if check_only:
        relation = "available" if release.version > current else "current"
        log(f"AKSAL {release.tag} is {relation}; installed version is "
            f"v{__version__}.")
        log(release.page_url)
        return False

    install = _install_root()
    asset = select_asset(release)
    asset_name = str(asset.get("name", ""))
    if Path(asset_name).name != asset_name:
        raise RuntimeError(f"release has an invalid asset name: {asset_name!r}")
    url = str(asset.get("browser_download_url", ""))
    if not url:
        raise RuntimeError(f"release asset {asset_name} has no download URL")

    update_root = cache_home() / "updates"
    update_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="aksal-update-", dir=update_root))
    archive = work / asset_name
    try:
        log(f"downloading AKSAL {release.tag}: {asset_name}")
        expected = _expected_digest(release, asset, work)
        _download(url, archive)
        actual = _sha256(archive)
        if actual != expected:
            raise RuntimeError(
                f"SHA-256 mismatch for {asset_name}: expected {expected}, "
                f"received {actual}")
        log("checksum verified; unpacking update")
        extracted = work / "extracted"
        _extract_archive(archive, extracted)
        archive.unlink(missing_ok=True)
        payload = _payload_root(extracted)
        manifest = _write_manifest(payload, work)

        # A write probe catches Program Files/read-only installations before
        # the current process exits and leaves the user with only a helper log.
        probe = install / ".aksal-update-write-test"
        try:
            probe.write_bytes(b"")
        finally:
            probe.unlink(missing_ok=True)

        _launch_helper(install, payload, work, manifest, release.tag)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    log("update is ready and will be installed when this AKSAL process exits.")
    log(f"result log: {home() / 'update.log'}")
    return True
