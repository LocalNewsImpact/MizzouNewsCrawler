#!/usr/bin/env python3
import argparse
import csv
from urllib.parse import urlparse
from datetime import datetime


def parse_date(s: str) -> datetime:
    if len(s) == 10:
        return datetime.fromisoformat(s + "T00:00:00")
    return datetime.fromisoformat(s)


def main():
    p = argparse.ArgumentParser(description="Build domain allowlist from strong-tier telemetry mismatches")
    p.add_argument("--csv", required=True, help="Input CSV (telemetry_mismatches_decjan.csv)")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD (exclusive)")
    p.add_argument("--out", required=True, help="Output allowlist file path")
    args = p.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)

    strong = set()
    with open(args.csv, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            pd = row.get("publish_date")
            try:
                pub = datetime.fromisoformat(pd) if pd else None
            except ValueError:
                pub = None
            if pub is None or pub < start or pub >= end:
                continue
            status = (row.get("status") or "").lower()
            if status == "wire":
                continue
            wcs = (row.get("wire_check_status") or "").lower()
            if wcs not in {"pending", "complete"}:
                continue
            tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
            if any(t == "content_type" or t.startswith("content_type:") for t in tags):
                host = urlparse(row.get("url") or "").netloc.lower()
                if host:
                    strong.add(host)

    with open(args.out, "w", encoding="utf-8") as f:
        for h in sorted(strong):
            f.write(h + "\n")

    print(f"Wrote {len(strong)} domains to {args.out}")


if __name__ == "__main__":
    main()
