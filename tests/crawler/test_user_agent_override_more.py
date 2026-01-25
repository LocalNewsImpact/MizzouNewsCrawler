from copy import deepcopy
from pathlib import Path

import pytest

from src.crawler import ContentExtractor
from src.crawler.fingerprint_profile import FingerprintProfile


class FakeDriver:
    def __init__(self, responses=None, fail_hook=None):
        self.calls = []
        self.responses = responses or {}
        self.fail_hook = fail_hook
        # Default flag is True (meaning try full payload)
        self._supports_user_agent_metadata = True
        self._user_agent_metadata_version_checked = False

    def execute_cdp_cmd(self, cmd, params):
        # record call
        self.calls.append({"cmd": cmd, "params": params})
        # allow custom failure behavior
        if self.fail_hook:
            self.fail_hook(cmd, params)
        # support returning Browser.getVersion
        if cmd in self.responses:
            return deepcopy(self.responses[cmd])
        return None


def make_fp():
    return FingerprintProfile(
        source_path=Path("dummy"),
        raw={},
        user_agent="UA-from-profile",
        client_hints={
            "platform": "Win32",
            "userAgentMetadata": {
                "platform": "Win32",
                "brands": [{"brand": "Google Chrome", "version": "143"}],
                "mobile": False,
            },
            "acceptLanguage": "en-US",
        },
        accept_language="en-US",
        languages=["en-US"],
        screen_size=(1366, 768),
        script=None,
    )


def test_full_payload_success_sets_extra_headers():
    extractor = ContentExtractor()
    extractor._fingerprint_profile = make_fp()
    fake = FakeDriver(responses={"Browser.getVersion": {"product": "Chrome/142.0.0.0"}})

    extractor._set_user_agent_override(fake, "Windows UA string")

    # Ensure an initial Network.setUserAgentOverride with full payload was attempted
    assert any(
        c["cmd"] == "Network.setUserAgentOverride"
        and "userAgentMetadata" in c["params"]
        for c in fake.calls
    )
    # Also ensure extra headers were set after success
    assert any(c["cmd"] == "Network.setExtraHTTPHeaders" for c in fake.calls)


def test_full_payload_invalid_parameters_marks_driver_and_falls_back():
    extractor = ContentExtractor()
    extractor._fingerprint_profile = make_fp()

    def fail_hook(cmd, params):
        if cmd == "Network.setUserAgentOverride" and "userAgentMetadata" in params:
            raise Exception("Invalid parameters: userAgentMetadata not supported")

    fake = FakeDriver(
        responses={"Browser.getVersion": {"product": "Chrome/142.0.0.0"}},
        fail_hook=fail_hook,
    )

    extractor._set_user_agent_override(fake, "Windows UA string")

    # driver should have been marked as not supporting userAgentMetadata
    assert getattr(fake, "_supports_user_agent_metadata", False) is False
    # There should be at least one reduced payload call (no userAgentMetadata)
    assert any(
        c["cmd"] == "Network.setUserAgentOverride"
        and "userAgentMetadata" not in c["params"]
        for c in fake.calls
    )


def test_full_payload_other_exception_falls_back_but_does_not_mark():
    extractor = ContentExtractor()
    extractor._fingerprint_profile = make_fp()

    def fail_hook(cmd, params):
        if cmd == "Network.setUserAgentOverride" and "userAgentMetadata" in params:
            raise Exception("Some transient CDP error")

    fake = FakeDriver(
        responses={"Browser.getVersion": {"product": "Chrome/142.0.0.0"}},
        fail_hook=fail_hook,
    )

    extractor._set_user_agent_override(fake, "Windows UA string")

    # Should have attempted reduced payload
    assert any(
        c["cmd"] == "Network.setUserAgentOverride"
        and "userAgentMetadata" not in c["params"]
        for c in fake.calls
    )
    # But not marked as unsupported because message didn't contain 'invalid parameters'
    assert getattr(fake, "_supports_user_agent_metadata", True) is True


def test_version_check_skips_full_payload_for_chrome_143():
    extractor = ContentExtractor()
    extractor._fingerprint_profile = make_fp()

    class FakeDriverWithVersion(FakeDriver):
        def __init__(self):
            super().__init__(
                responses={"Browser.getVersion": {"product": "Chrome/143.0.7499.169"}}
            )

    fake = FakeDriverWithVersion()

    extractor._set_user_agent_override(fake, "Windows UA string")

    # Ensure no call attempted with userAgentMetadata (we skip full payload)
    assert not any(
        c["cmd"] == "Network.setUserAgentOverride"
        and "userAgentMetadata" in c["params"]
        for c in fake.calls
    )


def test_emulation_fallback_when_reduced_fails():
    extractor = ContentExtractor()
    extractor._fingerprint_profile = make_fp()

    def fail_hook(cmd, params):
        if cmd == "Network.setUserAgentOverride":
            # fail both full and reduced payloads
            raise Exception("Network override failed")

    fake = FakeDriver(fail_hook=fail_hook)

    extractor._set_user_agent_override(fake, "Windows UA string")

    # Emulation fallback should have been attempted
    assert any(c["cmd"] == "Emulation.setUserAgentOverride" for c in fake.calls)


def test_final_ua_override_attempt_if_all_fallbacks_fail():
    extractor = ContentExtractor()
    extractor._fingerprint_profile = None

    def fail_hook(cmd, params):
        # Fail everything except final minimal UA override
        if cmd in ("Network.setUserAgentOverride", "Emulation.setUserAgentOverride"):
            # But allow the final minimal UA override (no userAgentMetadata)
            if isinstance(params, dict) and params.keys() == {"userAgent"}:
                return
            raise Exception("All override attempts failed")

    fake = FakeDriver(fail_hook=fail_hook)

    extractor._set_user_agent_override(fake, "UA-only")

    # The final call should include only the userAgent key
    assert any(
        c["cmd"] == "Network.setUserAgentOverride"
        and set(c["params"].keys()) == {"userAgent"}
        for c in fake.calls
    )
