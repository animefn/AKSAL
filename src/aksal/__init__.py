"""AKSAL -- AFN Karaoke Syllable Aligner for Lyrics.

Two-phase karaoke timing for any song in a video: openings, endings
and insert songs alike. Phase 1 produces timed lines for you to
correct; phase 2 turns those into syllable-level karaoke.
"""

try:
    # Generated temporarily by packaging/build.py and compiled into release
    # executables.  A source/pip installation gets its version from metadata.
    from ._frozen_version import VERSION as __version__
except ImportError:
    try:
        from importlib.metadata import version

        __version__ = version("aksal")
    except Exception:  # noqa: BLE001 - an uninstalled source checkout
        __version__ = "0.1.0"
