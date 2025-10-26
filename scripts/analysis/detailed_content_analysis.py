#!/usr/bin/env python3
"""
Detailed content cleaning analysis showing exactly what text would be removed.
"""

import argparse
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


def main():
    parser = argparse.ArgumentParser(
        description="Detailed analysis showing exact text that would be removed"
    )
    parser.add_argument("domain", help="Domain to analyze in detail")
    parser.add_argument(
        "--sample-size", type=int, default=20, help="Sample size for analysis"
    )
    parser.add_argument(
        "--min-boundary-score",
        type=float,
        default=0.5,
        help="Minimum boundary score for segment removal",
    )
    parser.add_argument(
        "--show-full-text",
        action="store_true",
        help="Show full text of segments (can be very long)",
    )

    args = parser.parse_args()

    print("🔍 DETAILED CONTENT CLEANING ANALYSIS")
    print(f"Domain: {args.domain}")
    print("=" * 60)

    # Initialize cleaner
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    try:
        # Analyze domain
        result = cleaner.analyze_domain(
            args.domain, sample_size=args.sample_size, min_occurrences=3
        )

        if not result.get("segments"):
            print("❌ No boilerplate segments detected")
            return

        # Filter segments by boundary score
        good_segments = [
            s
            for s in result["segments"]
            if s["boundary_score"] >= args.min_boundary_score
        ]

        if not good_segments:
            print(
                f"⚠️  {len(result['segments'])} segments found but "
                f"none meet boundary score threshold ({args.min_boundary_score})"
            )
            return

        # Calculate stats
        stats = result["stats"]
        segment_count = len(good_segments)
        removal_chars = sum(s["length"] * s["occurrences"] for s in good_segments)
        estimated_removal_pct = (
            removal_chars / stats["total_content_chars"] * 100
            if stats["total_content_chars"] > 0
            else 0
        )

        print("📊 ANALYSIS RESULTS:")
        print(f"   Articles analyzed: {result['article_count']}")
        print(f"   Segments for removal: {segment_count}")
        print(f"   Estimated removal: {estimated_removal_pct:.1f}% of content")
        print(f"   Total removable characters: {removal_chars:,}")
        print()

        # Show detailed segments
        print("📝 SEGMENTS TO BE REMOVED:")
        print("=" * 60)

        for i, segment in enumerate(good_segments, 1):
            pattern_emoji = {
                "navigation": "🧭",
                "subscription": "💰",
                "footer": "🦶",
                "trending": "📈",
                "other": "❓",
            }.get(segment["pattern_type"], "❓")

            print(f"\n{i:2d}. {pattern_emoji} SEGMENT #{i}")
            print(f"    Score: {segment['boundary_score']:.2f}")
            print(f"    Pattern: {segment['pattern_type']}")
            print(f"    Reason: {segment.get('removal_reason', 'No reason specified')}")
            print(f"    Occurrences: {segment['occurrences']}")
            print(f"    Length: {segment['length']} characters")
            print(
                f"    Total removal: {segment['length'] * segment['occurrences']:,} chars"
            )

            # Show text preview or full text
            text = segment["text"]
            if args.show_full_text or len(text) <= 200:
                print("    TEXT:")
                print("    " + "─" * 50)
                for line in text.split("\n"):
                    print(f"    {line}")
                print("    " + "─" * 50)
            else:
                # Show preview
                lines = text.split("\n")
                preview_lines = []
                char_count = 0

                for line in lines:
                    if char_count + len(line) > 150:
                        break
                    preview_lines.append(line)
                    char_count += len(line) + 1  # +1 for newline

                print("    TEXT PREVIEW (use --show-full-text to see all):")
                print("    " + "─" * 50)
                for line in preview_lines:
                    print(f"    {line}")
                if len(lines) > len(preview_lines):
                    remaining = len(lines) - len(preview_lines)
                    print(
                        f"    ... ({remaining} more lines, {len(text) - char_count} more chars)"
                    )
                print("    " + "─" * 50)

        print()
        print("💡 To see full text of all segments, use --show-full-text")
        print("✅ Analysis complete - no changes were made to the database.")

    except Exception as e:
        print(f"❌ Error analyzing {args.domain}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
