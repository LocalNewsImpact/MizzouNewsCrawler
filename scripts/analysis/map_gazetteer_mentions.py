#!/usr/bin/env python3
"""Map actual mentions of gazetteer entities to county/outlet combinations.

This script scans article text for occurrences of gazetteer entity names
restricted to the business/economic/government/healthcare categories and
records which outlets and counties actually mention those entities. Results are
written to a CSV summarizing the number of distinct articles mentioning each
entity per (county, outlet, category) grouping.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from re import Pattern

CATEGORIES: tuple[str, ...] = (
    "businesses",
    "economic",
    "government",
    "healthcare",
)

# Characters that we consider part of an entity token for boundary purposes.
# This keeps apostrophes and ampersands inside names but avoids run-on matches
# against alphanumeric characters in surrounding text.
TOKEN_CHARS = "A-Za-z0-9&'"  # hyphen handled via pattern replacement


def build_pattern(name: str) -> Pattern[str] | None:
    """Build a compiled regex that matches an entity name within article text.

    The pattern enforces loose word boundaries and collapses stretches of
    whitespace so that names like "Casey's General Store" match even if the
    article uses multiple spaces or newline breaks between words.
    """

    clean = name.strip()
    if not clean:
        return None

    # Collapse repeated whitespace to a single space for consistency.
    clean = re.sub(r"\s+", " ", clean)

    # Require at least one alphanumeric character to avoid patterns that would
    # never produce meaningful matches (e.g., lone punctuation).
    if not re.search(r"[A-Za-z0-9]", clean):
        return None

    escaped = re.escape(clean)
    # Allow flexible spacing between words.
    escaped = escaped.replace(r"\ ", r"\s+")
    # Treat hyphenated names as matching both with hyphen and with spaces.
    escaped = escaped.replace(r"\-", r"[-\s]")

    pattern = rf"(?<![{TOKEN_CHARS}]){escaped}(?![{TOKEN_CHARS}])"
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def fetch_entities_by_source(
    conn: sqlite3.Connection,
) -> dict[str, list[tuple[str, str, Pattern[str]]]]:
    """Return relevant gazetteer entities organized by source_id."""

    query = """
        SELECT DISTINCT source_id, category, name
        FROM gazetteer
        WHERE category IN (?, ?, ?, ?)
          AND name IS NOT NULL
          AND source_id IS NOT NULL
    """
    entities: dict[str, list[tuple[str, str, Pattern[str]]]] = defaultdict(list)
    for source_id, category, name in conn.execute(query, CATEGORIES):
        pattern = build_pattern(name)
        if pattern is None:
            continue
        entities[source_id].append((category, name, pattern))
    return entities


def iterate_articles(
    conn: sqlite3.Connection,
) -> Iterable[sqlite3.Row]:
    """Yield articles joined with outlet metadata."""

    query = """
        SELECT a.id AS article_id, a.text, cl.source_id, cl.source_name,
               cl.source_county
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.text IS NOT NULL
          AND cl.source_id IS NOT NULL
          AND cl.source_name IS NOT NULL
          AND cl.source_county IS NOT NULL
    """
    yield from conn.execute(query)


def map_mentions(
    conn: sqlite3.Connection,
    entities_by_source: dict[str, list[tuple[str, str, Pattern[str]]]],
) -> dict[tuple[str, str, str, str], set]:
    """Return mapping of (county, outlet, category, entity) -> article IDs."""

    mentions: dict[tuple[str, str, str, str], set] = defaultdict(set)

    for row in iterate_articles(conn):
        article_id = row["article_id"]
        text = row["text"]
        source_id = row["source_id"]
        outlet = row["source_name"]
        county = row["source_county"]

        entity_patterns = entities_by_source.get(source_id)
        if not entity_patterns:
            continue

        for category, name, pattern in entity_patterns:
            if pattern.search(text):
                key = (county, outlet, category, name)
                mentions[key].add(article_id)

    return mentions


def write_results(
    output_path: Path,
    mentions: dict[tuple[str, str, str, str], set],
) -> None:
    """Persist mention counts to CSV sorted by county/outlet/category."""

    rows = [
        (county, outlet, category, name, len(article_ids))
        for (county, outlet, category, name), article_ids in mentions.items()
    ]
    rows.sort(key=lambda r: (r[0], r[1], r[2], -r[4], r[3]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "county",
                "outlet",
                "category",
                "entity_name",
                "article_count",
            ]
        )
        writer.writerows(rows)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Locate actual mentions of gazetteer entities in article text and "
            "summarize them by county/outlet."
        )
    )
    parser.add_argument(
        "--db",
        default="data/mizzou.db",
        help="Path to the SQLite database (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default="reports/county_outlet_entity_mentions_actual.csv",
        help="CSV file to write mention counts (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    db_path = Path(args.db)
    output_path = Path(args.output)

    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        entities_by_source = fetch_entities_by_source(conn)
        if not entities_by_source:
            print("No gazetteer entities found for target categories.")
            return 0

        mentions = map_mentions(conn, entities_by_source)
        write_results(output_path, mentions)
        print(f"Wrote {len(mentions)} county/outlet/entity rows to {output_path}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
