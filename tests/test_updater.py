from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import zipfile
import pytest

from aksal import updater


def release(tag="v1.2.3", assets=()):
    parsed = updater.version_tuple(tag)
    assert parsed is not None
    return updater.Release(tag, parsed, "https://example.test/release", tuple(assets))


def native_archive(tag="v99.0.0"):
    """Build a minimal release archive for the platform running the test."""
    suffix = updater.platform_asset_suffix()
    assert suffix is not None
    name = f"aksal-{tag}{suffix}"
    executable = "aksal.exe" if sys.platform == "win32" else "aksal"
    archive = io.BytesIO()
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(executable, b"new exe")
            bundle.writestr("_internal/library.dll", b"new library")
    else:
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            for member_name, content, mode in (
                    (f"aksal/{executable}", b"new exe", 0o755),
                    ("aksal/_internal/library.so", b"new library", 0o644)):
                info = tarfile.TarInfo(member_name)
                info.size = len(content)
                info.mode = mode
                bundle.addfile(info, io.BytesIO(content))
    return name, archive.getvalue(), executable


@pytest.mark.parametrize("text,expected", [
    ("0.1.0", (0, 1, 0, 0)),
    ("v2.4", (2, 4, 0, 0)),
    ("10.2.3.4", (10, 2, 3, 4)),
    ("v1.0rc1", None),
    ("main", None),
])
def test_version_tuple_accepts_only_stable_numeric_tags(text, expected):
    assert updater.version_tuple(text) == expected


def test_newer_version_is_compared_numerically():
    assert updater.is_newer(release("v0.10.0"), "0.9.9")
    assert not updater.is_newer(release("v0.9.9"), "0.10.0")


@pytest.mark.parametrize("system,machine,suffix", [
    ("win32", "AMD64", "-windows-x64.zip"),
    ("linux", "x86_64", "-linux-x64.tar.gz"),
    ("darwin", "arm64", "-macos-arm64.tar.gz"),
])
def test_platform_asset_suffix(monkeypatch, system, machine, suffix):
    monkeypatch.setattr(updater.sys, "platform", system)
    monkeypatch.setattr(updater.platform, "machine", lambda: machine)
    assert updater.platform_asset_suffix() == suffix


def test_select_asset_requires_one_exact_platform_archive(monkeypatch):
    monkeypatch.setattr(updater, "platform_asset_suffix",
                        lambda: "-windows-x64.zip")
    wanted = {"name": "aksal-v1.2.3-windows-x64.zip"}
    found = updater.select_asset(release(assets=[
        {"name": "aksal-v1.2.3-linux-x64.tar.gz"}, wanted,
    ]))
    assert found is wanted
    with pytest.raises(RuntimeError, match="no unique"):
        updater.select_asset(release(assets=[]))


def test_extract_zip_and_find_windows_payload(tmp_path, monkeypatch):
    archive = tmp_path / "aksal-v1-windows-x64.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("aksal.exe", b"exe")
        bundle.writestr("_internal/library.dll", b"dll")
    extracted = tmp_path / "out"
    updater._extract_archive(archive, extracted)
    monkeypatch.setattr(updater.sys, "platform", "win32")
    assert updater._payload_root(extracted) == extracted
    assert (extracted / "_internal/library.dll").read_bytes() == b"dll"


def test_extract_linux_tar_preserves_wrapper_directory(tmp_path, monkeypatch):
    archive = tmp_path / "aksal-v1-linux-x64.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name, content, mode in (("aksal/aksal", b"exe", 0o755),
                                    ("aksal/_internal/lib.so", b"so", 0o644)):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = mode
            bundle.addfile(info, io.BytesIO(content))
    extracted = tmp_path / "out"
    updater._extract_archive(archive, extracted)
    monkeypatch.setattr(updater.sys, "platform", "linux")
    assert updater._payload_root(extracted) == extracted / "aksal"


@pytest.mark.parametrize("name", [
    "../escape", "/absolute", "x/../../escape", "C:/drive-escape",
])
def test_archive_path_traversal_is_rejected(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, b"bad")
    with pytest.raises(RuntimeError, match="unsafe path"):
        updater._extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_expected_digest_accepts_github_digest(tmp_path):
    digest = "a" * 64
    assert updater._expected_digest(
        release(), {"name": "aksal.zip", "digest": "sha256:" + digest},
        tmp_path) == digest


def test_expected_digest_downloads_sidecar(tmp_path, monkeypatch):
    archive_name = "aksal-v1-windows-x64.zip"
    checksum = "b" * 64
    assets = [
        {"name": archive_name},
        {"name": archive_name + ".sha256",
         "browser_download_url": "https://example.test/checksum"},
    ]

    def fake_download(url, target, timeout=0):
        assert url.endswith("checksum")
        target.write_text(f"{checksum}  {archive_name}\n", encoding="ascii")

    monkeypatch.setattr(updater, "_download", fake_download)
    assert updater._expected_digest(
        release(assets=assets), assets[0], tmp_path) == checksum


