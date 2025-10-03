#!/usr/bin/env python3
"""
Dry run analysis of content cleaning across all domains in the database.
Shows removal statistics and examples without making any changes.
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import after path setup
from utils.content_cleaner_balanced import BalancedBoundaryContentCleaner  # noqa


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return "unknown"


def get_domain_article_counts(db_path: str = "data/mizzou.db") -> dict:
    """Get article counts by domain."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT url, content
        FROM articles
        WHERE content IS NOT NULL
        AND content != ''
        AND LENGTH(content) > 100
    """)

    domain_counts = {}
    for url, content in cursor.fetchall():
        domain = extract_domain(url)
        if domain and domain != "unknown":
            if domain not in domain_counts:
                domain_counts[domain] = 1
            else:
                domain_counts[domain] += 1

    conn.close()
    return domain_counts


def main():
    parser = argparse.ArgumentParser(
        description="Dry run content cleaning analysis across all domains"
    )
    parser.add_argument(
        "--min-articles",
        type=int,
        default=3,
        help="Minimum articles per domain to analyze",
    )
    parser.add_argument(
        "--max-domains", type=int, default=20, help="Maximum domains to analyze"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Sample size per domain for analysis",
    )
    parser.add_argument(
        "--min-boundary-score",
        type=float,
        default=0.5,
        help="Minimum boundary score for segment removal",
    )
    parser.add_argument(
        "--show-examples",
        action="store_true",
        help="Show example segments for each domain",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    print("🧹 Content Cleaning Dry Run Analysis")
    print("=" * 50)

    # Get domain counts
    print(f"📊 Analyzing domains with >= {args.min_articles} articles...")
    domain_counts = get_domain_article_counts()

    # Filter and sort domains
    filtered_domains = {
        domain: count
        for domain, count in domain_counts.items()
        if count >= args.min_articles
    }

    sorted_domains = sorted(filtered_domains.items(), key=lambda x: x[1], reverse=True)[
        : args.max_domains
    ]

    print(f"Found {len(filtered_domains)} domains with sufficient articles")
    print(f"Analyzing top {len(sorted_domains)} domains")
    print()

    # Initialize cleaner
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    # Analysis results
    total_segments = 0
    total_removable_chars = 0
    total_articles_analyzed = 0
    domain_results = []

    for i, (domain, total_articles) in enumerate(sorted_domains, 1):
        print(f"🔍 {i:2d}. Analyzing {domain} ({total_articles} total articles)...")

        try:
            # Analyze domain
            result = cleaner.analyze_domain(
                domain, sample_size=args.sample_size, min_occurrences=3
            )

            if not result.get("segments"):
                print("    ❌ No boilerplate segments detected")
                print()
                continue

            # Filter segments by boundary score
            good_segments = [
                s
                for s in result["segments"]
                if s["boundary_score"] >= args.min_boundary_score
            ]

            if not good_segments:
                print(
                    f"    ⚠️  {len(result['segments'])} segments found but "
                    f"none meet boundary score threshold ({args.min_boundary_score})"
                )
                print()
                continue

            # Calculate stats
            stats = result["stats"]
            segment_count = len(good_segments)
            removal_chars = sum(s["length"] * s["occurrences"] for s in good_segments)
            estimated_removal_pct = (
                removal_chars / stats["total_content_chars"] * 100
                if stats["total_content_chars"] > 0
                else 0
            )

            total_segments += segment_count
            total_removable_chars += removal_chars
            total_articles_analyzed += result["article_count"]

            # Store results
            domain_result = {
                "domain": domain,
                "total_articles": total_articles,
                "analyzed_articles": result["article_count"],
                "segments": segment_count,
                "removal_percentage": estimated_removal_pct,
                "removable_chars": removal_chars,
                "good_segments": good_segments,
            }
            domain_results.append(domain_result)

            # Print summary for this domain
            print(
                f"    ✅ {segment_count} segments (score >= {args.min_boundary_score})"
            )
            print(f"    📈 Estimated removal: {estimated_removal_pct:.1f}% of content")
            print(f"    📝 {removal_chars:,} characters removable")

            # Show examples if requested
            if args.show_examples and good_segments:
                print("    🔍 Top segments:")
                for j, segment in enumerate(good_segments[:3], 1):
                    pattern_emoji = {
                        "navigation": "🧭",
                        "subscription": "💰",
                        "footer": "🦶",
                        "other": "❓",
                    }.get(segment["pattern_type"], "❓")

                    print(
                        f"       {j}. {pattern_emoji} Score: {segment['boundary_score']:.2f}, "
                        f"Occurs: {segment['occurrences']}x"
                    )
                    preview = segment["text"][:80].replace("\n", " ")
                    print(
                        f'          "{preview}{"..." if len(segment["text"]) > 80 else ""}"'
                    )

            print()

        except Exception as e:
            print(f"    ❌ Error analyzing {domain}: {e}")
            print()
            continue

    # Print overall summary
    print("📊 OVERALL SUMMARY")
    print("=" * 50)
    print(f"Domains analyzed: {len(domain_results)}")
    print(f"Total articles analyzed: {total_articles_analyzed:,}")
    print(f"Total segments for removal: {total_segments}")
    print(f"Total removable characters: {total_removable_chars:,}")

    if domain_results:
        avg_removal = sum(r["removal_percentage"] for r in domain_results) / len(
            domain_results
        )
        print(f"Average removal percentage: {avg_removal:.1f}%")

        print()
        print("🏆 TOP DOMAINS BY REMOVAL IMPACT:")
        top_domains = sorted(
            domain_results, key=lambda x: x["removal_percentage"], reverse=True
        )[:10]

        for i, result in enumerate(top_domains, 1):
            print(
                f"{i:2d}. {result['domain']:25} "
                f"{result['removal_percentage']:6.1f}% "
                f"({result['segments']} segments)"
            )

        print()
        print("📈 DOMAINS WITH MOST SEGMENTS:")
        segment_domains = sorted(
            domain_results, key=lambda x: x["segments"], reverse=True
        )[:10]

        for i, result in enumerate(segment_domains, 1):
            print(
                f"{i:2d}. {result['domain']:25} "
                f"{result['segments']:3d} segments "
                f"({result['removal_percentage']:5.1f}%)"
            )

    print()
    print("✅ Dry run analysis complete - no changes were made to the database.")


if __name__ == "__main__":
    main()
