#!/usr/bin/env python3
"""
Dry run analysis: How many cleaned bylines would change with current rules?

This script analyzes the telemetry data to find original bylines and compares
them with what the current byline cleaner would produce.
"""

import json
import sqlite3
from collections import defaultdict

from src.utils.byline_cleaner import BylineCleaner


def analyze_byline_changes():
    """Analyze how many bylines would change with current cleaning rules."""

    print("🔍 BYLINE CLEANING DRY RUN ANALYSIS")
    print("=" * 60)

    # Initialize the current byline cleaner
    cleaner = BylineCleaner(enable_telemetry=False)

    # Connect to database
    db_path = 'data/mizzou.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all articles with telemetry data
    cursor.execute('''
        SELECT a.id, a.author, bct.raw_byline, bct.source_name, 
               bct.final_authors_json, bct.cleaning_method
        FROM articles a
        INNER JOIN byline_cleaning_telemetry bct ON a.id = bct.article_id
        WHERE bct.raw_byline IS NOT NULL
        AND a.author IS NOT NULL
        ORDER BY bct.extraction_timestamp DESC
    ''')

    results = cursor.fetchall()

    if not results:
        print("❌ No articles with byline telemetry found")
        return

    print(f"📊 Found {len(results)} articles with byline telemetry")
    print()

    # Track statistics
    stats = {
        'total_articles': 0,
        'articles_with_raw_byline': 0,
        'unchanged_bylines': 0,
        'changed_bylines': 0,
        'improved_bylines': 0,
        'degraded_bylines': 0,
        'parsing_errors': 0
    }

    changes_by_type = defaultdict(list)

    for article_id, current_author, raw_byline, source_name, final_authors_json, cleaning_method in results:
        stats['total_articles'] += 1

        try:
            # Parse current author
            if current_author:
                try:
                    current_authors = json.loads(current_author)
                    if not isinstance(current_authors, list):
                        current_authors = [str(current_author)]
                except (json.JSONDecodeError, TypeError):
                    current_authors = [str(current_author)]
            else:
                current_authors = []

            if not raw_byline:
                continue

            stats['articles_with_raw_byline'] += 1

            # Apply current cleaning rules
            new_authors = cleaner.clean_byline(
                raw_byline, source_name=source_name)

            # Compare results
            current_norm = sorted([a.strip() for a in current_authors
                                   if a.strip()])
            new_norm = sorted([a.strip() for a in new_authors
                               if a.strip()])

            if current_norm == new_norm:
                stats['unchanged_bylines'] += 1
            else:
                stats['changed_bylines'] += 1

                # Determine if change is improvement or degradation
                current_count = len(current_norm)
                new_count = len(new_norm)

                change_type = None

                # Analyze change type
                if new_count > current_count:
                    change_type = "more_authors_found"
                elif new_count < current_count:
                    change_type = "fewer_authors_found"
                elif new_count == current_count and new_count > 0:
                    # Same count, check quality
                    has_html_fix = any('&#' in author
                                       for author in current_norm)
                    if has_html_fix:
                        change_type = "html_decoding_fix"
                    else:
                        change_type = "name_format_change"
                else:
                    change_type = "other_change"

                # Classify as improvement or degradation
                improvement_types = {"html_decoding_fix", "more_authors_found"}
                if change_type in improvement_types:
                    stats['improved_bylines'] += 1
                elif new_count == 0 and current_count > 0:
                    stats['degraded_bylines'] += 1
                    change_type = "lost_all_authors"
                else:
                    # Neutral change
                    pass

                changes_by_type[change_type].append({
                    'article_id': article_id,
                    'raw_byline': raw_byline,
                    'current_authors': current_norm,
                    'new_authors': new_norm,
                    'source_name': source_name,
                    'cleaning_method': cleaning_method
                })

        except Exception as e:
            stats['parsing_errors'] += 1
            print(f"⚠️  Error processing article {article_id}: {e}")

    # Print summary statistics
    print("📈 SUMMARY STATISTICS")
    print("-" * 40)
    print(f"Total articles analyzed: {stats['total_articles']}")
    print(f"Articles with raw byline: {stats['articles_with_raw_byline']}")
    print(f"Parsing errors: {stats['parsing_errors']}")
    print()

    if stats['articles_with_raw_byline'] > 0:
        print("🔄 CHANGE ANALYSIS")
        print("-" * 40)
        unchanged_pct = (stats['unchanged_bylines'] / stats['articles_with_raw_byline']) * 100
        changed_pct = (stats['changed_bylines'] / stats['articles_with_raw_byline']) * 100

        print(f"Unchanged bylines: {stats['unchanged_bylines']} ({unchanged_pct:.1f}%)")
        print(f"Changed bylines: {stats['changed_bylines']} ({changed_pct:.1f}%)")
        print()

        if stats['changed_bylines'] > 0:
            improved_pct = (stats['improved_bylines'] / stats['changed_bylines']) * 100
            degraded_pct = (stats['degraded_bylines'] / stats['changed_bylines']) * 100

            print(f"Improvements: {stats['improved_bylines']} ({improved_pct:.1f}% of changes)")
            print(f"Degradations: {stats['degraded_bylines']} ({degraded_pct:.1f}% of changes)")
            print()

    # Show examples of each change type
    print("📋 CHANGE EXAMPLES BY TYPE")
    print("-" * 40)

    for change_type, examples in changes_by_type.items():
        print(f"\n🔸 {change_type.upper().replace('_', ' ')} ({len(examples)} cases)")
        print("-" * 30)

        # Show first 3 examples
        for i, example in enumerate(examples[:3]):
            print(f"Example {i+1}:")
            print(f"  Article ID: {example['article_id']}")
            print(f"  Raw byline: \"{example['raw_byline']}\"")
            print(f"  Source: {example['source_name']}")
            print(f"  Current: {example['current_authors']}")
            print(f"  New: {example['new_authors']}")
            print()

        if len(examples) > 3:
            print(f"  ... and {len(examples) - 3} more cases")
            print()

    # Overall assessment
    print("🎯 OVERALL ASSESSMENT")
    print("-" * 40)

    if stats['articles_with_raw_byline'] == 0:
        print("❌ No data available for analysis")
    elif stats['changed_bylines'] == 0:
        print("✅ No changes would be made - current cleaning is consistent")
    else:
        improvement_ratio = stats['improved_bylines'] / max(1, stats['changed_bylines'])
        degradation_ratio = stats['degraded_bylines'] / max(1, stats['changed_bylines'])

        if improvement_ratio > 0.7:
            print("✅ Excellent - Most changes would be improvements")
        elif improvement_ratio > 0.5:
            print("👍 Good - More improvements than degradations")
        elif degradation_ratio > 0.3:
            print("⚠️  Caution - Significant number of degradations")
        else:
            print("🤔 Mixed - Changes are mostly neutral")

        print(f"Change impact: {stats['changed_bylines']}/{stats['articles_with_raw_byline']} articles would change")
        print(f"Risk level: {stats['degraded_bylines']} potential degradations")

    conn.close()


if __name__ == "__main__":
    analyze_byline_changes()
