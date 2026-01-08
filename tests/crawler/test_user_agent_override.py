from pathlib import Path

from src.crawler import ContentExtractor
from src.crawler.fingerprint_profile import FingerprintProfile


class FakeDriver:
    def __init__(self):
        self.calls = []
        # Optional hook: a callable (cmd, params) -> raise Exception to simulate failures
        self.fail_hook = None

    def execute_cdp_cmd(self, cmd, params):
        if self.fail_hook:
            self.fail_hook(cmd, params)
        self.calls.append({"cmd": cmd, "params": params})


def test_set_user_agent_override_includes_client_hints():
    extractor = ContentExtractor()
    fp = FingerprintProfile(
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
        },
        accept_language="en-US",
        languages=["en-US"],
        screen_size=(1366, 768),
        script=None,
    )
    extractor._fingerprint_profile = fp
    fake = FakeDriver()

    extractor._set_user_agent_override(fake, "Windows UA string")

    assert fake.calls, "Expected CDP call(s)"
    # Browser.getVersion may be invoked for proactive capability checks; find the UA override call
    assert any(c["cmd"] == "Network.setUserAgentOverride" for c in fake.calls)
    call = next(c for c in fake.calls if c["cmd"] == "Network.setUserAgentOverride")
    assert call["params"]["userAgent"] == "Windows UA string"
    assert call["params"].get("platform") == "Win32"
    assert "userAgentMetadata" in call["params"]


def test_set_user_agent_override_without_profile_only_user_agent():
    extractor = ContentExtractor()
    extractor._fingerprint_profile = None
    fake = FakeDriver()

    extractor._set_user_agent_override(fake, "UA-only")

    assert fake.calls[-1]["params"] == {"userAgent": "UA-only"}


def test_set_user_agent_override_fallback_on_invalid_userAgentMetadata():
    extractor = ContentExtractor()
    fp = FingerprintProfile(
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
    extractor._fingerprint_profile = fp

    def fail_hook(cmd, params):
        # Simulate ChromeDriver rejecting userAgentMetadata in the first Network call
        if cmd == "Network.setUserAgentOverride" and "userAgentMetadata" in params:
            raise Exception("Invalid parameters")

    fake = FakeDriver()
    fake.fail_hook = fail_hook

    extractor._set_user_agent_override(fake, "Windows UA string")

    # Ensure we attempted a reduced payload or alternative method:
    # Look for either a second Network.setUserAgentOverride without userAgentMetadata,
    # an Emulation.setUserAgentOverride, or Network.setExtraHTTPHeaders being called.
    cmds = [c["cmd"] for c in fake.calls]
    assert (
        any(c == "Emulation.setUserAgentOverride" for c in cmds)
        or any(c == "Network.setExtraHTTPHeaders" for c in cmds)
        or any(
            c == "Network.setUserAgentOverride"
            and "userAgentMetadata" not in obj["params"]
            for obj, c in zip(fake.calls, cmds, strict=False)
        )
    ), f"Expected fallback calls, got: {fake.calls}"


def test_set_user_agent_override_marks_and_skips_full_payload_on_subsequent_calls():
    extractor = ContentExtractor()
    fp = FingerprintProfile(
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
    extractor._fingerprint_profile = fp

    def fail_hook(cmd, params):
        # Simulate Device returning invalid parameters for userAgentMetadata
        if cmd == "Network.setUserAgentOverride" and "userAgentMetadata" in params:
            raise Exception("Invalid parameters")

    fake = FakeDriver()
    fake.fail_hook = fail_hook

    # First call should set the driver flag indicating no support
    extractor._set_user_agent_override(fake, "Windows UA string")
    assert getattr(fake, "_supports_user_agent_metadata", False) is False

    fake.calls.clear()

    # Second call should not attempt the full payload with userAgentMetadata
    extractor._set_user_agent_override(fake, "Windows UA string")

    # Ensure there are no calls containing userAgentMetadata
    assert not any("userAgentMetadata" in c.get("params", {}) for c in fake.calls)


def test_set_user_agent_override_skips_full_payload_on_chrome_143():
    extractor = ContentExtractor()
    fp = FingerprintProfile(
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
    extractor._fingerprint_profile = fp

    class FakeDriverWithVersion(FakeDriver):
        def execute_cdp_cmd(self, cmd, params):
            if cmd == "Browser.getVersion":
                return {"product": "Chrome/143.0.7499.169"}
            return super().execute_cdp_cmd(cmd, params)

    fake = FakeDriverWithVersion()

    extractor._set_user_agent_override(fake, "Windows UA string")

    # No call should include userAgentMetadata because version proactively disabled it
    assert not any(
        "userAgentMetadata" in c.get("params", {}) for c in fake.calls
    ), fake.calls
