#!/usr/bin/env python3
"""
Test script to compare current vs experimental byline cleaning methods.

This script allows us to:
1. Test both methods on the same data
2. Compare results and performance
3. Analyze which strategies work best for different types of bylines
4. Make data-driven decisions about integration
"""

import sys
import os
import time

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

try:
    from src.utils.byline_cleaner_experimental import (
        ExperimentalBylineCleaner,
        compare_cleaning_methods,
    )
    from src.utils.byline_cleaner import BylineCleaner
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)


def test_special_to_cases():
    """Test the specific 'Special to' cases we've been working on."""
    test_cases = [
        {
            "byline": "By DORIAN DUCRE Special tot he Courier-Post",
            "source": "Courier-Post",
            "expected": ["Dorian Ducre"],
        },
        {
            "byline": "By DORIAN DUCRE Special to the Courier-Post",
            "source": "Courier-Post",
            "expected": ["Dorian Ducre"],
        },
        {
            "byline": "By JANE SMITH Special to the Herald",
            "source": "Herald",
            "expected": ["Jane Smith"],
        },
        {
            "byline": "By JOHN DOE SPECIAL CORRESPONDENT",
            "source": None,
            "expected": ["John Doe"],
        },
        {
            "byline": "By Mary Johnson Special to The Times",
            "source": "The Times",
            "expected": ["Mary Johnson"],
        },
    ]

    print("=== Testing 'Special to' Cases ===")
    print()

    current_cleaner = BylineCleaner(enable_telemetry=False)
    experimental_cleaner = ExperimentalBylineCleaner(enable_telemetry=False)

    for i, case in enumerate(test_cases, 1):
        byline = case["byline"]
        source = case["source"]
        expected = case["expected"]

        print(f"Test {i}: {byline}")
        print(f"Source: {source}")
        print(f"Expected: {expected}")

        # Current method
        start_time = time.time()
        current_result = current_cleaner.clean_byline(byline, source_name=source)
        current_time = time.time() - start_time

        # Experimental method
        start_time = time.time()
        experimental_detailed = experimental_cleaner.clean_byline_multi_strategy(
            byline, source_name=source, return_comparison=True
        )
        experimental_time = time.time() - start_time

        experimental_result = experimental_detailed["best_result"]
        strategy_used = experimental_detailed["strategy_used"]
        confidence = experimental_detailed["confidence"]

        # Check results
        current_correct = current_result == expected
        experimental_correct = experimental_result == expected

        print(
            f"Current:      {current_result} ({'✅' if current_correct else '❌'}) ({current_time * 1000:.1f}ms)"
        )
        print(
            f"Experimental: {experimental_result} ({'✅' if experimental_correct else '❌'}) ({experimental_time * 1000:.1f}ms)"
        )
        print(f"Strategy:     {strategy_used} (confidence: {confidence:.2f})")

        if current_result != experimental_result:
            print("⚠️  DIFFERENT RESULTS!")

        print()

    return test_cases


def test_diverse_bylines():
    """Test a diverse set of byline patterns."""
    test_cases = [
        # Wire services
        "By The Associated Press",
        "Reuters",
        "By CNN NewsSource",
        # Standard bylines
        "By John Smith",
        "By Sarah Johnson and Mike Davis",
        "Written by Emma Wilson",
        # Complex bylines
        "By Jennifer Brown, staff writer",
        "By Robert Clark • rclark@example.com",
        "By Lisa Martinez, Herald correspondent",
        # Problematic cases
        "Staff Report",
        "News Services",
        "By THE ASSOCIATED PRESS",
        # Photo credits mixed with bylines
        "By Tom Anderson | Photo by Jake Miller",
        "Mary Peterson, staff • Photos by Chris Lee",
    ]

    print("=== Testing Diverse Bylines ===")
    print()

    # Compare methods
    comparison_result = compare_cleaning_methods(test_cases)

    print(f"Total tests: {comparison_result['statistics']['total_tests']}")
    print(f"Matches: {comparison_result['statistics']['matches']}")
    print(f"Match rate: {comparison_result['statistics']['match_percentage']:.1f}%")
    print()

    print("Strategy usage:")
    for strategy, count in comparison_result["statistics"]["strategy_usage"].items():
        percentage = (count / len(test_cases)) * 100
        print(f"  {strategy}: {count} ({percentage:.1f}%)")
    print()

    # Show cases where results differ
    differences = [r for r in comparison_result["results"] if not r["match"]]
    if differences:
        print("Cases with different results:")
        for diff in differences:
            print(f"  Byline: '{diff['byline']}'")
            print(f"  Current: {diff['current_result']}")
            print(
                f"  Experimental: {diff['experimental_result']} (via {diff['experimental_strategy']})"
            )
            print()

    return comparison_result


