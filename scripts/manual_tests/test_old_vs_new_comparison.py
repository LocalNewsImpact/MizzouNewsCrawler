#!/usr/bin/env python3
"""
Comprehensive comparison between OLD (current) and NEW (experimental)
byline cleaning methods. Uses real telemetry data from the database
for testing.
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
sys.path.insert(0, os.path.dirname(__file__))

from utils.byline_cleaner import BylineCleaner
from utils.byline_cleaner_experimental import ExperimentalBylineCleaner


@dataclass
@dataclass
class ComparisonResult:
    """Result of comparing OLD vs NEW methods on a single byline."""

    raw_byline: str
    old_result: list[str]
    new_result: list[str]
    new_confidence: float
    new_strategy: str
    old_time_ms: float
    new_time_ms: float
    agreement: bool
    old_length: int
    new_length: int
    difference_type: (
        str  # 'identical', 'subset', 'superset', 'different', 'new_empty', 'old_empty'
    )


class OldVsNewComparison:
    """Compare OLD (current) vs NEW (experimental) byline cleaning methods."""

    def __init__(self):
        # Initialize both cleaners
        self.old_cleaner = BylineCleaner(enable_telemetry=False)
        self.new_cleaner = ExperimentalBylineCleaner()

        # Get real bylines from database
        self.test_bylines = self._load_real_bylines()

        # Results storage
        self.results: list[ComparisonResult] = []

    def _load_real_bylines(self) -> list[str]:
        """Load real bylines from the telemetry database."""
        try:
            conn = sqlite3.connect("data/mizzou.db")
            cursor = conn.cursor()

            # Get diverse set of bylines including edge cases
            query = """
            SELECT DISTINCT raw_byline 
            FROM byline_cleaning_telemetry 
            WHERE raw_byline IS NOT NULL 
              AND raw_byline != '' 
              AND LENGTH(raw_byline) > 3
              AND LENGTH(raw_byline) < 500
            ORDER BY RANDOM() 
            LIMIT 300
            """

            cursor.execute(query)
            bylines = [row[0] for row in cursor.fetchall()]
            conn.close()

            print(f"Loaded {len(bylines)} real bylines from database")
            return bylines

        except Exception as e:
            print(f"Error loading bylines from database: {e}")
            # Fallback to sample data
            return [
                "By JOHN DOE Special to the Herald",
                "Associated Press",
                "Reuters",
                "Jane Smith, Reporter",
                "Mike Johnson and Sarah Wilson",
                "BREAKING: Staff Reporter",
                "CNN NewsSource",
                "By Author Name Special tot he Times",
                "Staff Editorial Board",
                "Wire Service Report",
            ]

    def _classify_difference(self, old_result: list[str], new_result: list[str]) -> str:
        """Classify the type of difference between OLD and NEW results."""
        if old_result == new_result:
            return "identical"
        elif not old_result and new_result:
            return "new_found_authors"
        elif old_result and not new_result:
            return "old_found_authors"
        elif set(old_result).issubset(set(new_result)):
            return "new_superset"
        elif set(new_result).issubset(set(old_result)):
            return "new_subset"
        else:
            return "completely_different"

    def run_comparison(self) -> dict[str, Any]:
        """Run comprehensive comparison between OLD and NEW methods."""
        print("\n=== OLD vs NEW Byline Cleaning Comparison ===")
        print(f"Testing {len(self.test_bylines)} real bylines from telemetry data\n")

        total_old_time = 0
        total_new_time = 0
        agreements = 0

        for i, byline in enumerate(self.test_bylines, 1):
            if i % 50 == 0:
                print(
                    f"Progress: {i}/{len(self.test_bylines)} ({i / len(self.test_bylines) * 100:.1f}%)"
                )

            # Test OLD method
            start_time = time.perf_counter()
            old_result = self.old_cleaner.clean_byline(byline)
            old_time = (time.perf_counter() - start_time) * 1000

            # Test NEW method
            start_time = time.perf_counter()
            new_extraction = self.new_cleaner.clean_byline_multi_strategy(
                byline, source_name=None, return_comparison=True
            )
            new_time = (time.perf_counter() - start_time) * 1000

            # Extract information from the detailed result
            if isinstance(new_extraction, dict):
                new_result = new_extraction.get("best_result", [])
                new_confidence = new_extraction.get("confidence", 0.5)
                new_strategy = new_extraction.get("strategy_used", "unknown")
            else:
                # Fallback if structure is different
                new_result = new_extraction if isinstance(new_extraction, list) else []
                new_confidence = 0.5
                new_strategy = "unknown"

            # Calculate agreement
            agreement = old_result == new_result
            if agreement:
                agreements += 1

            # Classify difference type
            difference_type = self._classify_difference(old_result, new_result)

            # Store result
            result = ComparisonResult(
                raw_byline=byline,
                old_result=old_result,
                new_result=new_result,
                new_confidence=new_confidence,
                new_strategy=new_strategy,
                old_time_ms=old_time,
                new_time_ms=new_time,
                agreement=agreement,
                old_length=len(old_result),
                new_length=len(new_result),
                difference_type=difference_type,
            )

            self.results.append(result)
            total_old_time += old_time
            total_new_time += new_time

        # Calculate summary statistics
        agreement_rate = agreements / len(self.test_bylines)
        avg_old_time = total_old_time / len(self.test_bylines)
        avg_new_time = total_new_time / len(self.test_bylines)
        speed_ratio = avg_new_time / avg_old_time if avg_old_time > 0 else 0

        summary = {
            "total_tests": len(self.test_bylines),
            "agreements": agreements,
            "agreement_rate": agreement_rate,
            "disagreements": len(self.test_bylines) - agreements,
            "old_avg_time_ms": avg_old_time,
            "new_avg_time_ms": avg_new_time,
            "speed_ratio": speed_ratio,
            "old_total_time_ms": total_old_time,
            "new_total_time_ms": total_new_time,
        }

        return summary

    def analyze_differences(self) -> dict[str, Any]:
        """Analyze patterns in disagreements between OLD and NEW methods."""
        disagreements = [r for r in self.results if not r.agreement]

        if not disagreements:
            return {"message": "No disagreements found"}

        # Classify difference types
        difference_counts = Counter(r.difference_type for r in disagreements)

        # Strategy usage in disagreements
        strategy_counts = Counter(r.new_strategy for r in disagreements)

        # Confidence distribution in disagreements
        confidence_ranges = {
            "high (0.8-1.0)": len(
                [r for r in disagreements if r.new_confidence >= 0.8]
            ),
            "medium (0.6-0.8)": len(
                [r for r in disagreements if 0.6 <= r.new_confidence < 0.8]
            ),
            "low (0.0-0.6)": len([r for r in disagreements if r.new_confidence < 0.6]),
        }

        # Examples of each difference type
        examples_by_type = defaultdict(list)
        for result in disagreements[:20]:  # Limit examples
            examples_by_type[result.difference_type].append(
                {
                    "byline": result.raw_byline,
                    "old": result.old_result,
                    "new": result.new_result,
                    "confidence": result.new_confidence,
                    "strategy": result.new_strategy,
                }
            )

        return {
            "total_disagreements": len(disagreements),
            "difference_types": dict(difference_counts),
            "strategy_usage": dict(strategy_counts),
            "confidence_distribution": confidence_ranges,
            "examples_by_type": dict(examples_by_type),
        }

    def generate_detailed_report(self) -> str:
        """Generate a comprehensive comparison report."""
        summary = self.run_comparison()
        differences = self.analyze_differences()

        report = []
        report.append("=" * 80)
        report.append("OLD vs NEW BYLINE CLEANING METHOD COMPARISON")
        report.append("=" * 80)
        report.append("")

        # Summary Statistics
        report.append("SUMMARY STATISTICS:")
        report.append("-" * 40)
        report.append(f"Total Tests: {summary['total_tests']}")
        report.append(
            f"Agreements: {summary['agreements']} ({summary['agreement_rate'] * 100:.1f}%)"
        )
        report.append(
            f"Disagreements: {summary['disagreements']} ({(1 - summary['agreement_rate']) * 100:.1f}%)"
        )
        report.append("")

        # Performance Comparison
        report.append("PERFORMANCE COMPARISON:")
        report.append("-" * 40)
        report.append(f"OLD Method Average Time: {summary['old_avg_time_ms']:.2f}ms")
        report.append(f"NEW Method Average Time: {summary['new_avg_time_ms']:.2f}ms")
        report.append(f"Speed Ratio (NEW/OLD): {summary['speed_ratio']:.1f}x")
        report.append(
            f"NEW method is {summary['speed_ratio']:.1f}x {'slower' if summary['speed_ratio'] > 1 else 'faster'} than OLD"
        )
        report.append("")

        # Difference Analysis
        if "total_disagreements" in differences:
            report.append("DISAGREEMENT ANALYSIS:")
            report.append("-" * 40)
            report.append(f"Total Disagreements: {differences['total_disagreements']}")
            report.append("")

            report.append("Difference Types:")
            for diff_type, count in differences["difference_types"].items():
                percentage = (count / differences["total_disagreements"]) * 100
                report.append(f"  {diff_type}: {count} ({percentage:.1f}%)")
            report.append("")

            report.append("NEW Method Strategy Usage in Disagreements:")
            for strategy, count in differences["strategy_usage"].items():
                percentage = (count / differences["total_disagreements"]) * 100
                report.append(f"  {strategy}: {count} ({percentage:.1f}%)")
            report.append("")

            report.append("NEW Method Confidence Distribution in Disagreements:")
            for conf_range, count in differences["confidence_distribution"].items():
                percentage = (count / differences["total_disagreements"]) * 100
                report.append(f"  {conf_range}: {count} ({percentage:.1f}%)")
            report.append("")

        # Strategy Usage Overall
        strategy_overall = Counter(r.new_strategy for r in self.results)
        report.append("OVERALL NEW METHOD STRATEGY USAGE:")
        report.append("-" * 40)
        for strategy, count in strategy_overall.most_common():
            percentage = (count / len(self.results)) * 100
            report.append(f"  {strategy}: {count} ({percentage:.1f}%)")
        report.append("")

        # Detailed Examples
        if "examples_by_type" in differences:
            report.append("EXAMPLE DISAGREEMENTS:")
            report.append("-" * 40)

            for diff_type, examples in differences["examples_by_type"].items():
                if examples:
                    report.append(f"\n{diff_type.upper()}:")
                    for i, example in enumerate(examples[:3], 1):  # Show top 3 examples
                        report.append(f'  {i}. Byline: "{example["byline"]}"')
                        report.append(f"     OLD Result: {example['old']}")
                        report.append(f"     NEW Result: {example['new']}")
                        report.append(
                            f"     NEW Confidence: {example['confidence']:.2f}"
                        )
                        report.append(f"     NEW Strategy: {example['strategy']}")
                        report.append("")

        # Cases where NEW found authors but OLD didn't
        new_found_cases = [
            r for r in self.results if r.difference_type == "new_found_authors"
        ]
        if new_found_cases:
            report.append("CASES WHERE NEW METHOD FOUND AUTHORS (OLD DIDN'T):")
            report.append("-" * 40)
            for i, case in enumerate(new_found_cases[:10], 1):
                report.append(f'  {i}. "{case.raw_byline}"')
                report.append(f"     OLD: {case.old_result}")
                report.append(
                    f"     NEW: {case.new_result} (confidence: {case.new_confidence:.2f}, strategy: {case.new_strategy})"
                )
                report.append("")

        # Cases where OLD found authors but NEW didn't
        old_found_cases = [
            r for r in self.results if r.difference_type == "old_found_authors"
        ]
        if old_found_cases:
            report.append("CASES WHERE OLD METHOD FOUND AUTHORS (NEW DIDN'T):")
            report.append("-" * 40)
            for i, case in enumerate(old_found_cases[:10], 1):
                report.append(f'  {i}. "{case.raw_byline}"')
                report.append(f"     OLD: {case.old_result}")
                report.append(
                    f"     NEW: {case.new_result} (confidence: {case.new_confidence:.2f}, strategy: {case.new_strategy})"
                )
                report.append("")

        # Wire Service Cases
        wire_cases = [r for r in self.results if "wire" in r.new_strategy.lower()]
        if wire_cases:
            report.append("WIRE SERVICE DETECTION CASES:")
            report.append("-" * 40)
            for i, case in enumerate(wire_cases[:10], 1):
                report.append(f'  {i}. "{case.raw_byline}"')
                report.append(f"     OLD: {case.old_result}")
                report.append(
                    f"     NEW: {case.new_result} (confidence: {case.new_confidence:.2f})"
                )
                report.append("")

        report.append("=" * 80)

        return "\n".join(report)

    def save_detailed_results(self, filename: str = "old_vs_new_detailed_results.json"):
        """Save detailed results to JSON file for further analysis."""
        detailed_results = {
            "metadata": {
                "test_count": len(self.results),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "method_comparison": "OLD (current BylineCleaner) vs NEW (ExperimentalBylineCleaner)",
            },
            "summary": self.run_comparison(),
            "differences": self.analyze_differences(),
            "all_results": [asdict(result) for result in self.results],
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(detailed_results, f, indent=2, ensure_ascii=False)

        print(f"Detailed results saved to {filename}")


def main():
    """Run the comparison and generate report."""
    comparison = OldVsNewComparison()

    # Generate and display report
    report = comparison.generate_detailed_report()
    print(report)

    # Save detailed results
    comparison.save_detailed_results()

    # Save report to file
    with open("OLD_vs_NEW_comparison_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    print("\nReport saved to OLD_vs_NEW_comparison_report.txt")
    print("Detailed JSON results saved to old_vs_new_detailed_results.json")


if __name__ == "__main__":
    main()
