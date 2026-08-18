"""Frozen entry point for the desktop GUI, packaged as aksal-gui[.exe].

A separate entry point from entry.py so the GUI ships as its own executable,
built into the same dist/aksal directory as aksal[.exe] rather than as a
second full copy of the runtime -- see packaging/aksal.spec.
"""
from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> int:
    # A frozen app must call this before anything spawns workers, or each worker
    # re-executes the bundle and the process forks endlessly.
    multiprocessing.freeze_support()

    # Keep downloaded weights with a portable build, same as the CLI exe --
    # both live in the same directory, so this resolves to the same folder.
    if getattr(sys, "frozen", False):
        from aksal.tools import configure_model_home

        configure_model_home()

    if os.environ.get("AKSAL_GUI_PACKAGING_SMOKE") == "1":
        # No display in CI, and no need for one: constructing the main window
        # exercises PyQt6's own packaged plugins (platforms, styles, ...)
        # without blocking on an event loop.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from aksal.gui.app import MainWindow

        app = QApplication([sys.argv[0]])
        window = MainWindow()
        window.show()
        app.processEvents()
        print("gui packaging smoke ok")
        return 0

    from aksal.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
