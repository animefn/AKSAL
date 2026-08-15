"""The dictionary pin must survive a path with a space in it.

MeCab takes its arguments as one string and splits them on whitespace, so an
unquoted `-d <path>` breaks in half the moment the path contains a space. The
pin added to make readings reproducible introduced exactly that, and it was
reported from `aksal-windows (1)` -- the folder a browser creates on a second
download of the same archive.

The paths this fails on are ordinary: `C:/Program Files`, any user folder with
a space, any duplicate download. So the case is pinned here rather than left to
whoever unzips the build somewhere unlucky.
"""
import shutil

import pytest

from aksal import readings


def test_a_spaced_path_stays_one_argument():
    args = readings.tagger_args("C:/some dir/dicdir")
    assert args == '-d "C:/some dir/dicdir"'


def test_backslashes_become_posix_separators():
    """MeCab is given forward slashes on every platform."""
    assert "\\" not in readings.tagger_args(r"C:\some dir\dicdir")


def test_the_real_dictionary_loads_from_a_spaced_path(tmp_path):
    """The end-to-end case: a dictionary that genuinely lives under a space.

    Asserting the argument string alone would not have caught the original bug,
    because that string looked perfectly reasonable -- the damage happened
    inside MeCab's own tokeniser. So the dictionary is really copied to a path
    with a space and a tagger is really built on it.
    """
    fugashi = pytest.importorskip("fugashi")
    unidic_lite = pytest.importorskip("unidic_lite")

    spaced = tmp_path / "a dir with spaces"
    shutil.copytree(unidic_lite.DICDIR, spaced / "dicdir")

    tagger = fugashi.Tagger(readings.tagger_args(spaced / "dicdir"))
    words = [w.surface for w in tagger("風が吹く")]
    assert "".join(words) == "風が吹く"


def test_module_pins_the_dictionary_at_all():
    """Whatever the quoting, the point of the pin is that -d is passed.

    Without it fugashi uses whichever dictionary is installed, preferring full
    UniDic -- so an unrelated package in the environment silently changes every
    reading.
    """
    readings.tagger()
    assert readings._TAGGER_ARGS.startswith("-d ")
