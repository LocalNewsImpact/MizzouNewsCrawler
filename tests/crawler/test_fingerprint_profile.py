"""Loading a Chrome fingerprint profile and preparing its user-data directory.

The profile is what keeps a macOS User-Agent from shipping with
navigator.platform == "Win32"; these tests read one from disk and pin what
is derived from it -- the Accept-Language header, the screen size, the
client hints, the injected script -- and every way the loader declines
(missing file, not an object) without raising. The user-data-dir half
copies a read-only profile rather than letting Chrome write into a
Kubernetes secret mount.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from src.crawler import fingerprint_profile as fp

FULL_PROFILE = {
    "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/128",
    "navigator": {
        "platform": "MacIntel",
        "language": "en-US",
        "languages": ["en-US", "en", "fr"],
        "hardwareConcurrency": 8,
        "maxTouchPoints": 0,
        "deviceMemory": 8,
    },
    "screen": {
        "width": "1728",
        "height": 1117,
        "availWidth": 1728,
        "colorDepth": 30,
        "pixelDepth": None,
    },
    "webgl": {"webglVendor": "Apple Inc.", "webglRenderer": "Apple M2"},
    "uaData": {"platform": "macOS", "mobile": False},
}


@pytest.fixture
def profile_file(tmp_path: Path) -> Path:
    path = tmp_path / "macos.json"
    path.write_text(json.dumps(FULL_PROFILE), encoding="utf-8")
    return path


# --- load_fingerprint_profile -------------------------------------------------


def test_a_missing_file_is_none_and_warns_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(fp, "_WARNED_PATHS", set())
    missing = tmp_path / "nope.json"
    with caplog.at_level("INFO", logger=fp.__name__):
        assert fp.load_fingerprint_profile(missing) is None
        assert fp.load_fingerprint_profile(missing) is None
    notices = [r for r in caplog.records if "not found" in r.getMessage()]
    assert len(notices) == 1, "the missing-profile notice repeats on every load"
    assert missing in fp._WARNED_PATHS


def test_the_path_comes_from_the_environment_when_not_given(profile_file, monkeypatch):
    monkeypatch.setenv("SELENIUM_FINGERPRINT_PATH", str(profile_file))
    profile = fp.load_fingerprint_profile()
    assert profile is not None
    assert profile.source_path == profile_file


def test_the_default_path_is_the_image_layout(monkeypatch):
    monkeypatch.delenv("SELENIUM_FINGERPRINT_PATH", raising=False)
    monkeypatch.setattr(fp, "_WARNED_PATHS", set())
    # /app/fingerprints does not exist on a laptop; the loader must say so
    # quietly rather than raise.
    assert fp.load_fingerprint_profile() is None
    assert fp.DEFAULT_FINGERPRINT_PATH in fp._WARNED_PATHS


def test_a_file_that_is_not_an_object_is_none(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]")
    assert fp.load_fingerprint_profile(path) is None


def test_the_whole_profile_is_derived(profile_file):
    profile = fp.load_fingerprint_profile(profile_file)
    assert profile is not None
    assert profile.user_agent == FULL_PROFILE["userAgent"]
    assert profile.languages == ["en-US", "en", "fr"]
    assert profile.accept_language == "en-US,en;q=0.9,fr;q=0.8"
    assert profile.screen_size == (1728, 1117)
    assert profile.client_hints == {
        "userAgentMetadata": {"platform": "macOS", "mobile": False},
        "platform": "macOS",
        "acceptLanguage": "en-US",
    }
    assert profile.navigator_platform == "MacIntel"
    assert profile.webgl_vendor == "Apple Inc."
    assert profile.webgl_renderer == "Apple M2"
    assert profile.raw == FULL_PROFILE


def test_a_single_language_stands_in_for_the_list(tmp_path):
    path = tmp_path / "one.json"
    path.write_text(json.dumps({"navigator": {"language": "de-DE"}}))
    profile = fp.load_fingerprint_profile(path)
    assert profile is not None
    assert profile.languages == ["de-DE"]
    assert profile.accept_language == "de-DE"
    assert profile.user_agent is None
    assert profile.screen_size is None
    assert profile.client_hints == {"acceptLanguage": "de-DE"}


def test_an_empty_profile_has_no_platform_and_no_webgl(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("{}")
    profile = fp.load_fingerprint_profile(path)
    assert profile is not None
    assert profile.navigator_platform is None
    assert profile.webgl_vendor is None
    assert profile.webgl_renderer is None
    assert profile.client_hints is None
    assert profile.accept_language is None


def test_webgl_that_is_not_an_object_is_ignored():
    profile = fp.FingerprintProfile(
        source_path=Path("x"),
        raw={"webgl": "yes"},
        user_agent=None,
        client_hints=None,
        accept_language=None,
        languages=[],
        screen_size=None,
        script=None,
    )
    assert profile.webgl_vendor is None
    assert profile.webgl_renderer is None


# --- the pieces ---------------------------------------------------------------


@pytest.mark.parametrize(
    "screen, expected",
    [
        ({"width": 1920, "height": 1080}, (1920, 1080)),
        ({"width": "1920", "height": "1080"}, (1920, 1080)),
        ({"width": 1920}, None),
        ({}, None),
        ({"width": "wide", "height": 1080}, None),
        ({"width": 0, "height": 1080}, None),
        ({"width": 1920, "height": -1}, None),
    ],
)
def test_screen_size(screen, expected):
    assert fp._extract_screen_size(screen) == expected


def test_accept_language_quality_values_step_down_and_stop_at_a_tenth():
    header = fp._build_accept_language_header(
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"], None
    )
    assert header == (
        "a,b;q=0.9,c;q=0.8,d;q=0.7,e;q=0.6,f;q=0.5,g;q=0.4,h;q=0.3,"
        "i;q=0.2,j;q=0.1,k;q=0.1"
    )


def test_accept_language_falls_back_and_skips_blanks():
    assert fp._build_accept_language_header([], "en") == "en"
    assert fp._build_accept_language_header(["", "en", None], None) == "en"
    assert fp._build_accept_language_header([], None) is None


def test_client_hints_prefer_uadata_platform_over_navigator():
    assert fp._build_client_hints(
        {"uaData": {"platform": "macOS"}, "navigator": {"platform": "MacIntel"}}
    ) == {"userAgentMetadata": {"platform": "macOS"}, "platform": "macOS"}
    assert fp._build_client_hints(
        {"uaData": {"mobile": False}, "navigator": {"platform": "MacIntel"}}
    ) == {"userAgentMetadata": {"mobile": False}, "platform": "MacIntel"}
    # uaData that is not an object is not metadata.
    assert fp._build_client_hints({"uaData": "x", "navigator": {}}) is None


def test_the_script_defines_what_the_profile_has_and_nothing_else():
    script = fp._build_fingerprint_script(FULL_PROFILE)
    assert script is not None
    assert "define(navigator, 'userAgent'," in script
    assert "define(navigator, 'platform', \"MacIntel\");" in script
    assert 'define(navigator, \'languages\', ["en-US", "en", "fr"]);' in script
    assert "define(navigator, 'hardwareConcurrency', 8);" in script
    assert "define(screenObj, 'width', \"1728\");" in script
    assert "define(screenObj, 'colorDepth', 30);" in script
    assert "pixelDepth" not in script, "a null screen value must not be defined"
    assert "availHeight" not in script
    assert 'if (param === 37445) { return "Apple Inc."; }' in script
    assert 'if (param === 37446) { return "Apple M2"; }' in script
    assert script.startswith("(function() {") and script.endswith("})();")


def test_the_script_keeps_an_explicit_navigator_user_agent():
    script = fp._build_fingerprint_script(
        {"userAgent": "top", "navigator": {"userAgent": "nav"}}
    )
    assert script is not None
    assert "define(navigator, 'userAgent', \"nav\");" in script
    assert '"top"' not in script


def test_the_script_without_screen_or_webgl_has_neither_block():
    script = fp._build_fingerprint_script({"navigator": {"platform": "Linux"}})
    assert script is not None
    assert "screenObj" not in script
    assert "spoofWebGL" not in script


def test_the_script_spoofs_only_the_webgl_field_present():
    script = fp._build_fingerprint_script({"webgl": {"webglRenderer": "R"}})
    assert script is not None
    assert "37446" in script
    assert "37445" not in script


# --- prepare_user_data_dir ----------------------------------------------------


def test_no_source_means_no_directory():
    assert fp.prepare_user_data_dir(None) is None
    assert fp.prepare_user_data_dir("") is None


def test_a_missing_source_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        fp.prepare_user_data_dir(tmp_path / "gone")


def test_a_writable_profile_is_used_in_place(tmp_path):
    source = tmp_path / "profile"
    source.mkdir()
    assert fp.prepare_user_data_dir(source) == source


def test_readonly_forces_a_copy_even_when_writable(tmp_path):
    source = tmp_path / "profile"
    source.mkdir()
    (source / "Default").mkdir()
    (source / "Default" / "Preferences").write_text("{}")
    workdir = tmp_path / "scratch"

    copied = fp.prepare_user_data_dir(source, readonly=True, workdir=workdir)

    assert copied == workdir / "profile"
    assert (copied / "Default" / "Preferences").read_text() == "{}"
    assert copied != source


def test_a_stale_copy_is_replaced(tmp_path):
    source = tmp_path / "profile"
    source.mkdir()
    (source / "new").write_text("n")
    workdir = tmp_path / "scratch"
    stale = workdir / "profile"
    stale.mkdir(parents=True)
    (stale / "old").write_text("o")

    copied = fp.prepare_user_data_dir(source, readonly=True, workdir=workdir)

    assert copied == stale
    assert (copied / "new").exists()
    assert not (copied / "old").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")
def test_a_readonly_mount_is_copied(tmp_path):
    """The Kubernetes-secret case: a directory with no write bits."""
    source = tmp_path / "profile"
    source.mkdir()
    (source / "First Run").write_text("")
    source.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        copied = fp.prepare_user_data_dir(source, workdir=tmp_path / "scratch")
        assert copied == tmp_path / "scratch" / "profile"
        assert (copied / "First Run").exists()
    finally:
        source.chmod(0o755)


# --- _is_directory_writable ---------------------------------------------------


def test_writability_is_proven_by_a_probe_that_is_removed(tmp_path):
    assert fp._is_directory_writable(tmp_path) is True
    assert list(tmp_path.iterdir()) == [], "the probe file was left behind"


def test_a_file_is_judged_by_its_parent(tmp_path):
    inside = tmp_path / "file"
    inside.write_text("x")
    assert fp._is_directory_writable(inside) is True


def test_no_write_bits_is_readonly_without_probing(tmp_path, monkeypatch):
    target = tmp_path / "ro"
    target.mkdir()
    target.chmod(0o555)

    def no_probe(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("a directory with no write bits was probed")

    monkeypatch.setattr(fp.tempfile, "mkstemp", no_probe)
    try:
        assert fp._is_directory_writable(target) is False
    finally:
        target.chmod(0o755)


def test_a_vanished_directory_is_readonly(tmp_path):
    # A missing path is judged by its parent, so the parent has to be
    # missing too for the stat to fail.
    assert fp._is_directory_writable(tmp_path / "gone" / "deeper") is False


def test_a_failed_probe_is_readonly(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(fp.tempfile, "mkstemp", refuse)
    assert fp._is_directory_writable(tmp_path) is False
