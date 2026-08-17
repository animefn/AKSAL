"""Build a native AKSAL distribution with PyInstaller.

Run this on the OS being targeted; PyInstaller does not cross-compile.  The
default is an onedir bundle because a onefile torch application would unpack
hundreds of megabytes on every launch.  Acoustic and Demucs model weights are
not bundled and are cached in the platform's writable user cache on first use.

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

# Optional packages pulled in by transformers/torch but never reached by AKSAL.
# Only exclude complete packages that AKSAL itself does not import.
EXCLUDE = [
    "tensorflow", "flax", "jax", "jaxlib", "keras", "torchvision",
    "matplotlib", "pandas", "IPython", "notebook", "jupyter",
    "pytest", "_pytest", "tkinter",
    # AKSAL invokes the separately updatable executable selected by tools.py.
    "yt_dlp",
    "cv2", "av", "onnxruntime", "onnx", "sklearn", "nltk",
    "sentencepiece", "PIL", "timm", "accelerate", "datasets", "evaluate",
    "sudachipy", "sudachidict_core", "sudachidict_full", "sudachidict_small",
]

HIDDEN = [
    "aksal.dualctc", "aksal.hfmodel", "aksal.catalog", "aksal.fetch",
    "aksal.discover", "aksal.tools", "aksal.updater", "demucs.api",
]


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


def executable_path(onefile: bool) -> Path:
    name = "aksal.exe" if sys.platform == "win32" else "aksal"
    return DIST / name if onefile else DIST / "aksal" / name


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
        "--name", "aksal", "--noconfirm", "--clean", "--console",
        "--onefile" if onefile else "--onedir",
        "--distpath", str(DIST), "--workpath", str(WORK),
        "--specpath", str(WORK), "--paths", str(ROOT / "src"),
        "--collect-submodules", "transformers.models.wav2vec2",
        "--collect-submodules", "transformers.models.wavlm",
        "--collect-data", "unidic_lite", "--collect-data", "ipadic",
        # PyInstaller's pkg_resources hook imports jaraco.text at startup.
        "--collect-data", "jaraco.text",
        # Demucs' registry is package data; model weights remain a download.
        "--collect-data", "demucs",
        # The compressed JMdict index is AKSAL package data.
        "--collect-data", "aksal",
        str(ROOT / "packaging" / "entry.py"),
    ]
    for module in EXCLUDE:
        cmd += ["--exclude-module", module]
    for module in HIDDEN:
        cmd += ["--hidden-import", module]

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
    try:
        result = subprocess.run(cmd, cwd=ROOT)
    finally:
        stamp.unlink(missing_ok=True)
    if result.returncode != 0:
        return result.returncode

    # A completed freeze is not evidence that the program imports. Run both a
    # CLI probe and the optional dependency/model import probe before archiving.
    executable = executable_path(onefile)
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    probe = subprocess.run(
        [str(executable), "--help"], capture_output=True, text=True)
    if probe.returncode != 0 or "phase1" not in (probe.stdout or ""):
        print("\nBUILD IS DEAD -- the executable does not start:")
        print((probe.stderr or probe.stdout or "")[-1500:])
        return 1
    print("  smoke test: --help ok")

    version_probe = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True)
    if (version_probe.returncode != 0 or
            version not in (version_probe.stdout or "")):
        print("\nBUILD VERSION STAMP FAILED:")
        print((version_probe.stderr or version_probe.stdout or "")[-1500:])
        return 1
    print(f"  smoke test: version {version} ok")

    smoke_env = dict(os.environ, AKSAL_PACKAGING_SMOKE="1")
    imports = subprocess.run(
        [str(executable)], capture_output=True, text=True, env=smoke_env)
    if imports.returncode != 0 or "packaging imports ok" not in imports.stdout:
        print("\nBUILD IMPORT SMOKE FAILED:")
        print((imports.stderr or imports.stdout or "")[-1500:])
        return 1
    print("  smoke test: model and separation imports ok")

    target = executable if onefile else executable.parent
    total = (target.stat().st_size if onefile else
             sum(f.stat().st_size for f in target.rglob("*") if f.is_file()))
    print(f"\nbuilt: {target}")
    print(f"size : {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
