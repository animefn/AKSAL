"""Build a Windows distribution of AKSAL with PyInstaller.

onedir, not onefile. A onefile build of a torch application unpacks several
hundred megabytes to a temp directory on EVERY launch, which costs seconds
before anything happens. A directory starts immediately, and it gives the models
somewhere natural to live next to the executable.

The acoustic model is NOT bundled. It is downloaded on first use and cached, the
way faster-whisper and similar tools do it -- so the download happens once and
the distributable stays the same size whichever model you end up using.

    python packaging/build_windows.py [--onefile]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build"

# Pulled in by transformers/torch but never reached on this path. Excluding
# them is most of the difference between a large build and an absurd one.
# Only whole packages that nothing here imports. NEVER a submodule of a package
# we do use: torch imports torch.distributed from its own dataloader, and sympy
# imports sympy.plotting from its __init__, so excluding either produces a build
# that succeeds and an executable that dies on its first line. That happened
# twice before this rule was written down.
EXCLUDE = [
    "tensorflow", "flax", "jax", "jaxlib", "keras",
    "torchvision",
    "matplotlib", "pandas", "IPython", "notebook", "jupyter",
    "pytest", "_pytest", "tkinter",
    # Optional at runtime: separation is opt-in and yt-dlp is only used by
    # `find`, so both are better installed alongside than frozen in.
    "demucs", "julius", "openunmix", "yt_dlp",
    # Measured at 246 MB in a first build, all of it reached only through
    # transformers' optional imports. Audio is decoded by shelling out to
    # ffmpeg, so PyAV is never touched, and nothing here does vision, ONNX or
    # classical ML.
    "cv2", "av", "onnxruntime", "onnx", "sklearn", "nltk", "sentencepiece",
    "PIL", "timm", "accelerate", "datasets", "evaluate",
]

HIDDEN = [
    # Reached only through the CLI dispatch table or a lazy import, so a static
    # analyser cannot see them.
    "aksal.dualctc", "aksal.hfmodel", "aksal.catalog", "aksal.fetch",
    "aksal.discover", "aksal.tools",
    "scipy.special.cython_special",
]


def main() -> int:
    onefile = "--onefile" in sys.argv
    for d in (DIST, WORK):
        shutil.rmtree(d, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "aksal",
        "--noconfirm", "--clean",
        "--console",
        "--onefile" if onefile else "--onedir",
        "--paths", str(ROOT / "src"),
        # transformers and fugashi resolve things at import time that a static
        # analyser cannot see.
        "--collect-submodules", "transformers.models.wav2vec2",
        "--collect-data", "unidic_lite",
        "--collect-data", "ipadic",
        str(ROOT / "packaging" / "entry.py"),
    ]
    for mod in EXCLUDE:
        cmd += ["--exclude-module", mod]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]

    print(" ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0:
        return rc

    # A build that completes proves nothing. Both previous builds exited 0 and
    # produced an executable that died on its first import, so the artefact is
    # RUN before its size is reported.
    exe = DIST / ("aksal.exe" if onefile else Path("aksal") / "aksal.exe")
    probe = subprocess.run([str(exe), "--help"], capture_output=True, text=True)
    if probe.returncode != 0 or "phase1" not in (probe.stdout or ""):
        print("\nBUILD IS DEAD -- the executable does not start:")
        print((probe.stderr or probe.stdout or "")[-1500:])
        return 1
    print("  smoke test: --help ok")

    target = DIST / ("aksal.exe" if onefile else "aksal")
    total = (target.stat().st_size if onefile else
             sum(f.stat().st_size for f in target.rglob("*") if f.is_file()))
    print(f"\nbuilt: {target}")
    print(f"size : {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