def performance_test():
    """Test performance of both methods."""
    print("=== Performance Test ===")
    print()

    # Create a larger test set
    test_bylines = [
        "By John Smith",
        "By Sarah Johnson Special to The Times",
        "By The Associated Press",
        "By Jennifer Brown, staff writer",
        "Reuters",
    ] * 20  # 100 total tests

    current_cleaner = BylineCleaner(enable_telemetry=False)
    experimental_cleaner = ExperimentalBylineCleaner(enable_telemetry=False)

    # Test current method
    start_time = time.time()
    for byline in test_bylines:
        current_cleaner.clean_byline(byline)
    current_total_time = time.time() - start_time

    # Test experimental method
    start_time = time.time()
    for byline in test_bylines:
        experimental_cleaner.clean_byline_multi_strategy(byline)
    experimental_total_time = time.time() - start_time

    print(f"Test set size: {len(test_bylines)} bylines")
    print(
        f"Current method:      {current_total_time * 1000:.1f}ms total, {current_total_time / len(test_bylines) * 1000:.2f}ms per byline"
    )
    print(
        f"Experimental method: {experimental_total_time * 1000:.1f}ms total, {experimental_total_time / len(test_bylines) * 1000:.2f}ms per byline"
    )
    print(
        f"Performance ratio: {experimental_total_time / current_total_time:.1f}x slower"
    )
    print()


def detailed_strategy_analysis():
    """Analyze which strategies work best for different byline types."""
    print("=== Detailed Strategy Analysis ===")
    print()

    test_cases = [
        ("By DORIAN DUCRE Special tot he Courier-Post", "Special to pattern"),
        ("By The Associated Press", "Wire service"),
        ("By John Smith", "Simple byline"),
        ("By Sarah Johnson and Mike Davis", "Multiple authors"),
        ("By Jennifer Brown, staff writer", "Title included"),
        ("Staff Report", "Generic attribution"),
    ]

    experimental_cleaner = ExperimentalBylineCleaner(enable_telemetry=False)

    for byline, category in test_cases:
        print(f"Byline: '{byline}' ({category})")

        result = experimental_cleaner.clean_byline_multi_strategy(
            byline, return_comparison=True
        )

        print(f"Best result: {result['best_result']} (via {result['strategy_used']})")
        print("All strategies attempted:")

        for strategy_result in result["all_results"]:
            strategy = strategy_result["strategy"]
            authors = strategy_result["authors"]
            overall = strategy_result["overall"]
            print(f"  {strategy}: {authors} (score: {overall:.3f})")

        print()


def main():
    """Run all comparison tests."""
    print("Byline Cleaner Method Comparison")
    print("=" * 50)
    print()

    # Test our specific 'Special to' cases
    test_special_to_cases()
    print()

    # Test diverse bylines
    test_diverse_bylines()
    print()

    # Performance comparison
    performance_test()
    print()

    # Detailed strategy analysis
    detailed_strategy_analysis()

    print("Comparison complete!")
    print()
    print("Next steps:")
    print("1. Review the results above")
    print("2. Identify areas where experimental method performs better")
    print("3. Consider integration based on data")
    print("4. Run on larger dataset if needed")


if __name__ == "__main__":
    main()
