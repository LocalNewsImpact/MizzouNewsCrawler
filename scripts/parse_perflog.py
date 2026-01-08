#!/usr/bin/env python3
"""Compact parser for Chrome performance logs (Selenium "performance" logs).

Usage examples:
  ./scripts/parse_perflog.py /tmp/selenium_perflog.json --domain httpbin.org --format csv

Outputs a compact table (CSV) with: timestamp, requestId, url, resourceType,
userAgent (from extra info if present), sec-ch-ua-platform, sec-ch-ua, accept-language,
px_tokens, status, protocol, keyExchangeGroup

This tool avoids dumping huge logs and extracts PerimeterX signals and header parity
so they can be inspected quickly.
"""

import argparse
import json
import re
import csv
import sys
from urllib.parse import urlparse

PX_KEYS = ("pxhd", "pxvid", "pxcts", "_px", "_pxhd")
PX_RE = re.compile(r"(pxhd|pxvid|pxcts|_px[^\s=;:,\"']*)[=:\"']?([A-Za-z0-9_-]{6,})", re.I)


def parse_perflog(path, domain_filter=None):
    with open(path, "r") as f:
        data = json.load(f)

    # Map requestId -> record
    records = {}

    def ensure_record(rid):
        if rid not in records:
            records[rid] = {
                "requestId": rid,
                "url": None,
                "resourceType": None,
                "timestamp": None,
                "ua": None,
                "ua_extra": None,
                "sec_ch_ua_platform": None,
                "sec_ch_ua": None,
                "accept_language": None,
                "px_tokens": set(),
                "status": None,
                "protocol": None,
                "keyExchangeGroup": None,
            }
        return records[rid]

    def extract_px_from_text(text):
        found = set()
        if not text:
            return found
        for m in PX_RE.finditer(text):
            found.add((m.group(1), m.group(2)))
        return found

    for entry in data:
        msg = entry.get("message")
        parsed = None
        try:
            if isinstance(msg, str):
                parsed = json.loads(msg)
            elif isinstance(msg, dict):
                parsed = msg
            else:
                continue
        except Exception:
            # Some entries may not be JSON strings
            continue

        inner = parsed.get("message") if isinstance(parsed, dict) and "message" in parsed else parsed
        method = inner.get("method") if isinstance(inner, dict) else None
        params = inner.get("params", {}) if isinstance(inner, dict) else {}

        text_blob = json.dumps(inner)
        px_found = extract_px_from_text(text_blob)

        if method == "Network.requestWillBeSent":
            rid = params.get("requestId")
            if not rid:
                continue
            rec = ensure_record(rid)
            req = params.get("request", {})
            rec["url"] = req.get("url") or rec.get("url")
            rec["resourceType"] = params.get("type") or rec.get("resourceType")
            rec["timestamp"] = params.get("timestamp") or rec.get("timestamp")
            hdrs = req.get("headers", {}) or {}
            # headers may have 'User-Agent' or 'user-agent' depending on event
            ua = hdrs.get("User-Agent") or hdrs.get("user-agent")
            if ua:
                rec["ua"] = ua
            # cookies
            cookie = hdrs.get("Cookie") or hdrs.get("cookie")
            if cookie:
                for k in PX_KEYS:
                    for part in cookie.split(";"):
                        if k in part:
                            rec["px_tokens"].add((k, part.strip()))
            # find px in the full text
            for k, v in px_found:
                rec["px_tokens"].add((k, v))

        elif method == "Network.requestWillBeSentExtraInfo":
            rid = params.get("requestId")
            if not rid:
                continue
            rec = ensure_record(rid)
            hdrs = params.get("headers", {}) or {}
            # headers here often are lowercase
            ua = hdrs.get("user-agent") or hdrs.get("User-Agent")
            if ua:
                rec["ua_extra"] = ua
            scp = hdrs.get("sec-ch-ua-platform")
            if scp:
                rec["sec_ch_ua_platform"] = scp
            scua = hdrs.get("sec-ch-ua")
            if scua:
                rec["sec_ch_ua"] = scua
            al = hdrs.get("accept-language")
            if al:
                rec["accept_language"] = al
            # merge px tokens
            cookie = hdrs.get("cookie") or hdrs.get("Cookie")
            if cookie:
                for m in PX_RE.finditer(cookie):
                    rec["px_tokens"].add((m.group(1), m.group(2)))
            for k, v in px_found:
                rec["px_tokens"].add((k, v))

        elif method == "Network.responseReceived":
            rid = params.get("requestId")
            if not rid:
                continue
            rec = ensure_record(rid)
            resp = params.get("response", {})
            rec["status"] = resp.get("status") or rec.get("status")
            sec = resp.get("securityDetails") or {}
            if sec:
                rec["protocol"] = resp.get("protocol") or rec.get("protocol")
                rec["keyExchangeGroup"] = sec.get("keyExchangeGroup") or rec.get("keyExchangeGroup")
            for k, v in px_found:
                rec["px_tokens"].add((k, v))

        elif method == "Network.responseReceivedExtraInfo":
            rid = params.get("requestId")
            if not rid:
                continue
            rec = ensure_record(rid)
            hdrs = params.get("headers", {}) or {}
            for k in ("content-length", "content-type"):
                if hdrs.get(k):
                    pass
            for k, v in px_found:
                rec["px_tokens"].add((k, v))

        else:
            # still look for px tokens in other events
            if px_found and 'requestId' in params:
                rid = params.get('requestId')
                rec = ensure_record(rid)
                for k, v in px_found:
                    rec["px_tokens"].add((k, v))

    # Prepare output: flatten records and apply domain filter
    rows = []
    for rid, rec in records.items():
        url = rec.get("url") or ""
        if domain_filter:
            p = urlparse(url)
            if domain_filter not in (p.netloc or "") and domain_filter not in url:
                continue
        px_list = ",".join(f"{k}={v}" for k, v in sorted(rec["px_tokens"])) if rec["px_tokens"] else ""
        row = {
            "timestamp": rec.get("timestamp"),
            "requestId": rid,
            "url": rec.get("url"),
            "resourceType": rec.get("resourceType"),
            "ua": rec.get("ua") or rec.get("ua_extra"),
            "sec_ch_ua_platform": rec.get("sec_ch_ua_platform"),
            "sec_ch_ua": rec.get("sec_ch_ua"),
            "accept_language": rec.get("accept_language"),
            "px_tokens": px_list,
            "status": rec.get("status"),
            "protocol": rec.get("protocol"),
            "keyExchangeGroup": rec.get("keyExchangeGroup"),
        }
        rows.append(row)

    # sort rows by timestamp if present
    rows.sort(key=lambda r: (r.get("timestamp") or 0))
    return rows


def main():
    parser = argparse.ArgumentParser(description="Parse Chrome performance log and extract header parity + PX signals")
    parser.add_argument("input", help="Path to performance log JSON (e.g., /tmp/selenium_perflog.json)")
    parser.add_argument("--domain", help="Filter by domain (e.g., httpbin.org)")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--output", help="Output file path (defaults to stdout)")
    args = parser.parse_args()

    rows = parse_perflog(args.input, domain_filter=args.domain)

    if args.format == "json":
        out = args.output
        if out:
            with open(out, "w") as f:
                json.dump(rows, f, indent=2)
        else:
            print(json.dumps(rows, indent=2))
        return

    # CSV output
    fieldnames = ["timestamp", "requestId", "url", "resourceType", "ua", "sec_ch_ua_platform", "sec_ch_ua", "accept_language", "px_tokens", "status", "protocol", "keyExchangeGroup"]
    if args.output:
        f = open(args.output, "w")
    else:
        f = sys.stdout
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: (r.get(k) if r.get(k) is not None else "") for k in fieldnames})
    if args.output:
        f.close()


if __name__ == "__main__":
    main()
