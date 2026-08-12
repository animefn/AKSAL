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


def separate(source: Path, target: Path, device: str = "cpu",
             force: bool = False, log=print) -> Path:
    """Isolate vocals to `target`, running demucs if it is not already there.

    demucs insists on writing a nested <model>/<stem>/vocals.wav tree, so the
    result is moved to the flat sibling path the rest of the tool uses and the
    tree is removed. Nothing is left behind for the user to find later.
    """
    import shutil
    import tempfile

    if target.exists() and not force:
        log(f"  using cached stem: {target.name}")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    outdir = Path(tempfile.mkdtemp(prefix=".aksal-demucs-",
                                   dir=str(target.parent)))
    cmd = [sys.executable, "-m", "demucs", "-n", MODEL, "--two-stems=vocals",
           "-d", device, "-o", str(outdir), str(source)]
    log(f"  separating vocals ({MODEL}, {device}) -- this is the slow step")
    try:
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            raise RuntimeError(
                "demucs failed. It is a hard dependency of this tool; if it "
                "will not install on your Python version, create a 3.11 "
                "environment (see README). To proceed without it for one run, "
                "pass --no-preprocess.")

        produced = vocals_path(outdir, source)
        if not produced.exists():
            # Fall back to a search: demucs has moved this path around between
            # versions, and failing here would waste the minutes just spent.
            found = sorted(outdir.rglob("vocals.wav"))
            if not found:
                raise RuntimeError(
                    f"demucs finished but produced no vocals.wav under {outdir}")
            produced = found[0]

        shutil.move(str(produced), str(target))
    finally:
        shutil.rmtree(outdir, ignore_errors=True)

    log(f"  vocal stem: {target.name}")
    return target
