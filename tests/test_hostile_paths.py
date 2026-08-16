"""Paths users actually have, which are not the paths tests usually use.

A space in a folder name broke the tool completely once -- the dictionary
argument split in half inside MeCab and nothing loaded. It was reported from
`aksal-windows (1)`, the folder a browser makes when you download the same
archive twice, and it would have fired just as readily on `C:/Program Files`.

The lesson was not "quote that one string". It was that every test until then
ran under tmp_path, which is short and ASCII and has no spaces, so the whole
class of failure was invisible. These tests use one deliberately awful
directory name for everything: spaces, parentheses, brackets, a percent sign,
an ampersand, an apostrophe and Japanese.

Every character here is legal on Windows -- the forbidden set is < > : " / \\ |
? * -- so none of this is hypothetical.
"""
import pytest

from aksal import ass, project as project_mod, readings, romaji

# Individually chosen, and each one has broken a tool somewhere:
#   space        splits an unquoted argument string
#   (1)          browsers, on a second download of the same file
#   [x]          a glob metacharacter, if anything globs a user path
#   100%         a format-string introducer for yt-dlp output templates
#   &            a shell separator, if anything ever runs through a shell
#   'q'          a quote inside a quoted argument
#   日本語        non-ASCII, which is likely for THIS tool in particular
HOSTILE = "aksal (1) [x] 100% & 'q' 日本語"


@pytest.fixture
def hostile_dir(tmp_path):
    d = tmp_path / HOSTILE
    d.mkdir()
    return d


def test_tagger_args_survive_every_hostile_character(hostile_dir):
    """The original bug, generalised past the space that revealed it."""
    args = readings.tagger_args(hostile_dir / "dicdir")
    assert args.startswith('-d "') and args.endswith('"')
    # The path is intact between the quotes, not split anywhere.
    assert HOSTILE in args[4:-1]


def test_default_project_keeps_a_dotted_hostile_name(hostile_dir):
    video = hostile_dir / "my song (1).final.mkv"
    root = project_mod.default_output_dir(video)
    assert root.name == "my song (1).final.aksal"
    assert root.parent == hostile_dir


def test_project_round_trips_through_a_hostile_path(hostile_dir):
    """Phase 2 finds its state by stamping the path into the ASS header."""
    from aksal import locate

    root = hostile_dir / "my song (1).aksal"
    proj = project_mod.Project(
        root=root, video=hostile_dir / "ep (1).mkv", mode="video",
        align_audio=hostile_dir / "ep (1).mkv", reference=None,
        segments=[locate.Segment(ref_start=0.0, ref_end=10.0, ep_start=0.0,
                                 ep_end=10.0, offset=0.0)])
    proj.save()
    assert project_mod.Project.load(root).root == root.resolve()


def test_ass_stamp_round_trips_a_hostile_path(hostile_dir):
    """The stamp is read back as the rest of the line, so spaces must survive."""
    out = hostile_dir / "lines (1).ass"
    ass.write(out, [ass.Event(start=0.0, end=1.0, text="test",
                              style="KARA-JP")],
              [ass.STYLE_JP], project=hostile_dir / "my song (1)")
    assert ass.read_project_stamp(out) == hostile_dir / "my song (1)"


def test_lyrics_cache_written_and_read_under_a_hostile_path(hostile_dir):
    """A local lyrics file resolves from a hostile path without a network."""
    from aksal import lyrics

    src = hostile_dir / "lyrics (1).txt"
    src.write_text("かぜ\nひかり\n", encoding="utf-8")
    got = lyrics.resolve(str(src), cache=None, log=lambda *a, **k: None)
    assert got.lines == ["かぜ", "ひかり"]


def test_readings_table_round_trips_under_a_hostile_path(hostile_dir):
    """Overrides are keyed by surface text and stored beside the output."""
    tsv = hostile_dir / "my song (1).readings.tsv"
    readings.write_table(tsv, [(1, "", "風が吹く", "かぜがふく")])
    assert tsv.exists()
    readings.load_overrides(tsv)          # must parse back without raising


def test_romaji_output_is_unaffected_by_the_path(hostile_dir):
    """Sanity: nothing about the path leaks into the text pipeline."""
    units, _owner, cells = readings.units_and_romaji("かぜ", {}, "jp")
    assert "".join(cells) == "kaze"
    assert romaji.looks_like_romaji("kaze ga fuku")
