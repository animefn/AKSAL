"""Build a native AKSAL distribution with PyInstaller.

Run this on the OS being targeted; PyInstaller does not cross-compile.  The
default is an onedir bundle because a onefile torch application would unpack
hundreds of megabytes on every launch. Acoustic and Demucs model weights are
not bundled; packaged builds download them into their adjacent ``models``
directory on first use.

Builds two executables from packaging/aksal.spec: ``aksal`` (the CLI) and
``aksal-gui`` (the desktop GUI). In onedir mode they land side by side in one
dist/aksal directory, sharing one runtime instead of paying for it twice; in
onefile mode each is fully self-contained (see the spec for why those need
different builds).

    python packaging/build.py [--onefile]
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(os.environ.get("AKSAL_DIST", ROOT / "dist"))
WORK = Path(os.environ.get("AKSAL_WORK", ROOT / "build"))
SPEC = ROOT / "packaging" / "aksal.spec"


def build_version() -> str:
    """Version compiled into a frozen build; release tags are authoritative."""
    supplied = os.environ.get("AKSAL_BUILD_VERSION", "").removeprefix("v")
    if re.fullmatch(r"\d+(?:\.\d+){1,3}", supplied):
        return supplied
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([0-9.]+)"', project, re.MULTILINE)
    if not match:
        raise RuntimeError("cannot determine AKSAL version")
    return match.group(1)


def executable_name(base: str) -> str:
    return f"{base}.exe" if sys.platform == "win32" else base


def executable_path(base: str, onefile: bool) -> Path:
    name = executable_name(base)
    return DIST / name if onefile else DIST / "aksal" / name


def smoke_test_cli(executable: Path, version: str) -> str | None:
    """Return an error message, or None if the CLI executable is alive."""
    probe = subprocess.run(
        [str(executable), "--help"], capture_output=True, text=True)
    if probe.returncode != 0 or "phase1" not in (probe.stdout or ""):
        return ("the executable does not start:\n"
                + (probe.stderr or probe.stdout or "")[-1500:])
    print("  smoke test: aksal --help ok")

    version_probe = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True)
    if (version_probe.returncode != 0 or
            version not in (version_probe.stdout or "")):
        return ("version stamp failed:\n"
                + (version_probe.stderr or version_probe.stdout or "")[-1500:])
    print(f"  smoke test: aksal --version {version} ok")

    smoke_env = dict(os.environ, AKSAL_PACKAGING_SMOKE="1")
    imports = subprocess.run(
        [str(executable)], capture_output=True, text=True, env=smoke_env)
    if imports.returncode != 0 or "packaging imports ok" not in imports.stdout:
        return ("model/separation import smoke failed:\n"
                + (imports.stderr or imports.stdout or "")[-1500:])
    print("  smoke test: aksal model and separation imports ok")
    return None


def smoke_test_gui(executable: Path) -> str | None:
    """Return an error message, or None if the GUI executable is alive.

    Constructs the main window offscreen and exits rather than opening a
    blocking event loop, so this runs unattended in CI with no display.
    """
    smoke_env = dict(os.environ, AKSAL_GUI_PACKAGING_SMOKE="1")
    probe = subprocess.run(
        [str(executable)], capture_output=True, text=True, env=smoke_env)
    if probe.returncode != 0 or "gui packaging smoke ok" not in probe.stdout:
        return ("the GUI executable does not start:\n"
                + (probe.stderr or probe.stdout or "")[-1500:])
    print("  smoke test: aksal-gui window construction ok")
    return None


def main() -> int:
    onefile = "--onefile" in sys.argv
    for directory in (DIST, WORK):
        shutil.rmtree(directory, ignore_errors=True)
        if directory.exists():
            print(f"cannot clear {directory} -- is a shell or program using it?")
            print("  close anything inside it, or set AKSAL_DIST/AKSAL_WORK")
            return 1
    WORK.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(DIST), "--workpath", str(WORK),
        str(SPEC),
    ]

    # This module exists only while PyInstaller analyses the package.  The
    # frozen bytecode keeps the value, while source installs continue to use
    # importlib.metadata and the checkout never becomes dirty after a build.
    version = build_version()
    stamp = ROOT / "src" / "aksal" / "_frozen_version.py"
    # A killed build may have left its generated stamp behind.
    stamp.unlink(missing_ok=True)
    stamp.write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    print(f"building AKSAL {version}")
    print(subprocess.list2cmdline(cmd), flush=True)
    env = dict(os.environ, AKSAL_ONEFILE="1") if onefile else None
    try:
        result = subprocess.run(cmd, cwd=ROOT, env=env)
    finally:
        stamp.unlink(missing_ok=True)
    if result.returncode != 0:
        return result.returncode

    # A completed freeze is not evidence that either program imports or
    # starts. Probe both before archiving.
    cli_exe = executable_path("aksal", onefile)
    gui_exe = executable_path("aksal-gui", onefile)
    if os.name != "nt":
        for exe in (cli_exe, gui_exe):
            exe.chmod(exe.stat().st_mode | 0o111)

    for error in (smoke_test_cli(cli_exe, version), smoke_test_gui(gui_exe)):
        if error:
            print("\nBUILD IS DEAD --", error)
            return 1

    # Empty directories disappear from zip files, so ship a small explanation.
    # The updater deliberately preserves this mutable directory across updates.
    # Both executables live in the same directory in either mode, so one
    # models/ folder beside them covers both.
    model_dir = cli_exe.parent / "models"
    model_dir.mkdir(exist_ok=True)
    (model_dir / "README.txt").write_text(
        "AKSAL downloads acoustic and vocal-separation models here on first "
        "use.\nKeep this folder beside the AKSAL executables.\n",
        encoding="utf-8")

    if onefile:
        target = f"{cli_exe} + {gui_exe}"
        total = cli_exe.stat().st_size + gui_exe.stat().st_size
    else:
        target = cli_exe.parent
        total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"\nbuilt: {target}")
    print(f"size : {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
