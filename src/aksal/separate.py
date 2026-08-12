"""Vocal isolation via demucs.

The single biggest accuracy lever in the whole pipeline. The acoustic model was
trained on speech; in a full music mix the drums, bass and synths sit in the
same spectral space as the voice, and per-character confidence collapses.
Separating the vocal stem first is what makes mora-level timing usable.

Runs on the REFERENCE track in mode A -- studio audio separates far more
cleanly than a broadcast mix with SFX over it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MODEL = "htdemucs"


def vocals_path(outdir: Path, source: Path) -> Path:
    return outdir / MODEL / source.stem / "vocals.wav"


def separate(source: Path, outdir: Path, device: str = "cpu",
             force: bool = False, log=print) -> Path:
    """Return a path to the isolated vocal stem, running demucs if needed."""
    target = vocals_path(outdir, source)
    if target.exists() and not force:
        log(f"  using cached stem: {target.name}")
        return target

    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "demucs", "-n", MODEL, "--two-stems=vocals",
           "-d", device, "-o", str(outdir), str(source)]
    log(f"  separating vocals ({MODEL}, {device}) -- this is the slow step")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(
            "demucs failed. It is a hard dependency of this tool; if it will "
            "not install on your Python version, create a 3.11 environment "
            "(see README). To proceed without it for one run, pass "
            "--no-preprocess.")
    if not target.exists():
        raise RuntimeError(f"demucs finished but {target} is missing")
    return target
