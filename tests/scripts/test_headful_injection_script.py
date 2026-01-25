import scripts.headful_client_hints_probe as probe


def test_build_injection_script_contains_platform_and_brands():
    script = probe.build_injection_script(
        platform="MacIntel",
        brands=[{"brand": "Google Chrome", "version": "143"}],
        full_version="143.0.0.0",
    )
    assert "MacIntel" in script
    assert '"Google Chrome"' in script
    assert "fullVersionList" in script
    assert "getHighEntropyValues" in script


def test_make_payload_and_align():
    p = probe.make_payload("UA-TEST", platform="Win32", accept_language="en-US")
    assert p["platform"] == "Win32"
    p2 = probe.align_payload_platform(p, "MacIntel")
    assert p2["platform"] == "MacIntel"
    assert p2["userAgentMetadata"]["platform"] == "MacIntel"
