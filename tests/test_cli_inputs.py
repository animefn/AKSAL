"""The CLI's input contracts: reference resolution, fit checks, early refusals.

Each of these guards a decision that used to fail late or silently:

  - a URL reference used to be impossible, so people downloaded by hand;
  - a full lyric sheet in video mode used to pass the physical check and come
    out confidently wrong, because real cuts were never measured;
  - a --tracks typo used to be reported AFTER the whole alignment had run.
"""
import pytest

from aksal import cli


# --- resolve_media -----------------------------------------------------------

def test_no_reference_is_none(tmp_path):
    assert cli.resolve_media(None, tmp_path / "r.m4a") is None


def test_local_file_passes_through(tmp_path):
    ref = tmp_path / "song.flac"
    ref.write_bytes(b"x")
    got = cli.resolve_media(str(ref), tmp_path / "r.m4a", log=lambda *a: None)
    assert got == ref


def test_missing_local_file_refuses_up_front(tmp_path):
    """A typo'd path must die here, not forty seconds into a fingerprint."""
    with pytest.raises(SystemExit, match="reference not found"):
        cli.resolve_media(str(tmp_path / "nope.flac"), tmp_path / "r.m4a")


def test_url_is_fetched_to_the_cache_path(tmp_path, monkeypatch):
    from aksal import fetch

    calls = []

    def fake_download(url, dest):
        calls.append((url, dest))
        dest.write_bytes(b"audio")
        return dest

    monkeypatch.setattr(fetch, "download_audio", fake_download)
    dest = tmp_path / "OP01.lines.reference.m4a"
    got = cli.resolve_media("https://youtu.be/abc", dest, log=lambda *a: None)
    assert got == dest and calls == [("https://youtu.be/abc", dest)]


def test_cached_url_is_not_refetched(tmp_path, monkeypatch):
    """The download is per-project, once. Phase 2 and re-runs read the file."""
    from aksal import fetch

    monkeypatch.setattr(fetch, "download_audio",
                        lambda *a: pytest.fail("network touched"))
    dest = tmp_path / "r.m4a"
    dest.write_bytes(b"audio")
    got = cli.resolve_media("https://youtu.be/abc", dest, log=lambda *a: None)
    assert got == dest


# --- the fit check, with its measured thresholds ------------------------------

def _fits(n_units, window):
    lines = []
    cli.check_fits_window(n_units, window, log=lambda *a: lines.append(a))
    return lines


def test_a_real_cut_passes_silently():
    """Densest genuine cut measured: 0.49 of its window. No noise below that."""
    assert _fits(421, 87) == []           # the corpus's densest song, verbatim


def test_denser_than_any_real_song_warns_but_runs():
    """Between 0.55 and 1.0: louder than anything real, still possible."""
    lines = _fits(700, 92)                # needs 70s of 92 -- 0.76
    assert lines and "unusually long" in lines[0][0]


def test_physically_impossible_still_stops():
    with pytest.raises(SystemExit, match="cannot fit"):
        cli.check_fits_window(1200, 92)


# --- early refusals -----------------------------------------------------------

def test_bad_tracks_dies_before_any_work(tmp_path):
    """The typo must cost nothing. It used to cost a full alignment run."""
    lines = tmp_path / "x.lines.ass"
    lines.write_text("[Events]\n", encoding="utf-8")
    args = cli.build_parser().parse_args(
        ["phase2", str(lines), "--tracks", "jp,romji"])
    with pytest.raises(SystemExit, match="--tracks accepts"):
        args.func(args)


def test_duration_accepts_clock_form():
    args = cli.build_parser().parse_args(
        ["phase1", "--video", "x.mkv", "--lyrics", "l.txt",
         "--duration", "1:32"])
    assert args.duration == 92.0


def test_duration_default_is_none_so_the_cli_can_announce_it():
    """The default is applied late, so video mode can say it is guessing."""
    args = cli.build_parser().parse_args(
        ["phase1", "--video", "x.mkv", "--lyrics", "l.txt"])
    assert args.duration is None


# --- separation cache ----------------------------------------------------------

def test_cached_stem_needs_no_demucs(tmp_path, monkeypatch):
    """A cached vocal stem must be reusable even where demucs is absent --
    that is the whole point of caching the slow step."""
    import builtins

    from aksal import separate

    real_import = builtins.__import__

    def no_demucs(name, *a, **kw):
        if name.startswith("demucs"):
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_demucs)
    stem = tmp_path / "v.vocals.wav"
    stem.write_bytes(b"x")
    got = separate.separate(tmp_path / "in.wav", stem, log=lambda *a: None)
    assert got == stem


def test_missing_demucs_says_what_to_do(tmp_path, monkeypatch):
    import builtins

    from aksal import separate

    real_import = builtins.__import__

    def no_demucs(name, *a, **kw):
        if name.startswith("demucs"):
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_demucs)
    with pytest.raises(RuntimeError, match="pip install demucs"):
        separate.separate(tmp_path / "in.wav", tmp_path / "out.wav",
                          log=lambda *a: None)
