# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AKSAL: builds aksal[.exe] and aksal-gui[.exe].

Invoked by packaging/build.py as `pyinstaller packaging/aksal.spec`, never
directly -- build.py sets --distpath/--workpath and writes the version stamp
first.

Onedir mode (the default) puts both executables' Analysis results into ONE
COLLECT call, so their several-hundred-MB shared runtime (torch, transformers,
...) is deduplicated by name into a single dist/aksal directory instead of
being copied twice: aksal.exe and aksal-gui.exe end up side by side, sharing
one _internal. This deliberately does NOT use PyInstaller's MERGE() -- MERGE
is for executables that end up in SEPARATE directories, and turns onedir
builds into self-extracting ones that unpack their shared files into a temp
directory on every launch. Neither applies here: both executables already
share one directory, so a plain combined COLLECT (which just deduplicates
identical destination paths on its own) gets the same disk saving with none
of that extraction cost.

Onefile mode (AKSAL_ONEFILE=1) builds two fully independent single-file
executables instead, because MERGE's sharing does not apply to onefile
bundles and there is no directory for them to share.
"""
from __future__ import annotations

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ONEFILE = os.environ.get("AKSAL_ONEFILE") == "1"

# Optional packages pulled in by transformers/torch/PyQt6 but never reached by
# AKSAL. Only exclude complete packages that AKSAL itself does not import.
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

DATAS = (
    collect_data_files("unidic_lite")
    + collect_data_files("ipadic")
    # PyInstaller's pkg_resources hook imports jaraco.text at startup.
    + collect_data_files("jaraco.text")
    # Demucs' registry is package data; model weights remain a download.
    + collect_data_files("demucs")
    # The compressed JMdict index is AKSAL package data.
    + collect_data_files("aksal")
)

SUBMODULES = (
    collect_submodules("transformers.models.wav2vec2")
    + collect_submodules("transformers.models.wavlm")
)

SRC = os.path.join(SPECPATH, os.pardir, "src")  # noqa: F821 - injected by PyInstaller


def analysis(script: str) -> Analysis:  # noqa: F821 - injected by PyInstaller
    return Analysis(
        [os.path.join(SPECPATH, script)],  # noqa: F821
        pathex=[SRC],
        datas=list(DATAS),
        hiddenimports=list(HIDDEN) + list(SUBMODULES),
        excludes=list(EXCLUDE),
        noarchive=False,
        optimize=0,
    )


a_cli = analysis("entry.py")
a_gui = analysis("entry_gui.py")

pyz_cli = PYZ(a_cli.pure)  # noqa: F821
pyz_gui = PYZ(a_gui.pure)  # noqa: F821

exe_cli = EXE(  # noqa: F821
    pyz_cli, a_cli.scripts,
    a_cli.binaries if ONEFILE else [],
    a_cli.datas if ONEFILE else [],
    exclude_binaries=not ONEFILE,
    name="aksal",
    console=True,
    strip=False,
    upx=True,
    disable_windowed_traceback=False,
)
exe_gui = EXE(  # noqa: F821
    pyz_gui, a_gui.scripts,
    a_gui.binaries if ONEFILE else [],
    a_gui.datas if ONEFILE else [],
    exclude_binaries=not ONEFILE,
    name="aksal-gui",
    console=False,
    strip=False,
    upx=True,
    disable_windowed_traceback=False,
)

if not ONEFILE:
    COLLECT(  # noqa: F821
        exe_cli, a_cli.binaries, a_cli.datas,
        exe_gui, a_gui.binaries, a_gui.datas,
        strip=False, upx=True, name="aksal",
    )
