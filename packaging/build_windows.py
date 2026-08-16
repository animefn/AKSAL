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

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Overridable, because on Windows a shell sitting inside dist/aksal locks the
# directory and nothing can replace it -- which is exactly what happens when
# someone is trying out the previous build while a new one is made.
DIST = Path(os.environ.get("AKSAL_DIST", ROOT / "dist"))
WORK = Path(os.environ.get("AKSAL_WORK", ROOT / "build"))

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
    # yt-dlp is invoked as an executable found on PATH, never imported, so
    # freezing it in would only pin a tool that must stay updatable.
    #
    # demucs is NOT excluded. It used to be, on the grounds that separation is
    # opt-in -- which turned every packaged `--separate-audio` run into a
    # confusing failure: the frozen build had no demucs to import and no
    # python to spawn. It is small next to torch (einops + julius + lameenc),
    # so the build carries it and the flag works everywhere.
    "yt_dlp",
    # Measured at 246 MB in a first build, all of it reached only through
    # transformers' optional imports. Audio is decoded by shelling out to
    # ffmpeg, so PyAV is never touched, and nothing here does vision, ONNX or
    # classical ML.
    "cv2", "av", "onnxruntime", "onnx", "sklearn", "nltk", "sentencepiece",
    "PIL", "timm", "accelerate", "datasets", "evaluate",
    # 212 MB reached ONLY through transformers' BertJapaneseTokenizer, which
    # nothing here uses -- the acoustic model is wav2vec2. Sudachi is not a
    # dependency of AKSAL at all; it was measured as a reading engine and
    # rejected. Without this the build silently grows by a sixth on any machine
    # that happens to have it installed, which also makes the artefact size
    # depend on the builder's environment rather than on the project.
    "sudachipy", "sudachidict_core", "sudachidict_full", "sudachidict_small",
]

HIDDEN = [
    # Reached only through the CLI dispatch table or a lazy import, so a static
    # analyser cannot see them.
    "aksal.dualctc", "aksal.hfmodel", "aksal.catalog", "aksal.fetch",
    "aksal.discover", "aksal.tools",
    "demucs.api",
]


def main() -> int:
    onefile = "--onefile" in sys.argv
    for d in (DIST, WORK):
        shutil.rmtree(d, ignore_errors=True)
        if d.exists():
            print(f"cannot clear {d} -- is a shell or program using it?")
            print("  close anything inside it, or set AKSAL_DIST to another path")
            return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "aksal",
        "--noconfirm", "--clean",
        "--console",
        "--onefile" if onefile else "--onedir",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--paths", str(ROOT / "src"),
        # transformers and fugashi resolve things at import time that a static
        # analyser cannot see.
        "--collect-submodules", "transformers.models.wav2vec2",
        "--collect-submodules", "transformers.models.wavlm",
        "--collect-data", "unidic_lite",
        "--collect-data", "ipadic",
        # pkg_resources is dragged in by something in the dependency tree, and
        # PyInstaller's runtime hook imports it before main() ever runs. On
        # import, jaraco.text reads a data file that is not collected by
        # default, so the whole application dies on a missing "Lorem ipsum.txt"
        # before it has done anything.
        "--collect-data", "jaraco.text",
        # demucs ships its model registry as package data (remote/*.yaml plus
        # files.txt); without them Separator() dies resolving "htdemucs" even
        # though every module imported fine. The weights themselves are NOT
        # bundled -- they download on first use like the acoustic model.
        "--collect-data", "demucs",
        # The JMdict index. It is package data rather than a module, so nothing
        # imports it and a static analyser cannot see it -- without this the
        # frozen build starts fine and then reads every set phrase wrong.
        "--collect-data", "aksal",
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
    smoke_env = dict(os.environ, AKSAL_PACKAGING_SMOKE="1")
    imports = subprocess.run(
        [str(exe)], capture_output=True, text=True, env=smoke_env)
    if imports.returncode != 0 or "packaging imports ok" not in imports.stdout:
        print("\nBUILD IMPORT SMOKE FAILED:")
        print((imports.stderr or imports.stdout or "")[-1500:])
        return 1
    print("  smoke test: model and separation imports ok")

    target = DIST / ("aksal.exe" if onefile else "aksal")
    total = (target.stat().st_size if onefile else
             sum(f.stat().st_size for f in target.rglob("*") if f.is_file()))
    print(f"\nbuilt: {target}")
    print(f"size : {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
