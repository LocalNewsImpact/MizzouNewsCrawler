import json
import tempfile

from scripts.parse_perflog import parse_perflog


def make_entry(method, params):
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


def test_parse_perflog_minimal():
    # Build minimal perf log with requestWillBeSent, requestWillBeSentExtraInfo, responseReceived
    entries = []

    entries.append(
        make_entry(
            "Network.requestWillBeSent",
            {
                "requestId": "r1",
                "request": {
                    "url": "https://example.com/article",
                    "headers": {
                        "User-Agent": "TestUA/1.0",
                        "Cookie": "_px=ABC123; other=1",
                    },
                },
                "type": "Document",
                "timestamp": 1.0,
            },
        )
    )

    entries.append(
        make_entry(
            "Network.requestWillBeSentExtraInfo",
            {
                "requestId": "r1",
                "headers": {
                    "user-agent": "TestUA/1.0",
                    "sec-ch-ua-platform": '"MacIntel"',
                    "sec-ch-ua": '"Google Chrome";v="143"',
                    "accept-language": "en-US",
                },
            },
        )
    )

    entries.append(
        make_entry(
            "Network.responseReceived",
            {
                "requestId": "r1",
                "response": {
                    "status": 200,
                    "protocol": "h2",
                    "securityDetails": {"keyExchangeGroup": "X25519"},
                },
            },
        )
    )

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        json.dump(entries, f)
        f.flush()
        rows = parse_perflog(f.name, domain_filter="example.com")

    assert len(rows) == 1
    r = rows[0]
    assert r["url"] == "https://example.com/article"
    assert r["ua"] == "TestUA/1.0"
    assert r["sec_ch_ua_platform"] == '"MacIntel"'
    assert r["sec_ch_ua"].startswith('"Google Chrome"')
    assert "_px" in r["px_tokens"] or "pxhd" in r["px_tokens"]
    assert r["status"] == 200
    assert r["protocol"] == "h2"
    assert r["keyExchangeGroup"] == "X25519"
