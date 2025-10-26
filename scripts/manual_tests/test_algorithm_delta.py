#!/usr/bin/env python3
"""
Test new byline cleaning algorithm against telemetry data.
Compare new algorithm results with current database cleaned authors.
"""

import sqlite3
import json
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.utils.byline_cleaner import BylineCleaner


def get_current_authors_from_db() -> dict[str, list[str]]:
    """Get current cleaned authors from articles table."""
    conn = sqlite3.connect("data/mizzou.db")
    cursor = conn.cursor()

    # Get articles with authors
    cursor.execute("""
        SELECT id, author
        FROM articles
        WHERE author IS NOT NULL
        AND author != '[]'
        AND author != ''
    """)

    current_authors = {}
    for article_id, authors_json in cursor.fetchall():
        try:
            authors = json.loads(authors_json)
            if isinstance(authors, list) and authors:
                current_authors[str(article_id)] = authors
        except (json.JSONDecodeError, TypeError):
            continue

    conn.close()
    return current_authors


def get_telemetry_data() -> dict[str, dict]:
    """Get raw bylines and metadata from telemetry table."""
    conn = sqlite3.connect("data/mizzou.db")
    cursor = conn.cursor()

    # Get telemetry data with raw bylines
    cursor.execute("""
        SELECT article_id, raw_byline, source_name, source_canonical_name,
               candidate_link_id, source_id
        FROM byline_cleaning_telemetry 
        WHERE raw_byline IS NOT NULL 
        AND raw_byline != ''
        ORDER BY article_id, id
    """)

    telemetry_data = {}
    for row in cursor.fetchall():
        (
            article_id,
            raw_byline,
            source_name,
            source_canonical_name,
            candidate_link_id,
            source_id,
        ) = row

        # Use the most recent telemetry entry for each article
        telemetry_data[str(article_id)] = {
            "raw_byline": raw_byline,
            "source_name": source_name,
            "source_canonical_name": source_canonical_name,
            "candidate_link_id": candidate_link_id,
            "source_id": source_id,
        }

    conn.close()
    return telemetry_data


def compare_author_lists(old_authors: list[str], new_authors: list[str]) -> dict:
    """Compare two author lists and categorize the change."""
    old_set = set(author.lower().strip() for author in old_authors)
    new_set = set(author.lower().strip() for author in new_authors)

    if old_set == new_set:
        return {
            "change_type": "identical",
            "added": [],
            "removed": [],
            "description": "No changes",
        }

    added = list(new_set - old_set)
    removed = list(old_set - new_set)

    # Determine change type
    if not old_authors and new_authors:
        change_type = "new_extraction"
    elif old_authors and not new_authors:
        change_type = "removal"
    elif len(new_authors) > len(old_authors):
        change_type = "expansion"
    elif len(new_authors) < len(old_authors):
        change_type = "reduction"
    else:
        change_type = "modification"

    return {
        "change_type": change_type,
        "added": added,
        "removed": removed,
        "description": f"Added: {len(added)}, Removed: {len(removed)}",
    }


