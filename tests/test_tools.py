"""Finding ffmpeg, and what happens when it is not there.

Every audio step shells out to ffmpeg, so its absence is the most likely first
failure for someone who has just unzipped a folder. These cover the resolution
order and the refusal, not the download -- that one needs the network and is
verified by using it.
"""
from __future__ import annotations

import pytest

from aksal import tools


@pytest.fixture(autouse=True)
def clean_cache():
    tools._resolved.clear()
    yield
    tools._resolved.clear()


def test_a_remembered_path_wins_over_PATH(tmp_path, monkeypatch):
    """A location the user chose explicitly should not be overridden by
    whatever happens to be on PATH."""
    chosen = tmp_path / "ffmpeg.exe"
    chosen.write_text("")
    monkeypatch.setattr(tools, "_load_config",
                        lambda: {"ffmpeg_path": str(chosen)})
    monkeypatch.setattr(tools, "_works", lambda p: True)
    monkeypatch.setattr(tools.shutil, "which", lambda n: "C:/somewhere/ffmpeg.exe")
    assert tools.find("ffmpeg") == str(chosen)


def test_falls_back_to_PATH(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_load_config", dict)
    monkeypatch.setattr(tools, "_home", lambda: tmp_path)
    on_path = tmp_path / "sys-ffmpeg.exe"
    on_path.write_text("")
    monkeypatch.setattr(tools.shutil, "which", lambda n: str(on_path))
    monkeypatch.setattr(tools, "_works", lambda p: True)
    assert tools.find("ffmpeg") == str(on_path)


def test_a_binary_that_does_not_run_is_not_accepted(tmp_path, monkeypatch):
    """Existing on disk is not the same as working -- a stub or a wrong-arch
    binary would otherwise be picked and fail much later."""
    monkeypatch.setattr(tools, "_load_config", dict)
    monkeypatch.setattr(tools, "_home", lambda: tmp_path)
    broken = tmp_path / "ffmpeg.exe"
    broken.write_text("")
    monkeypatch.setattr(tools.shutil, "which", lambda n: str(broken))
    monkeypatch.setattr(tools, "_works", lambda p: False)
    assert tools.find("ffmpeg") is None


def test_missing_ffmpeg_refuses_rather_than_hanging(monkeypatch):
    """Without a terminal there is nobody to answer the prompt, so it must fail
    with an explanation instead of blocking on input forever -- which is what a
    scripted or scheduled run would hit."""
    monkeypatch.setattr(tools, "find", lambda name: None)
    monkeypatch.setattr(tools.sys, "stdin", None)
    with pytest.raises(SystemExit, match="ffmpeg is required"):
        tools.ensure(log=lambda *a, **k: None)


def test_use_path_accepts_a_folder(tmp_path, monkeypatch):
    import os

    exe = ".exe" if os.name == "nt" else ""
    (tmp_path / f"ffmpeg{exe}").write_text("")
    (tmp_path / f"ffprobe{exe}").write_text("")
    monkeypatch.setattr(tools, "_works", lambda p: True)
    saved = {}
    monkeypatch.setattr(tools, "_save_config", lambda c: saved.update(c))
    assert tools.use_path(str(tmp_path), log=lambda *a, **k: None)
    assert saved["ffmpeg_path"].endswith(f"ffmpeg{exe}")
    assert saved["ffprobe_path"].endswith(f"ffprobe{exe}")


def test_use_path_rejects_a_folder_without_both_binaries(tmp_path, monkeypatch):
    """ffprobe is needed as much as ffmpeg; accepting a folder with only one
    would fail later, somewhere less obvious."""
    import os

    (tmp_path / f"ffmpeg{'.exe' if os.name == 'nt' else ''}").write_text("")
    monkeypatch.setattr(tools, "_works", lambda p: True)
    assert not tools.use_path(str(tmp_path), log=lambda *a, **k: None)
