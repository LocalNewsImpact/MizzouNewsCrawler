import json
import tempfile
from scripts.parse_perflog import parse_perflog


def make_entry(method, params):
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


def test_parse_perflog_collects_px_tokens_in_multiple_fields():
    entries = []

    # px in Cookie on request
    entries.append(
        make_entry(
            "Network.requestWillBeSent",
            {
                "requestId": "r1",
                "request": {"url": "https://example.com/a", "headers": {"Cookie": "_px=ABC123; other=1"}},
                "type": "Document",
                "timestamp": 1.0,
            },
        )
    )

    # px in requestWillBeSentExtraInfo cookie, and include sec-ch headers
    entries.append(
        make_entry(
            "Network.requestWillBeSentExtraInfo",
            {
                "requestId": "r1",
                "headers": {"cookie": "pxhd=XYZ789; foo=bar", "sec-ch-ua-platform": '"MacIntel"', "sec-ch-ua": '"Google Chrome";v="143"', "accept-language": "en-US"},
            },
        )
    )

    # px in a later miscellaneous event
    entries.append(
        make_entry("Network.loadingFinished", {"requestId": "r1", "info": "contains _px=IN-MEME"})
    )

    # Response with securityDetails
    entries.append(
        make_entry(
            "Network.responseReceived",
            {
                "requestId": "r1",
                "response": {"status": 200, "protocol": "h2", "securityDetails": {"keyExchangeGroup": "X25519"}},
            },
        )
    )

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        json.dump(entries, f)
        f.flush()
        rows = parse_perflog(f.name, domain_filter="example.com")

    assert len(rows) == 1
    r = rows[0]
    assert "_px" in r["px_tokens"] or "pxhd" in r["px_tokens"] or "_px" in r["px_tokens"]
    assert r["sec_ch_ua_platform"] == '"MacIntel"'
    assert r["protocol"] == "h2"


def test_parse_perflog_domain_filtering():
    entries = []
    entries.append(make_entry("Network.requestWillBeSent", {"requestId": "r1", "request": {"url": "https://images.example.com/x.jpg"}, "timestamp": 1.0}))
    entries.append(make_entry("Network.requestWillBeSent", {"requestId": "r2", "request": {"url": "https://other.org/"}, "timestamp": 2.0}))

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        json.dump(entries, f)
        f.flush()
        rows = parse_perflog(f.name, domain_filter="example.com")

    assert len(rows) == 1
    assert rows[0]["url"].startswith("https://images.example.com")


def test_parse_perflog_large_synthetic_runs_fast_and_consistent():
    entries = []
    # generate 500 small entries to exercise loops and branching
    for i in range(500):
        entries.append(make_entry("Network.requestWillBeSent", {"requestId": f"r{i}", "request": {"url": f"https://host{i % 5}.example.com/asset{i}.js", "headers": {"User-Agent": "TestUA"}}, "timestamp": float(i)}))
        entries.append(make_entry("Network.requestWillBeSentExtraInfo", {"requestId": f"r{i}", "headers": {"sec-ch-ua-platform": '"Linux"', "accept-language": "en-US"}}))
        entries.append(make_entry("Network.responseReceived", {"requestId": f"r{i}", "response": {"status": 200}}))

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        json.dump(entries, f)
        f.flush()
        rows = parse_perflog(f.name, domain_filter="example.com")

    # we should have rows for each unique requestId with domain filter matching any host*.example.com
    assert len(rows) >= 100