def analyze_changes():
    """Main analysis function."""
    print("🔍 BYLINE ALGORITHM DELTA ANALYSIS")
    print("=" * 60)
    print()

    # Initialize new algorithm (without telemetry to avoid conflicts)
    cleaner = BylineCleaner(enable_telemetry=False)

    # Get current data
    print("📊 Loading current database authors...")
    current_authors = get_current_authors_from_db()
    print(f"Found {len(current_authors)} articles with authors")

    print("📊 Loading telemetry data...")
    telemetry_data = get_telemetry_data()
    print(f"Found {len(telemetry_data)} telemetry entries")

    # Find articles that have both current authors and telemetry
    common_articles = set(current_authors.keys()) & set(telemetry_data.keys())
    print(
        f"Found {len(common_articles)} articles with both current authors and telemetry"
    )
    print()

    # Track changes
    changes = {
        "identical": 0,
        "new_extraction": 0,
        "removal": 0,
        "expansion": 0,
        "reduction": 0,
        "modification": 0,
    }

    detailed_changes = []
    sample_changes = {
        "new_extraction": [],
        "removal": [],
        "expansion": [],
        "reduction": [],
        "modification": [],
    }

    errors = []

    # Process each article
    for i, article_id in enumerate(sorted(common_articles), 1):
        if i % 100 == 0:
            print(f"Processed {i}/{len(common_articles)} articles...")

        try:
            # Get current authors
            old_authors = current_authors[article_id]

            # Get telemetry data
            telemetry = telemetry_data[article_id]
            raw_byline = telemetry["raw_byline"]
            source_name = telemetry["source_name"]

            # Run new algorithm
            new_authors = cleaner.clean_byline(
                raw_byline, return_json=False, source_name=source_name
            )

            # Ensure we have a list
            if not isinstance(new_authors, list):
                new_authors = []

            # Compare results
            comparison = compare_author_lists(old_authors, new_authors)
            change_type = comparison["change_type"]
            changes[change_type] += 1

            # Store detailed information
            change_detail = {
                "article_id": article_id,
                "raw_byline": raw_byline,
                "source_name": source_name,
                "old_authors": old_authors,
                "new_authors": new_authors,
                "comparison": comparison,
            }
            detailed_changes.append(change_detail)

            # Collect samples for each change type
            if change_type != "identical" and len(sample_changes[change_type]) < 5:
                sample_changes[change_type].append(change_detail)

        except Exception as e:
            errors.append(
                {
                    "article_id": article_id,
                    "error": str(e),
                    "raw_byline": telemetry_data[article_id].get(
                        "raw_byline", "Unknown"
                    ),
                }
            )

    print()
    print("📈 SUMMARY STATISTICS")
    print("=" * 40)

    total_articles = len(common_articles)
    unchanged_count = changes["identical"]
    changed_count = total_articles - unchanged_count

    print(f"Total articles analyzed: {total_articles}")
    print(
        f"Unchanged: {unchanged_count} ({unchanged_count / total_articles * 100:.1f}%)"
    )
    print(f"Changed: {changed_count} ({changed_count / total_articles * 100:.1f}%)")
    print()

    print("Change breakdown:")
    for change_type, count in changes.items():
        if change_type != "identical" and count > 0:
            percentage = count / total_articles * 100
            print(
                f"  {change_type.replace('_', ' ').title()}: {count} ({percentage:.1f}%)"
            )

    if errors:
        print(f"Errors encountered: {len(errors)}")

    print()
    print("🔍 SAMPLE CHANGES")
    print("=" * 40)

    for change_type, samples in sample_changes.items():
        if samples:
            print(f"\n{change_type.replace('_', ' ').title()} Examples:")
            for i, sample in enumerate(samples[:3], 1):
                print(f"  {i}. Article {sample['article_id']}")
                print(f"     Raw: '{sample['raw_byline']}'")
                print(f"     Source: {sample['source_name']}")
                print(f"     Old: {sample['old_authors']}")
                print(f"     New: {sample['new_authors']}")
                print(f"     Change: {sample['comparison']['description']}")
                print()

    # Show significant changes (where authors were completely different)
    print("🚨 SIGNIFICANT CHANGES (Complete Author Replacement)")
    print("=" * 55)

    significant_changes = [
        change
        for change in detailed_changes
        if (
            change["comparison"]["change_type"]
            in ["modification", "removal", "new_extraction"]
            and len(change["comparison"]["added"]) > 0
            and len(change["comparison"]["removed"]) > 0
        )
    ]

    for i, change in enumerate(significant_changes[:10], 1):
        print(f"{i}. Article {change['article_id']}")
        print(f"   Raw: '{change['raw_byline']}'")
        print(f"   Source: {change['source_name']}")
        print(f"   Old: {change['old_authors']}")
        print(f"   New: {change['new_authors']}")
        print(f"   Added: {change['comparison']['added']}")
        print(f"   Removed: {change['comparison']['removed']}")
        print()

    if len(significant_changes) > 10:
        print(f"... and {len(significant_changes) - 10} more significant changes")

    # Show error samples
    if errors:
        print()
        print("❌ ERROR SAMPLES")
        print("=" * 30)
        for i, error in enumerate(errors[:5], 1):
            print(f"{i}. Article {error['article_id']}")
            print(f"   Raw: '{error['raw_byline']}'")
            print(f"   Error: {error['error']}")
            print()

    return {
        "total_articles": total_articles,
        "changes": changes,
        "detailed_changes": detailed_changes,
        "errors": errors,
    }


if __name__ == "__main__":
    try:
        results = analyze_changes()
        print("\n✅ Analysis complete!")

        # Optional: Save detailed results to file
        save_details = input("\nSave detailed results to file? (y/N): ").lower().strip()
        if save_details == "y":
            output_file = "algorithm_delta_analysis.json"
            with open(output_file, "w") as f:
                # Convert to JSON-serializable format
                json_results = {
                    "summary": {
                        "total_articles": results["total_articles"],
                        "changes": results["changes"],
                    },
                    "detailed_changes": results["detailed_changes"][:100],  # Limit size
                    "errors": results["errors"],
                }
                json.dump(json_results, f, indent=2)
            print(f"Detailed results saved to {output_file}")

    except KeyboardInterrupt:
        print("\n\n❌ Analysis interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Analysis failed: {e}")
        raise
