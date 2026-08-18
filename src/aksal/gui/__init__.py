"""A simple PyQt6 GUI front end for AKSAL's two phases.

Requires the ``gui`` extra (``pip install aksal[gui]``); PyQt6 is not part of
the base install, so importing this package is the only place that dependency
is required.
"""


def main(argv: list[str] | None = None) -> int:
    from .app import main as _main

    return _main(argv)
