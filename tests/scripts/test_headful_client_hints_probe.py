import pytest

import scripts.headful_client_hints_probe as probe

pytestmark = pytest.mark.local_scripts


def test_make_payload_defaults():
    p = probe.make_payload("UA-1")
    assert p["userAgent"] == "UA-1"
    assert p["platform"] == "Win32"
    assert "userAgentMetadata" in p
    assert p["userAgentMetadata"]["platform"] == "Win32"


def test_align_payload_platform_changes_both():
    p = probe.make_payload("UA-1")
    p2 = probe.align_payload_platform(p, "MacIntel")
    assert p2["platform"] == "MacIntel"
    assert p2["userAgentMetadata"]["platform"] == "MacIntel"


def test_align_payload_noop_on_none():
    p = probe.make_payload("UA-1")
    p3 = probe.align_payload_platform(p, None)
    assert p3["platform"] == "Win32"
