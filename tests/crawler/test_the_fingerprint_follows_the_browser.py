"""The fingerprint profile follows the Chrome actually running, and its zone.

Measured in a production pod, 2026-10-15, Chrome 155 with the macOS profile:

    navigator.userAgent              ... Chrome/143.0.0.0 ...
    navigator.userAgentData.brands   []         <- the metadata was skipped
    navigator.userAgentData.platform ""
    time zone                        UTC        <- beside a Missouri egress

The profile pinned Chrome 143, a `major >= 143` gate turned the client hints
off for every later Chrome, and no time zone was set. reCAPTCHA scored the
pendoreillerivervalley.com login from this browser as spam.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.crawler import ContentExtractor
from src.crawler.fingerprint_profile import load_fingerprint_profile, matched_to_browser

PROFILE = Path("fingerprints/macos-default.json")
CHROME_155 = "Chrome/155.0.8059.79"


def _profile():
    return load_fingerprint_profile(PROFILE)


class TestTheProfileMatchesTheBrowser:
    def test_the_user_agent_carries_the_running_major(self):
        matched = matched_to_browser(_profile(), CHROME_155)
        assert "Chrome/155.0.0.0" in matched.user_agent
        assert "Chrome/143" not in matched.user_agent

    def test_the_client_hints_carry_it_too(self):
        meta = matched_to_browser(_profile(), CHROME_155).client_hints[
            "userAgentMetadata"
        ]
        brands = {b["brand"]: b["version"] for b in meta["brands"]}
        full = {b["brand"]: b["version"] for b in meta["fullVersionList"]}
        assert brands["Google Chrome"] == brands["Chromium"] == "155"
        assert full["Google Chrome"] == full["Chromium"] == "155.0.8059.79"
        assert brands["Not A Brand"] == "99"

    def test_the_injected_script_agrees(self):
        script = matched_to_browser(_profile(), CHROME_155).script or ""
        assert "Chrome/155.0.0.0" in script
        assert "Chrome/143" not in script

    def test_an_unknown_browser_leaves_the_profile_alone(self):
        profile = _profile()
        assert matched_to_browser(profile, None) is profile
        assert matched_to_browser(profile, "HeadlessThing/1") is profile

    def test_the_loaded_profile_is_not_changed(self):
        profile = _profile()
        matched_to_browser(profile, CHROME_155)
        assert "Chrome/143.0.0.0" in profile.user_agent


def test_the_profile_names_the_egress_time_zone():
    """Both egresses are in Missouri: the residential Squid and the Mizzou one."""
    assert json.loads(PROFILE.read_text())["timezone"] == "America/Chicago"
    assert _profile().timezone == "America/Chicago"


class _Driver:
    def __init__(self, product=CHROME_155):
        self.product = product
        self.calls: list[tuple[str, dict]] = []

    def execute_cdp_cmd(self, cmd, params):
        self.calls.append((cmd, params))
        if cmd == "Browser.getVersion":
            return {"product": self.product}
        return {}

    def execute_script(self, script):
        return None


def _applied(product=CHROME_155):
    extractor = ContentExtractor.__new__(ContentExtractor)
    extractor._fingerprint_profile = _profile()
    driver = _Driver(product)
    extractor._apply_fingerprint_profile(driver)
    return driver.calls


class TestTheDriverIsGivenIt:
    def test_the_override_carries_the_running_version(self):
        overrides = [p for c, p in _applied() if c == "Network.setUserAgentOverride"]
        first = overrides[0]
        assert "Chrome/155.0.0.0" in first["userAgent"]
        brands = {
            b["brand"]: b["version"] for b in first["userAgentMetadata"]["brands"]
        }
        assert brands["Google Chrome"] == "155"

    def test_the_time_zone_is_set(self):
        assert ("Emulation.setTimezoneOverride", {"timezoneId": "America/Chicago"}) in (
            _applied()
        )
