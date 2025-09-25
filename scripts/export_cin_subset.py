#!/usr/bin/env python3
"""Export CIN stories filtered by primary label and county."""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

SPLIT_PATTERN = re.compile(r"\s*(?:and|/|,|&|\+|;)\s*", re.IGNORECASE)


def _split_counties(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = SPLIT_PATTERN.split(raw.strip())
    return [part.strip() for part in parts if part.strip()]


def _load_filtered_rows(
    source_csv: Path,
    category: str,
    counties: set[str] | None,
) -> list[dict[str, str]]:
    with source_csv.open(newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            raise ValueError("Source CSV has no header row")

        rows: list[dict[str, str]] = []
        normalized_counties = {county.lower() for county in counties or []}

        for row in reader:
            if (row.get("primary_label") or "").strip() != category:
                continue

            if normalized_counties:
                row_counties = {
                    county.lower() for county in _split_counties(
                        row.get("publication_county")
                    )
                }
                if not row_counties & normalized_counties:
                    continue

            rows.append(row)

    return rows


def _get_article_texts(
    db_path: Path,
    article_ids: Sequence[str],
) -> dict[str, str]:
    if not article_ids:
        return {}

    placeholders = ",".join(["?"] * len(article_ids))
    query = (
        "SELECT id, COALESCE(content, text, '') AS article_text "
        "FROM articles WHERE id IN (" + placeholders + ")"
    )

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(query, list(article_ids))
        results: dict[str, str] = {}
        for article_id, text in cursor.fetchall():
            results[str(article_id)] = text or ""

    return results


def export_subset(
    source_csv: Path,
    db_path: Path,
    output_csv: Path,
    category: str,
    counties: Iterable[str] | None,
) -> int:
    counties_set = set(counties or [])
    rows = _load_filtered_rows(source_csv, category, counties_set)
    article_ids = [row["article_id"] for row in rows if row.get("article_id")]
    article_texts = _get_article_texts(db_path, article_ids)

    output_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "publication_name",
        "url",
        "publish_date",
        "title",
        "text",
    ]

    missing_text = 0

    with output_csv.open("w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            article_id = row.get("article_id")
            text = article_texts.get(article_id or "", "")
            if not text:
                missing_text += 1

            writer.writerow(
                {
                    "publication_name": row.get("publication_name", ""),
                    "url": row.get("url", ""),
                    "publish_date": row.get("publish_date", ""),
                    "title": row.get("title", ""),
                    "text": text,
                }
            )

    return missing_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export CIN stories filtered by county and primary label. "
            "Text is pulled from data/mizzou.db."
        )
    )
    parser.add_argument(
        "--category",
        required=True,
        help="Primary label (e.g., 'Emergencies and Public Safety')",
    )
    parser.add_argument(
        "--county",
        action="append",
        help="County name to include (can be repeated)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("reports/cin_labels_with_sources.csv"),
        help="Path to CIN labels export CSV",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/mizzou.db"),
        help="Path to SQLite database containing article text",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/cin_subset.csv"),
        help="Where to write the filtered stories",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    missing_text = export_subset(
        source_csv=args.source,
        db_path=args.db_path,
        output_csv=args.output,
        category=args.category,
        counties=args.county,
    )

    if missing_text:
        print(
            f"Export complete: {args.output}. "
            f"Missing text for {missing_text} articles."
        )
    else:
        print(f"Export complete: {args.output}.")


if __name__ == "__main__":
    main()
