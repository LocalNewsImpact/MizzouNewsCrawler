#!/usr/bin/env python3

"""
Show before/after comparison for content cleaning.
"""

import argparse
import logging
import sqlite3

from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner


def show_before_after():
    """Show before/after comparison for content cleaning."""
    parser = argparse.ArgumentParser(
        description="Show before/after comparison for content cleaning"
    )
    parser.add_argument("--domain", required=True, help="Domain to analyze")
    parser.add_argument("--article-id", help="Specific article ID to show")
    parser.add_argument(
        "--sample-size", type=int, default=10, help="Number of articles to sample"
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    cleaner = TwoPhaseContentCleaner(db_path="data/mizzou.db")

    # Get analysis results
    results = cleaner.analyze_domain(args.domain, args.sample_size, 3)

    if not results["segments"]:
        print("No segments found for cleaning.")
        return

    # Get a specific article or the first one
    conn = sqlite3.connect("data/mizzou.db")
    cursor = conn.cursor()

    if args.article_id:
        cursor.execute(
            "SELECT id, url, content FROM articles WHERE id = ?", (args.article_id,)
        )
    else:
        # Get first article from the domain
        cursor.execute(
            "SELECT id, url, content FROM articles WHERE url LIKE ? LIMIT 1",
            (f"%{args.domain}%",),
        )

    row = cursor.fetchone()
    if not row:
        print("No article found.")
        return

    article_id, url, original_content = row
    conn.close()

    # Clean the content
    cleaned_content = cleaner.clean_article_content(
        original_content, results["segments"]
    )

    print("=== BEFORE/AFTER COMPARISON ===")
    print(f"Article ID: {article_id}")
    print(f"URL: {url}")
    print(f"Original length: {len(original_content):,} chars")
    print(f"Cleaned length: {len(cleaned_content):,} chars")
    print(
        f"Removed: {len(original_content) - len(cleaned_content):,} chars "
        f"({(len(original_content) - len(cleaned_content)) / len(original_content) * 100:.1f}%)"
    )

    print("\n" + "=" * 80)
    print("ORIGINAL CONTENT (first 1000 chars):")
    print("=" * 80)
    print(original_content[:1000])
    if len(original_content) > 1000:
        print("...")

    print("\n" + "=" * 80)
    print("CLEANED CONTENT (first 1000 chars):")
    print("=" * 80)
    print(cleaned_content[:1000])
    if len(cleaned_content) > 1000:
        print("...")

    print("\n" + "=" * 80)
    print("REMOVED SEGMENTS:")
    print("=" * 80)
    for i, segment in enumerate(results["segments"], 1):
        print(f"\n{i}. [{segment['pattern_type']}] {segment['length']} chars:")
        preview = segment["text"][:200].replace("\n", "\\n")
        print(f"   '{preview}{'...' if len(segment['text']) > 200 else ''}'")


if __name__ == "__main__":
    show_before_after()
