#!/usr/bin/env python3
"""
Dry run test of the new byline cleaning algorithm.
Shows how many authors would be changed and how.
"""

import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.utils.byline_cleaner import BylineCleaner
except ImportError:
    print("Error: Could not import BylineCleaner")
    sys.exit(1)


def get_current_articles_with_authors(db_path: str) -> list[tuple]:
    """Get all articles with their current authors from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # First, let's see what columns we actually have
    cursor.execute("PRAGMA table_info(articles)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"Available columns: {columns}")

    # Check if we have 'author' column
    if 'author' in columns:
        query = """
        SELECT id, title, author
        FROM articles
        WHERE author IS NOT NULL
        AND author != ''
        ORDER BY id
        LIMIT 1000
        """
    else:
        print("No 'author' column found")
        return []

    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()

    return results


def parse_authors_json(authors_json: str) -> list[str]:
    """Parse authors JSON string into list of author names."""
    try:
        if not authors_json or authors_json.strip() == '':
            return []

        # Handle JSON list format (now the standard format)
        if authors_json.startswith('[') and authors_json.endswith(']'):
            authors = json.loads(authors_json)
            return [str(author).strip() for author in authors
                    if str(author).strip()]
        else:
            # Fallback for any remaining non-JSON format
            if ',' in authors_json:
                return [author.strip() for author in authors_json.split(',')
                        if author.strip()]
            else:
                return [authors_json.strip()] if authors_json.strip() else []
    except (json.JSONDecodeError, ValueError):
        # Fallback: treat as simple string
        if ',' in authors_json:
            return [author.strip() for author in authors_json.split(',')
                    if author.strip()]
        else:
            return [authors_json.strip()] if authors_json.strip() else []


def analyze_author_changes(current: list[str], new: list[str]) -> dict:
    """Analyze the differences between current and new author lists."""
    current_set = set(current)
    new_set = set(new)

    # Check if new version has better quality names
    new_quality = sum(1 for name in new if len(name.split()) >= 2)
    current_quality = sum(1 for name in current if len(name.split()) >= 2)

    return {
        'current_count': len(current),
        'new_count': len(new),
        'current_authors': current,
        'new_authors': new,
        'added': list(new_set - current_set),
        'removed': list(current_set - new_set),
        'unchanged': list(current_set & new_set),
        'is_changed': current != new,
        'is_improvement': (
            len(new) > 0 and (
                len(new) > len(current) or
                new_quality > current_quality
            )
        )
    }


def categorize_change(analysis: dict) -> str:
    """Categorize the type of change that occurred."""
    if not analysis['is_changed']:
        return 'no_change'
    elif not analysis['current_authors'] and analysis['new_authors']:
        return 'extraction_success'
    elif analysis['current_authors'] and not analysis['new_authors']:
        return 'removal'
    elif len(analysis['new_authors']) > len(analysis['current_authors']):
        return 'more_authors'
    elif len(analysis['new_authors']) < len(analysis['current_authors']):
        return 'fewer_authors'
    elif analysis['added'] and analysis['removed']:
        return 'different_authors'
    else:
        return 'refinement'


def run_dry_run_analysis():
    """Run the complete dry run analysis."""

    print("🧪 DRY RUN: Testing New Byline Cleaning Algorithm")
    print("=" * 60)

    # Database path
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'mizzou.db')
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
    for article_id, title, current_author_json in articles:
        processed_count += 1

        if processed_count % 100 == 0:
            print(f"   ... processed {processed_count}/{len(articles)}")

        # Parse current authors from JSON format
        current_authors = parse_authors_json(current_author_json)

        # Use the first author as the raw byline input for testing
        # (In reality, we'd want the original byline text, but this gives us
        # a way to test our algorithm against existing processed data)
        if current_authors:
            raw_byline = current_authors[0]  # Use first author as test input
        else:
            raw_byline = current_author_json  # Use raw JSON if no parsed authors

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
            'article_id': article_id,
            'raw_byline': raw_byline,
            'analysis': analysis,
            'category': category
        }
        changes_by_category[category].append(change_data)

        # Collect examples for reporting
        if analysis['is_changed']:
            if analysis['is_improvement']:
                if len(improvement_examples) < 10:
                    improvement_examples.append(change_data)
            else:
                if len(concerning_examples) < 10:
                    concerning_examples.append(change_data)

        # Track byline patterns
        byline_length = len(raw_byline)
        if byline_length < 20:
            byline_patterns['short'] += 1
        elif byline_length < 50:
            byline_patterns['medium'] += 1
        else:
            byline_patterns['long'] += 1

    print(f"✅ Completed processing {processed_count} articles")

    # Generate comprehensive report
    print("\n" + "=" * 60)
    print("📊 DRY RUN ANALYSIS RESULTS")
    print("=" * 60)

    # Overall statistics
    total_articles = len(articles)
    changed_count = sum(len(changes) for category, changes
                       in changes_by_category.items()
                       if category != 'no_change')

    print("\n📈 OVERALL IMPACT:")
    print(f"   Total articles analyzed: {total_articles:,}")
    print(f"   Articles that would change: {changed_count:,}")
    print(f"   Percentage changed: {(changed_count/total_articles)*100:.1f}%")
    print(f"   Articles unchanged: {len(changes_by_category['no_change']):,}")

    # Changes by category
    print("\n📋 CHANGES BY CATEGORY:")
    category_items = sorted(changes_by_category.items(),
                           key=lambda x: len(x[1]), reverse=True)
    for category, changes in category_items:
        count = len(changes)
        percentage = (count / total_articles) * 100
        category_name = category.replace('_', ' ').title()
        print(f"   {category_name}: {count:,} articles ({percentage:.1f}%)")

    # Improvement examples
    if improvement_examples:
        print(f"\n✅ IMPROVEMENT EXAMPLES (showing {len(improvement_examples)}):")
        for i, example in enumerate(improvement_examples[:5], 1):
            analysis = example['analysis']
            print(f"\n   Example {i} (Article ID: {example['article_id']}):")
            print(f"   Raw byline: \"{example['raw_byline']}\"")
            print(f"   Current: {analysis['current_authors']}")
            print(f"   New: {analysis['new_authors']}")
            if analysis['added']:
                print(f"   ➕ Added: {analysis['added']}")
            if analysis['removed']:
                print(f"   ➖ Removed: {analysis['removed']}")

    # Concerning examples
    if concerning_examples:
        print("\n⚠️  CONCERNING EXAMPLES:")
        for i, example in enumerate(concerning_examples[:5], 1):
            analysis = example['analysis']
            print(f"\n   Example {i} (Article ID: {example['article_id']}):")
            print(f"   Raw byline: \"{example['raw_byline']}\"")
            print(f"   Current: {analysis['current_authors']}")
            print(f"   New: {analysis['new_authors']}")
            if analysis['added']:
                print(f"   ➕ Added: {analysis['added']}")
            if analysis['removed']:
                print(f"   ➖ Removed: {analysis['removed']}")

    # Byline pattern analysis
    print("\n📝 BYLINE PATTERN ANALYSIS:")
    total_patterns = sum(byline_patterns.values())
    for pattern, count in byline_patterns.most_common():
        percentage = (count / total_patterns) * 100
        print(f"   {pattern.title()} bylines: {count:,} ({percentage:.1f}%)")

    # Summary recommendations
    print("\n💡 RECOMMENDATIONS:")

    improvement_count = sum(1 for category, changes
                           in changes_by_category.items()
                           for change in changes
                           if change['analysis']['is_improvement'])

    if improvement_count > changed_count * 0.7:
        print("   ✅ Algorithm shows significant improvements")
    elif improvement_count > changed_count * 0.5:
        print("   ⚠️  Algorithm shows mixed results")
    else:
        print("   ❌ Algorithm may cause problems")

    print("\n   Key metrics:")
    print(f"   - Improvements: {improvement_count:,}/{changed_count:,}")
    success_rate = (improvement_count/max(changed_count, 1))*100
    print(f"   - Success rate: {success_rate:.1f}%")

    removal_rate = len(changes_by_category['removal']) / total_articles
    if removal_rate > 0.1:
        print("   ⚠️  High removal rate - verify if intended")

    extraction_count = len(changes_by_category['extraction_success'])
    if extraction_count > 0:
        print(f"   ✅ Found authors in {extraction_count} empty articles")

    print("\n" + "=" * 60)
    print("🎯 DRY RUN COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    run_dry_run_analysis()
