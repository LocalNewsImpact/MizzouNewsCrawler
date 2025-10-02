#!/usr/bin/env python3
"""
Field Quality Report - Detailed analysis of extraction field quality

This script provides comprehensive reporting on field-level quality issues
detected during content extraction, helping identify patterns and problems.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import json
from collections import Counter

from sqlalchemy import text

from models.database import DatabaseManager


def generate_field_quality_report(operation_id=None, limit=50):
    """Generate detailed field quality report."""

    print("=" * 60)
    print("FIELD QUALITY ANALYSIS REPORT")
    print("=" * 60)

    with DatabaseManager() as db:
        # Base query for recent extractions
        where_clause = "WHERE operation_id = :operation_id" if operation_id else ""
        if not operation_id:
            where_clause = "WHERE timestamp > datetime('now', '-24 hours')"

        query = f"""
            SELECT 
                url,
                outcome,
                title_quality_issues,
                content_quality_issues,
                author_quality_issues,
                publish_date_quality_issues,
                overall_quality_score,
                title_has_issues,
                content_has_issues,
                author_has_issues,
                publish_date_has_issues,
                has_title,
                has_content,
                has_author,
                has_publish_date
            FROM extraction_outcomes 
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT :limit
        """

        params = {'limit': limit}
        if operation_id:
            params['operation_id'] = operation_id

        results = db.session.execute(text(query), params).fetchall()

        if not results:
            print("No extraction results found.")
            return

        print(f"Analyzing {len(results)} extraction results...")
        print()

        # Field presence analysis
        field_stats = {
            'title': {'present': 0, 'missing': 0, 'issues': 0},
            'content': {'present': 0, 'missing': 0, 'issues': 0},
            'author': {'present': 0, 'missing': 0, 'issues': 0},
            'publish_date': {'present': 0, 'missing': 0, 'issues': 0}
        }

        # Quality issue tracking
        all_issues = {
            'title': Counter(),
            'content': Counter(),
            'author': Counter(),
            'publish_date': Counter()
        }

        quality_scores = []
        perfect_scores = 0

        # Sample issues for detailed view
        sample_issues = []

        for row in results:
            # Track quality scores
            quality_scores.append(row.overall_quality_score)
            if row.overall_quality_score == 1.0:
                perfect_scores += 1

            # Field presence tracking
            field_stats['title']['present'] += 1 if row.has_title else 0
            field_stats['title']['missing'] += 1 if not row.has_title else 0
            field_stats['title']['issues'] += 1 if row.title_has_issues else 0

            field_stats['content']['present'] += 1 if row.has_content else 0
            field_stats['content']['missing'] += 1 if not row.has_content else 0
            field_stats['content']['issues'] += 1 if row.content_has_issues else 0

            field_stats['author']['present'] += 1 if row.has_author else 0
            field_stats['author']['missing'] += 1 if not row.has_author else 0
            field_stats['author']['issues'] += 1 if row.author_has_issues else 0

            field_stats['publish_date']['present'] += 1 if row.has_publish_date else 0
            field_stats['publish_date']['missing'] += 1 if not row.has_publish_date else 0
            field_stats['publish_date']['issues'] += 1 if row.publish_date_has_issues else 0

            # Parse and count specific quality issues
            try:
                title_issues = json.loads(row.title_quality_issues or '[]')
                content_issues = json.loads(row.content_quality_issues or '[]')
                author_issues = json.loads(row.author_quality_issues or '[]')
                date_issues = json.loads(row.publish_date_quality_issues or '[]')

                for issue in title_issues:
                    all_issues['title'][issue] += 1
                for issue in content_issues:
                    all_issues['content'][issue] += 1
                for issue in author_issues:
                    all_issues['author'][issue] += 1
                for issue in date_issues:
                    all_issues['publish_date'][issue] += 1

                # Collect samples of articles with issues
                if any([title_issues, content_issues, author_issues, date_issues]):
                    sample_issues.append({
                        'url': row.url[:80] + '...' if len(row.url) > 80 else row.url,
                        'quality_score': row.overall_quality_score,
                        'title_issues': title_issues,
                        'content_issues': content_issues,
                        'author_issues': author_issues,
                        'date_issues': date_issues
                    })

            except json.JSONDecodeError:
                continue

        # Print field presence summary
        print("FIELD PRESENCE SUMMARY")
        print("-" * 40)
        total = len(results)
        for field, stats in field_stats.items():
            present_pct = (stats['present'] / total) * 100
            issues_pct = (stats['issues'] / total) * 100 if total > 0 else 0
            print(f"{field.upper():>12}: {stats['present']:>3}/{total} present ({present_pct:>5.1f}%), "
                  f"{stats['issues']:>3} with issues ({issues_pct:>5.1f}%)")

        print()

        # Print quality score summary
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        perfect_pct = (perfect_scores / total) * 100

        print("QUALITY SCORE SUMMARY")
        print("-" * 40)
        print(f"Average Quality Score: {avg_quality:.3f}")
        print(f"Perfect Scores (1.0):  {perfect_scores}/{total} ({perfect_pct:.1f}%)")
        print(f"Score Range:           {min(quality_scores):.2f} - {max(quality_scores):.2f}")
        print()

        # Print specific quality issues
        print("QUALITY ISSUES BREAKDOWN")
        print("-" * 40)
        for field, issues in all_issues.items():
            if issues:
                print(f"\n{field.upper()} Issues:")
                for issue, count in issues.most_common():
                    pct = (count / total) * 100
                    print(f"  {issue:>20}: {count:>3} articles ({pct:>5.1f}%)")
            else:
                print(f"\n{field.upper()}: No quality issues detected")

        # Show sample problematic articles
        if sample_issues:
            print("\n" + "=" * 60)
            print("SAMPLE ARTICLES WITH QUALITY ISSUES")
            print("=" * 60)

            # Sort by quality score (worst first)
            sample_issues.sort(key=lambda x: x['quality_score'])

            for i, sample in enumerate(sample_issues[:5], 1):
                print(f"\n{i}. Quality Score: {sample['quality_score']:.2f}")
                print(f"   URL: {sample['url']}")

                if sample['title_issues']:
                    print(f"   Title Issues: {', '.join(sample['title_issues'])}")
                if sample['content_issues']:
                    print(f"   Content Issues: {', '.join(sample['content_issues'])}")
                if sample['author_issues']:
                    print(f"   Author Issues: {', '.join(sample['author_issues'])}")
                if sample['date_issues']:
                    print(f"   Date Issues: {', '.join(sample['date_issues'])}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Field Quality Analysis Report")
    parser.add_argument('--operation-id', help="Specific operation ID to analyze")
    parser.add_argument('--limit', type=int, default=50,
                        help="Maximum number of results to analyze (default: 50)")

    args = parser.parse_args()

    generate_field_quality_report(
        operation_id=args.operation_id,
        limit=args.limit
    )


if __name__ == "__main__":
    main()
