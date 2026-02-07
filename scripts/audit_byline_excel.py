#!/usr/bin/env python3
"""
Audit a spreadsheet of examples to verify byline-tier wire detection.

Reads an Excel/CSV file, extracts URLs, fetches articles by URL from DB,
runs ContentTypeDetector, and reports detection tiers/providers.
"""

import sys
import argparse
import re

sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector


def extract_urls_from_dataframe(df):
    urls = set()
    for _, row in df.iterrows():
        for val in row.tolist():
            s = str(val) if val is not None else ""
            for u in re.findall(r"https?://[^\s)]+", s):
                urls.add(u.rstrip(".,);:"))
    return sorted(urls)


def main():
    parser = argparse.ArgumentParser(description="Audit byline detection from Excel/CSV examples")
    parser.add_argument("--file", required=True, help="Path to Excel/CSV file inside pod (e.g., /tmp/byline_errors.xlsx)")
    parser.add_argument("--limit", type=int, default=500, help="Limit URLs to audit")
    args = parser.parse_args()

    # Load file with pandas (supports Excel/CSV)
    import pandas as pd
    try:
        df = pd.read_excel(args.file, header=None)
    except Exception:
        df = pd.read_csv(args.file, header=None)

    urls = extract_urls_from_dataframe(df)
    if not urls:
        print("No URLs found in file.")
        return
    if len(urls) > args.limit:
        urls = urls[: args.limit]

    print(f"Found {len(urls)} URLs to audit")

    db = DatabaseManager()
    with db.get_session() as session:
        detector = ContentTypeDetector(session=session)
        summary = {"byline": 0, "url": 0, "copyright": 0, "content": 0}
        missing = []

        for url in urls:
            row = session.execute(text(
                """
                SELECT id, url, title, author, text, metadata, status
                FROM articles WHERE url = :url LIMIT 1
                """
            ), {"url": url}).fetchone()
            if not row:
                missing.append(url)
                continue

            aid, aurl, title, author, text_content, metadata, status = row
            try:
                result = detector._detect_wire_service(
                    url=aurl,
                    content=text_content,
                    metadata=metadata if isinstance(metadata, dict) else None,
                    author=author,
                    title=title,
                )
            except Exception:
                result = None

            if not result:
                print(f"MISS (no wire): {aurl}")
                continue

            tier = result.evidence.get("detection_tier") if hasattr(result, "evidence") else "content"
            provider = (
                result.evidence.get("detected_services", [None])[-1]
                if hasattr(result, "evidence")
                else None
            )
            summary[tier] = summary.get(tier, 0) + 1
            print(f"WIRE ({tier}) [{provider}]: {aurl}")

        print("\n=== Audit Summary ===")
        for k in ("byline", "url", "copyright", "content"):
            print(f"{k:10s}: {summary.get(k, 0)}")
        if missing:
            print(f"Missing in DB: {len(missing)}")
            for u in missing[:10]:
                print(f"- {u}")


if __name__ == "__main__":
    main()
