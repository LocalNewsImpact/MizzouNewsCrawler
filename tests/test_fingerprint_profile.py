import json

import pytest

from src.crawler.fingerprint_profile import (
    load_fingerprint_profile,
    prepare_user_data_dir,
)


def test_load_fingerprint_profile_returns_none_when_missing(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setenv("SELENIUM_FINGERPRINT_PATH", str(missing))
    assert load_fingerprint_profile() is None


def test_load_fingerprint_profile_builds_script(monkeypatch, tmp_path):
    payload = {
        "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/143.0.0.0",
        "navigator": {
            "language": "en-US",
            "languages": ["en-US", "en"],
            "platform": "MacIntel",
            "hardwareConcurrency": 10,
            "maxTouchPoints": 0,
        },
        "screen": {"width": 1728, "height": 1117},
        "webgl": {"webglVendor": "Google Inc.", "webglRenderer": "ANGLE"},
        "uaData": {
            "brands": [{"brand": "Google Chrome", "version": "143"}],
            "platform": "macOS",
        },
    }
    profile_path = tmp_path / "fingerprint.json"
    profile_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("SELENIUM_FINGERPRINT_PATH", str(profile_path))

    profile = load_fingerprint_profile()

    assert profile is not None
    assert profile.user_agent == payload["userAgent"]
    assert profile.screen_size == (1728, 1117)
    assert profile.accept_language == "en-US,en;q=0.9"
    assert profile.client_hints is not None
    assert "navigator" in (profile.script or "")


def test_prepare_user_data_dir_no_source(tmp_path):
    assert prepare_user_data_dir(None, workdir=tmp_path) is None


def test_prepare_user_data_dir_writable_source(tmp_path):
    profile_dir = tmp_path / "Profile 1"
    (profile_dir / "Default").mkdir(parents=True)
    (profile_dir / "Default" / "Preferences").write_text("{}", encoding="utf-8")

    resolved = prepare_user_data_dir(profile_dir, workdir=tmp_path)
    assert resolved == profile_dir


def test_prepare_user_data_dir_copies_when_readonly(tmp_path):
    profile_dir = tmp_path / "Profile 1"
    (profile_dir / "Default").mkdir(parents=True)
    (profile_dir / "Default" / "Preferences").write_text("{}", encoding="utf-8")

    scratch = tmp_path / "scratch"
    resolved = prepare_user_data_dir(profile_dir, readonly=True, workdir=scratch)

    assert resolved != profile_dir
    assert (resolved / "Default" / "Preferences").is_file()


def test_prepare_user_data_dir_detects_nonwritable_source(tmp_path):
    profile_dir = tmp_path / "Profile ReadOnly"
    (profile_dir / "Default").mkdir(parents=True)
    prefs = profile_dir / "Default" / "Preferences"
    prefs.write_text("{}", encoding="utf-8")

    profile_dir.chmod(0o555)
    scratch = tmp_path / "scratch"
    resolved = prepare_user_data_dir(profile_dir, workdir=scratch)
    profile_dir.chmod(0o755)

    assert resolved != profile_dir
    assert (resolved / "Default" / "Preferences").read_text(encoding="utf-8") == "{}"


def test_prepare_user_data_dir_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        prepare_user_data_dir(tmp_path / "does-not-exist", workdir=tmp_path)


def test_load_fingerprint_profile_accept_language_fallback(monkeypatch, tmp_path):
    payload = {
        "userAgent": "Mozilla/5.0",
        "navigator": {"language": "en-GB", "platform": "MacIntel"},
        "screen": {"width": 100, "height": 200},
    }
    profile_path = tmp_path / "fingerprint.json"
    profile_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("SELENIUM_FINGERPRINT_PATH", str(profile_path))

    profile = load_fingerprint_profile()

    assert profile is not None
    assert profile.languages == ["en-GB"]
    assert profile.accept_language == "en-GB"


def test_load_fingerprint_profile_without_ua_data_sets_client_hints(
    monkeypatch, tmp_path
):
    payload = {
        "userAgent": "Mozilla/5.0",
        "navigator": {
            "language": "en-US",
            "platform": "MacIntel",
        },
    }
    profile_path = tmp_path / "fingerprint.json"
    profile_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("SELENIUM_FINGERPRINT_PATH", str(profile_path))

    profile = load_fingerprint_profile()

    assert profile is not None
    assert profile.client_hints == {
        "platform": "MacIntel",
        "acceptLanguage": "en-US",
    }
