"""Frozen entry point.

A thin shim rather than pointing PyInstaller at the package: it gives the build
one unambiguous module to start from, and a place to put anything that must
happen before the CLI runs in a frozen environment.
"""
from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


def main() -> int:
    # A frozen app must call this before anything spawns workers, or each worker
    # re-executes the bundle and the process forks endlessly.
    multiprocessing.freeze_support()

    # Keep models beside the executable rather than in the user profile, so the
    # whole tool is one movable folder. Honour an existing HF_HOME if the user
    # has deliberately set one.
    if getattr(sys, "frozen", False) and not os.environ.get("HF_HOME"):
        os.environ["HF_HOME"] = str(Path(sys.executable).parent / "models")

    from aksal.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
