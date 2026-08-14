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
EXCLUDE = [
    "tensorflow", "flax", "jax", "jaxlib", "keras",
    "torch.distributed", "torch.testing", "torch.utils.tensorboard",
    "torchvision", "torchaudio.prototype",
    "matplotlib", "pandas", "IPython", "notebook", "jupyter",
    "pytest", "_pytest", "sympy.plotting", "tkinter",
    # Optional at runtime: separation is opt-in, and yt-dlp is only used by
    # `find`. Both are better installed alongside than frozen in.
    "demucs", "julius", "openunmix", "yt_dlp",
]

HIDDEN = [
    "aksal.dualctc", "aksal.catalog", "aksal.fetch", "aksal.discover",
    "sklearn.utils._typedefs", "scipy.special.cython_special",
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

    target = DIST / ("aksal.exe" if onefile else "aksal")
    total = (target.stat().st_size if onefile else
             sum(f.stat().st_size for f in target.rglob("*") if f.is_file()))
    print(f"\nbuilt: {target}")
    print(f"size : {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