def test_expected_digest_refuses_unverified_release(tmp_path):
    with pytest.raises(RuntimeError, match="refusing"):
        updater._expected_digest(
            release(), {"name": "aksal.zip"}, tmp_path)


def test_sha256_streams_file(tmp_path):
    target = tmp_path / "archive"
    target.write_bytes(b"AKSAL update")
    assert updater._sha256(target) == hashlib.sha256(b"AKSAL update").hexdigest()


def test_notification_uses_fresh_cache_without_network(tmp_path, monkeypatch):
    suffix = updater.platform_asset_suffix()
    assert suffix is not None
    cache = tmp_path / "update-check.json"
    cache.write_text(json.dumps({
        "checked_at": updater.time.time(),
        "tag": "v99.0.0",
        "page_url": "https://example.test/release",
        "asset_names": [f"aksal-v99.0.0{suffix}"],
    }), encoding="utf-8")
    monkeypatch.setattr(updater, "_check_cache_path", lambda: cache)
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda **kwargs: pytest.fail("network was used"))
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    messages = []
    updater.notify_if_available(log=messages.append)
    assert any("99.0.0" in message for message in messages)
    assert any("aksal update" in message for message in messages)


def test_source_install_cannot_replace_itself(monkeypatch):
    monkeypatch.delattr(updater.sys, "frozen", raising=False)
    with pytest.raises(RuntimeError, match="packaged AKSAL"):
        updater._install_root()


def test_manifest_is_sorted_and_covers_top_level_payload(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "z.txt").write_text("z")
    (payload / "_internal").mkdir()
    manifest = updater._write_manifest(payload, tmp_path)
    assert manifest.read_text(encoding="utf-8").splitlines() == [
        "_internal", "z.txt"]


def test_install_latest_stages_verified_bundle_before_handoff(
        tmp_path, monkeypatch):
    asset_name, content, executable = native_archive()
    asset = {
        "name": asset_name,
        "browser_download_url": "https://example.test/aksal-archive",
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
    }
    latest = release("v99.0.0", [asset])
    install = tmp_path / "installed"
    (install / "_internal").mkdir(parents=True)
    (install / executable).write_bytes(b"old exe")
    cache = tmp_path / "cache"
    handed_off = {}

    monkeypatch.setattr(updater, "fetch_latest", lambda: latest)
    monkeypatch.setattr(updater, "_cache_release", lambda value: None)
    monkeypatch.setattr(updater, "select_asset", lambda value: asset)
    monkeypatch.setattr(updater, "_install_root", lambda: install)
    monkeypatch.setattr(updater, "cache_home", lambda: cache)
    monkeypatch.setattr(updater, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        updater, "_download", lambda url, target, timeout=0:
        target.write_bytes(content))

    def launch(root, payload, work, manifest, tag):
        handed_off.update(root=root, payload=payload, work=work,
                          names=manifest.read_text().splitlines(), tag=tag)

    monkeypatch.setattr(updater, "_launch_helper", launch)
    messages = []
    assert updater.install_latest(log=messages.append)
    assert handed_off["root"] == install
    assert (handed_off["payload"] / executable).read_bytes() == b"new exe"
    assert handed_off["names"] == ["_internal", executable]
    assert handed_off["tag"] == "v99.0.0"
    assert not (handed_off["work"] / asset["name"]).exists()
    assert any("will be installed" in message for message in messages)


def test_check_only_does_not_require_a_packaged_install(monkeypatch):
    latest = release("v99.0.0")
    monkeypatch.setattr(updater, "fetch_latest", lambda: latest)
    monkeypatch.setattr(updater, "_cache_release", lambda value: None)
    monkeypatch.setattr(
        updater, "_install_root",
        lambda: pytest.fail("check-only tried to modify the installation"))
    messages = []
    assert not updater.install_latest(check_only=True, log=messages.append)
    assert any("available" in message for message in messages)


def test_no_published_release_has_a_clear_error(monkeypatch):
    error = urllib.error.HTTPError(
        updater.RELEASE_API, 404, "Not Found", {}, None)
    monkeypatch.setattr(updater, "fetch_latest", lambda: (_ for _ in ()).throw(error))
    with pytest.raises(RuntimeError, match="no stable published"):
        updater.install_latest(check_only=True)


def test_native_update_helper_has_valid_shell_syntax(tmp_path):
    if sys.platform == "win32":
        shell = shutil.which("powershell.exe")
        if not shell:
            pytest.skip("Windows PowerShell is unavailable")
        helper = tmp_path / "helper.ps1"
        helper.write_text(updater._WINDOWS_HELPER, encoding="utf-8-sig")
        literal = str(helper).replace("'", "''")
        check = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{literal}',[ref]$tokens,[ref]$errors) > $null; "
            "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }")
        result = subprocess.run(
            [shell, "-NoProfile", "-Command", check],
            capture_output=True, text=True)
    else:
        helper = tmp_path / "helper.sh"
        helper.write_text(updater._POSIX_HELPER, encoding="utf-8")
        result = subprocess.run(
            ["/bin/sh", "-n", str(helper)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
