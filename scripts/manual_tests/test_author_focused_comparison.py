#!/usr/bin/env python3
"""
Focused comparison between OLD (current) and NEW (experimental) byline cleaning methods
using real author bylines from production articles (non-wire content).
"""

import sys
import os
import time
import sqlite3
from typing import Any
from dataclasses import dataclass, asdict
import json
from collections import Counter, defaultdict

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner
from utils.byline_cleaner_experimental import ExperimentalBylineCleaner


@dataclass
class AuthorComparisonResult:
    """Result of comparing OLD vs NEW methods on a real author byline."""

    raw_byline: str
    current_extraction: list[str]  # What's currently in the database
    old_result: list[str]  # What OLD method produces
    new_result: list[str]  # What NEW method produces
    new_confidence: float
    new_strategy: str
    old_time_ms: float
    new_time_ms: float

    # Agreement analysis
    old_vs_current_match: bool  # Does OLD match what's in DB?
    new_vs_current_match: bool  # Does NEW match what's in DB?
    old_vs_new_match: bool  # Do OLD and NEW agree?

    # Quality analysis
    current_author_count: int
    old_author_count: int
    new_author_count: int

    # Classification
    improvement_type: str  # 'old_better', 'new_better', 'equivalent', 'both_worse'


class FocusedAuthorComparison:
    """Compare OLD vs NEW methods on real author bylines from production."""

    def __init__(self):
        # Initialize both cleaners
        self.old_cleaner = BylineCleaner(enable_telemetry=False)
        self.new_cleaner = ExperimentalBylineCleaner()

        # Load real author data from database
        self.test_data = self._load_real_author_data()

        # Results storage
        self.results: list[AuthorComparisonResult] = []

    def _load_real_author_data(self) -> list[tuple[str, list[str]]]:
        """Load real bylines and their current author extractions from the database."""
        try:
            conn = sqlite3.connect("data/mizzou.db")
            cursor = conn.cursor()

            # Get bylines that produced actual author extractions (not wire services)
            query = """
            SELECT DISTINCT bct.raw_byline, a.author 
            FROM byline_cleaning_telemetry bct 
            JOIN articles a ON a.id = bct.article_id 
            WHERE a.author IS NOT NULL 
              AND a.author != '' 
              AND a.author != '[]' 
              AND a.wire IS NULL 
              AND bct.raw_byline IS NOT NULL 
              AND bct.raw_byline != ''
              AND LENGTH(bct.raw_byline) > 3
              AND LENGTH(bct.raw_byline) < 200
            ORDER BY RANDOM() 
            LIMIT 150
            """

            cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()

            # Parse the author JSON
            test_data = []
            for raw_byline, author_json in rows:
                try:
                    current_authors = json.loads(author_json)
                    if isinstance(current_authors, list) and current_authors:
                        test_data.append((raw_byline, current_authors))
                except json.JSONDecodeError:
                    continue

            print(f"Loaded {len(test_data)} real author bylines from database")
            return test_data

        except Exception as e:
            print(f"Error loading author data from database: {e}")
            return []

    def _classify_improvement(self, result: AuthorComparisonResult) -> str:
        """Classify whether OLD or NEW method is better for this case."""

        # If current extraction is our baseline "truth"
        current_count = result.current_author_count
        old_count = result.old_author_count
        new_count = result.new_author_count

        # Check exact matches first
        if result.old_vs_current_match and not result.new_vs_current_match:
            return "old_better"
        elif result.new_vs_current_match and not result.old_vs_current_match:
            return "new_better"
        elif result.old_vs_current_match and result.new_vs_current_match:
            return "equivalent"

        # Neither matches exactly - evaluate based on count proximity and quality
        old_diff = abs(old_count - current_count)
        new_diff = abs(new_count - current_count)

        if old_diff < new_diff:
            return "old_closer"
        elif new_diff < old_diff:
            return "new_closer"
        elif old_count == 0 and new_count == 0:
            return "both_failed"
        else:
            # Same distance - check confidence for NEW method
            if result.new_confidence > 0.7:
                return "new_higher_confidence"
            else:
                return "equivalent_distance"

    def run_comparison(self) -> dict[str, Any]:
        """Run comparison between OLD and NEW methods on real author data."""
        print("\n=== FOCUSED AUTHOR EXTRACTION COMPARISON ===")
        print(f"Testing {len(self.test_data)} real author bylines from production\n")

        total_old_time = 0
        total_new_time = 0

        for i, (raw_byline, current_authors) in enumerate(self.test_data, 1):
            if i % 25 == 0:
                print(
                    f"Progress: {i}/{len(self.test_data)} ({i / len(self.test_data) * 100:.1f}%)"
                )

            # Test OLD method
            start_time = time.perf_counter()
            old_result = self.old_cleaner.clean_byline(raw_byline)
            old_time = (time.perf_counter() - start_time) * 1000

            # Test NEW method
            start_time = time.perf_counter()
            new_extraction = self.new_cleaner.clean_byline_multi_strategy(
                raw_byline, source_name=None, return_comparison=True
            )
            new_time = (time.perf_counter() - start_time) * 1000

            # Extract NEW method details
            if isinstance(new_extraction, dict):
                new_result = new_extraction.get("best_result", [])
                new_confidence = new_extraction.get("confidence", 0.5)
                new_strategy = new_extraction.get("strategy_used", "unknown")
            else:
                new_result = new_extraction if isinstance(new_extraction, list) else []
                new_confidence = 0.5
                new_strategy = "unknown"

            # Calculate agreement flags
            old_vs_current_match = old_result == current_authors
            new_vs_current_match = new_result == current_authors
            old_vs_new_match = old_result == new_result

            # Create result
            result = AuthorComparisonResult(
                raw_byline=raw_byline,
                current_extraction=current_authors,
                old_result=old_result,
                new_result=new_result,
                new_confidence=new_confidence,
                new_strategy=new_strategy,
                old_time_ms=old_time,
                new_time_ms=new_time,
                old_vs_current_match=old_vs_current_match,
                new_vs_current_match=new_vs_current_match,
                old_vs_new_match=old_vs_new_match,
                current_author_count=len(current_authors),
                old_author_count=len(old_result),
                new_author_count=len(new_result),
                improvement_type="",  # Will be set below
            )

            # Classify improvement
            result.improvement_type = self._classify_improvement(result)

            self.results.append(result)
            total_old_time += old_time
            total_new_time += new_time

        # Calculate summary statistics
        total_tests = len(self.results)
        old_exact_matches = sum(1 for r in self.results if r.old_vs_current_match)
        new_exact_matches = sum(1 for r in self.results if r.new_vs_current_match)
        old_new_agreement = sum(1 for r in self.results if r.old_vs_new_match)

        avg_old_time = total_old_time / total_tests
        avg_new_time = total_new_time / total_tests
        speed_ratio = avg_new_time / avg_old_time if avg_old_time > 0 else 0

        summary = {
            "total_tests": total_tests,
            "old_exact_matches": old_exact_matches,
            "new_exact_matches": new_exact_matches,
            "old_new_agreement": old_new_agreement,
            "old_accuracy_rate": old_exact_matches / total_tests,
            "new_accuracy_rate": new_exact_matches / total_tests,
            "method_agreement_rate": old_new_agreement / total_tests,
            "old_avg_time_ms": avg_old_time,
            "new_avg_time_ms": avg_new_time,
            "speed_ratio": speed_ratio,
        }

        return summary

    def analyze_improvements(self) -> dict[str, Any]:
        """Analyze where each method performs better."""
        improvement_counts = Counter(r.improvement_type for r in self.results)

        # Group examples by improvement type
        examples_by_type = defaultdict(list)
        for result in self.results:
            if len(examples_by_type[result.improvement_type]) < 5:  # Limit examples
                examples_by_type[result.improvement_type].append(
                    {
                        "byline": result.raw_byline,
                        "current": result.current_extraction,
                        "old": result.old_result,
                        "new": result.new_result,
                        "new_confidence": result.new_confidence,
                        "new_strategy": result.new_strategy,
                    }
                )

        # Strategy usage in NEW method
        strategy_counts = Counter(r.new_strategy for r in self.results)

        return {
            "improvement_types": dict(improvement_counts),
            "examples_by_type": dict(examples_by_type),
            "new_strategy_usage": dict(strategy_counts),
        }

    def generate_detailed_report(self) -> str:
        """Generate comprehensive comparison report."""
        summary = self.run_comparison()
        improvements = self.analyze_improvements()

        report = []
        report.append("=" * 80)
        report.append("FOCUSED AUTHOR EXTRACTION COMPARISON")
        report.append("OLD (Current) vs NEW (Experimental) Methods")
        report.append("=" * 80)
        report.append("")

        # Summary Statistics
        report.append("ACCURACY COMPARISON:")
        report.append("-" * 40)
        report.append(f"Total Test Cases: {summary['total_tests']}")
        report.append(
            f"OLD Method Exact Matches: {summary['old_exact_matches']} ({summary['old_accuracy_rate'] * 100:.1f}%)"
        )
        report.append(
            f"NEW Method Exact Matches: {summary['new_exact_matches']} ({summary['new_accuracy_rate'] * 100:.1f}%)"
        )
        report.append(
            f"Method Agreement: {summary['old_new_agreement']} ({summary['method_agreement_rate'] * 100:.1f}%)"
        )
        report.append("")

        # Performance
        report.append("PERFORMANCE COMPARISON:")
        report.append("-" * 40)
        report.append(f"OLD Method Average Time: {summary['old_avg_time_ms']:.2f}ms")
        report.append(f"NEW Method Average Time: {summary['new_avg_time_ms']:.2f}ms")
        report.append(f"Speed Ratio (NEW/OLD): {summary['speed_ratio']:.1f}x")
        report.append("")

        # Improvement Analysis
        report.append("IMPROVEMENT ANALYSIS:")
        report.append("-" * 40)
        for improvement_type, count in improvements["improvement_types"].items():
            percentage = (count / summary["total_tests"]) * 100
            report.append(f"  {improvement_type}: {count} ({percentage:.1f}%)")
        report.append("")

        # Strategy Usage
        report.append("NEW METHOD STRATEGY USAGE:")
        report.append("-" * 40)
        for strategy, count in improvements["new_strategy_usage"].items():
            percentage = (count / summary["total_tests"]) * 100
            report.append(f"  {strategy}: {count} ({percentage:.1f}%)")
        report.append("")

        # Detailed Examples
        report.append("DETAILED EXAMPLES:")
        report.append("-" * 40)

        for improvement_type, examples in improvements["examples_by_type"].items():
            if examples:
                report.append(f"\n{improvement_type.upper().replace('_', ' ')}:")
                for i, example in enumerate(examples, 1):
                    report.append(f'  {i}. Byline: "{example["byline"]}"')
                    report.append(f"     CURRENT: {example['current']}")
                    report.append(f"     OLD: {example['old']}")
                    report.append(
                        f"     NEW: {example['new']} (confidence: {example['new_confidence']:.2f}, strategy: {example['new_strategy']})"
                    )
                    report.append("")

        report.append("=" * 80)

        return "\n".join(report)

    def save_detailed_results(
        self, filename: str = "author_focused_comparison_results.json"
    ):
        """Save detailed results to JSON file."""
        detailed_results = {
            "metadata": {
                "test_count": len(self.results),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "description": "Focused comparison on real author bylines from production articles",
            },
            "summary": self.run_comparison(),
            "improvements": self.analyze_improvements(),
            "all_results": [asdict(result) for result in self.results],
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(detailed_results, f, indent=2, ensure_ascii=False)

        print(f"Detailed results saved to {filename}")


def main():
    """Run the focused author comparison."""
    comparison = FocusedAuthorComparison()

    if not comparison.test_data:
        print("No test data available. Exiting.")
        return

    # Generate and display report
    report = comparison.generate_detailed_report()
    print(report)

    # Save detailed results
    comparison.save_detailed_results()

    # Save report to file
    with open("AUTHOR_FOCUSED_comparison_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    print("\nReport saved to AUTHOR_FOCUSED_comparison_report.txt")
    print("Detailed JSON results saved to author_focused_comparison_results.json")


if __name__ == "__main__":
    main()
