"""Frozen entry point.

A thin shim rather than pointing PyInstaller at the package: it gives the build
one unambiguous module to start from, and a place to put anything that must
happen before the CLI runs in a frozen environment.
"""
from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> int:
    # A frozen app must call this before anything spawns workers, or each worker
    # re-executes the bundle and the process forks endlessly.
    multiprocessing.freeze_support()

    # /Applications, /usr/local and managed Windows installations may all be
    # read-only. Honour an explicit HF_HOME; otherwise use the native writable
    # user cache selected by AKSAL.
    if getattr(sys, "frozen", False) and not os.environ.get("HF_HOME"):
        from aksal.tools import cache_home

        os.environ["HF_HOME"] = str(cache_home() / "huggingface")

    if os.environ.get("AKSAL_PACKAGING_SMOKE") == "1":
        import demucs.api as demucs_api
        import torch
        import torchaudio
        from torchaudio.functional import forced_align
        from transformers import AutoModel, AutoModelForCTC, AutoProcessor

        from aksal import ass, dualctc, hfmodel, ichiran

        required = (demucs_api, forced_align, AutoModel, AutoModelForCTC,
                    AutoProcessor, ass, dualctc, hfmodel, ichiran)
        print(f"packaging imports ok: torch {torch.__version__}, "
              f"torchaudio {torchaudio.__version__}, {len(required)} probes")
        return 0

    from aksal.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
