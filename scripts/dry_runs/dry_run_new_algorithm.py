#!/usr/bin/env python3
"""
Dry run test of the new byline cleaning algorithm against current articles
database. Shows how many authors would be changed and provides detailed
analysis.
"""

import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.utils.byline_cleaner import BylineCleaner


def get_current_articles_with_authors(db_path: str) -> list[tuple[int, str, str]]:
    """
    Get all articles with their current authors from the database.

    Returns:
        List of tuples: (article_id, raw_byline, current_authors_json)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get articles that have both raw bylines and processed authors
    query = """
    SELECT id, byline, authors 
    FROM articles 
    WHERE byline IS NOT NULL 
    AND byline != '' 
    AND authors IS NOT NULL 
    AND authors != '' 
    AND authors != '[]'
    ORDER BY id
    """

    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()

    return results


def parse_authors_json(authors_json: str) -> list[str]:
    """Parse authors JSON string into list of author names."""
    try:
        if not authors_json or authors_json.strip() == "":
            return []

        # Handle both JSON list format and simple string format
        if authors_json.startswith("[") and authors_json.endswith("]"):
            authors = json.loads(authors_json)
            return [str(author).strip() for author in authors if str(author).strip()]
        else:
            # Handle single author or comma-separated format
            if "," in authors_json:
                return [
                    author.strip()
                    for author in authors_json.split(",")
                    if author.strip()
                ]
            else:
                return [authors_json.strip()] if authors_json.strip() else []
    except (json.JSONDecodeError, ValueError):
        # Fallback: treat as simple string
        if "," in authors_json:
            return [
                author.strip() for author in authors_json.split(",") if author.strip()
            ]
        else:
            return [authors_json.strip()] if authors_json.strip() else []


def analyze_author_changes(current: list[str], new: list[str]) -> dict[str, any]:
    """
    Analyze the differences between current and new author lists.

    Returns:
        Dictionary with analysis results
    """
    current_set = set(current)
    new_set = set(new)

    return {
        "current_count": len(current),
        "new_count": len(new),
        "current_authors": current,
        "new_authors": new,
        "added": list(new_set - current_set),
        "removed": list(current_set - new_set),
        "unchanged": list(current_set & new_set),
        "is_changed": current != new,
        "is_improvement": len(new) > 0
        and (
            # More valid names extracted
            len(new) > len(current)
            or
            # Better name quality (names with multiple words)
            sum(1 for name in new if len(name.split()) >= 2)
            > sum(1 for name in current if len(name.split()) >= 2)
        ),
    }


def categorize_change(analysis: dict) -> str:
    """Categorize the type of change that occurred."""
    if not analysis["is_changed"]:
        return "no_change"
    elif not analysis["current_authors"] and analysis["new_authors"]:
        return "extraction_success"  # Found authors where none existed
    elif analysis["current_authors"] and not analysis["new_authors"]:
        return "removal"  # Removed invalid authors
    elif len(analysis["new_authors"]) > len(analysis["current_authors"]):
        return "more_authors"  # Found additional authors
    elif len(analysis["new_authors"]) < len(analysis["current_authors"]):
        return "fewer_authors"  # Reduced to fewer (hopefully better) authors
    elif analysis["added"] and analysis["removed"]:
        return "different_authors"  # Completely different authors
    else:
        return "refinement"  # Same count but different quality


def run_dry_run_analysis():
    """Run the complete dry run analysis."""

    print("🧪 DRY RUN: Testing New Byline Cleaning Algorithm")
    print("=" * 60)

    # Database path
    db_path = os.path.join(os.path.dirname(__file__), "data", "mizzou.db")
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return

    print(f"📂 Loading articles from: {db_path}")

    # Get current articles
    articles = get_current_articles_with_authors(db_path)
    print(f"📊 Found {len(articles)} articles with authors to analyze")

    if not articles:
        print("❌ No articles with authors found in database")
        return

    # Initialize the new cleaner (with telemetry disabled for speed)
    cleaner = BylineCleaner(enable_telemetry=False)

    # Analysis tracking
    changes_by_category = defaultdict(list)
    improvement_examples = []
    concerning_examples = []
    byline_patterns = Counter()

    print("\n🔄 Processing articles...")

    processed_count = 0
    for article_id, raw_byline, current_authors_json in articles:
        processed_count += 1

        if processed_count % 100 == 0:
            print(f"   ... processed {processed_count}/{len(articles)} articles")

        # Parse current authors
        current_authors = parse_authors_json(current_authors_json)

        # Run new algorithm
        try:
            new_authors = cleaner.clean_byline(raw_byline, return_json=False)
        except Exception as e:
            print(f"⚠️  Error processing article {article_id}: {e}")
            new_authors = []

        # Analyze the change
        analysis = analyze_author_changes(current_authors, new_authors)
        category = categorize_change(analysis)

        # Store the analysis
        change_data = {
            "article_id": article_id,
            "raw_byline": raw_byline,
            "analysis": analysis,
            "category": category,
        }
        changes_by_category[category].append(change_data)

        # Collect examples for reporting
        if analysis["is_changed"]:
            if analysis["is_improvement"]:
                if len(improvement_examples) < 10:  # Limit examples
                    improvement_examples.append(change_data)
            else:
                if len(concerning_examples) < 10:  # Limit examples
                    concerning_examples.append(change_data)

        # Track byline patterns
        byline_length = len(raw_byline)
        if byline_length < 20:
            byline_patterns["short"] += 1
        elif byline_length < 50:
            byline_patterns["medium"] += 1
        else:
            byline_patterns["long"] += 1

    print(f"✅ Completed processing {processed_count} articles")

    # Generate comprehensive report
    print("\n" + "=" * 60)
    print("📊 DRY RUN ANALYSIS RESULTS")
    print("=" * 60)

    # Overall statistics
    total_articles = len(articles)
    changed_articles = sum(
        len(changes)
        for category, changes in changes_by_category.items()
        if category != "no_change"
    )

    print("\n📈 OVERALL IMPACT:")
    print(f"   Total articles analyzed: {total_articles:,}")
    print(f"   Articles that would change: {changed_articles:,}")
    print(f"   Percentage changed: {(changed_articles / total_articles) * 100:.1f}%")
    print(f"   Articles unchanged: {len(changes_by_category['no_change']):,}")

    # Changes by category
    print("\n📋 CHANGES BY CATEGORY:")
    for category, changes in sorted(
        changes_by_category.items(), key=lambda x: len(x[1]), reverse=True
    ):
        count = len(changes)
        percentage = (count / total_articles) * 100
        print(
            f"   {category.replace('_', ' ').title()}: {count:,} articles ({percentage:.1f}%)"
        )

    # Improvement examples
    if improvement_examples:
        print(f"\n✅ IMPROVEMENT EXAMPLES (showing {len(improvement_examples)}):")
        for i, example in enumerate(improvement_examples[:5], 1):
            analysis = example["analysis"]
            print(f"\n   Example {i} (Article ID: {example['article_id']}):")
            print(f'   Raw byline: "{example["raw_byline"]}"')
            print(f"   Current: {analysis['current_authors']}")
            print(f"   New: {analysis['new_authors']}")
            if analysis["added"]:
                print(f"   ➕ Added: {analysis['added']}")
            if analysis["removed"]:
                print(f"   ➖ Removed: {analysis['removed']}")

    # Concerning examples
    if concerning_examples:
        print(f"\n⚠️  CONCERNING EXAMPLES (showing {len(concerning_examples)}):")
        for i, example in enumerate(concerning_examples[:5], 1):
            analysis = example["analysis"]
            print(f"\n   Example {i} (Article ID: {example['article_id']}):")
            print(f'   Raw byline: "{example["raw_byline"]}"')
            print(f"   Current: {analysis['current_authors']}")
            print(f"   New: {analysis['new_authors']}")
            if analysis["added"]:
                print(f"   ➕ Added: {analysis['added']}")
            if analysis["removed"]:
                print(f"   ➖ Removed: {analysis['removed']}")

    # Byline pattern analysis
    print("\n📝 BYLINE PATTERN ANALYSIS:")
    total_patterns = sum(byline_patterns.values())
    for pattern, count in byline_patterns.most_common():
        percentage = (count / total_patterns) * 100
        print(f"   {pattern.title()} bylines: {count:,} ({percentage:.1f}%)")

    # Detailed category analysis
    print("\n🔍 DETAILED CATEGORY ANALYSIS:")

    for category in [
        "extraction_success",
        "more_authors",
        "fewer_authors",
        "different_authors",
        "removal",
    ]:
        if category in changes_by_category:
            changes = changes_by_category[category]
            if changes:
                print(
                    f"\n   {category.replace('_', ' ').title()} ({len(changes)} articles):"
                )

                # Show a few examples from this category
                for i, change in enumerate(changes[:3], 1):
                    analysis = change["analysis"]
                    print(f"      {i}. Article {change['article_id']}:")
                    print(
                        f'         Byline: "{change["raw_byline"][:60]}{"..." if len(change["raw_byline"]) > 60 else ""}"'
                    )
                    print(f"         Before: {analysis['current_authors']}")
                    print(f"         After: {analysis['new_authors']}")

    # Summary recommendations
    print("\n💡 RECOMMENDATIONS:")

    improvement_count = sum(
        1
        for category, changes in changes_by_category.items()
        for change in changes
        if change["analysis"]["is_improvement"]
    )

    if improvement_count > changed_articles * 0.7:
        print("   ✅ Algorithm shows significant improvements - recommend deployment")
    elif improvement_count > changed_articles * 0.5:
        print("   ⚠️  Algorithm shows mixed results - recommend careful review")
    else:
        print("   ❌ Algorithm may cause more problems - recommend further development")

    print("\n   Key metrics:")
    print(
        f"   - Improvements: {improvement_count:,}/{changed_articles:,} changed articles"
    )
    print(
        f"   - Success rate: {(improvement_count / max(changed_articles, 1)) * 100:.1f}%"
    )

    if len(changes_by_category["removal"]) > total_articles * 0.1:
        print("   ⚠️  High removal rate - verify if this is intended")

    if len(changes_by_category["extraction_success"]) > 0:
        print(
            f"   ✅ Found authors in {len(changes_by_category['extraction_success'])} previously empty articles"
        )

    print("\n" + "=" * 60)
    print("🎯 DRY RUN COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    run_dry_run_analysis()
