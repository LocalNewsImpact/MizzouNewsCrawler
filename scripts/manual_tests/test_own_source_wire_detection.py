#!/usr/bin/env python3
"""
Test script to demonstrate enhanced wire service detection with source matching.

This test shows how the byline cleaner now distinguishes between:
1. Local content (wire service name matches source) -> extract author, don't mark as wire
2. Syndicated content (wire service from different source) -> preserve wire name, mark as wire
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils.byline_cleaner import BylineCleaner


def test_own_source_wire_detection():
    """Test enhanced wire service detection with source matching."""

    print("=== Enhanced Wire Service Detection Test ===\n")

    cleaner = BylineCleaner(enable_telemetry=False)

    # Test cases: (byline, source_name, expected_behavior)
    test_cases = [
        # Case 1: Associated Press publishing their own content
        (
            "By John Smith, Associated Press",
            "Associated Press",
            "LOCAL: Should extract 'John Smith', not mark as wire",
        ),
        # Case 2: Local paper publishing AP content
        (
            "By Associated Press",
            "Springfield Tribune",
            "SYNDICATED: Should preserve 'Associated Press', mark as wire",
        ),
        # Case 3: Reuters publishing their own content
        (
            "By Jane Doe, Reuters",
            "Reuters",
            "LOCAL: Should extract 'Jane Doe', not mark as wire",
        ),
        # Case 4: Local paper publishing Reuters content
        (
            "By Reuters",
            "Daily News",
            "SYNDICATED: Should preserve 'Reuters', mark as wire",
        ),
        # Case 5: CNN publishing their own content
        (
            "By Tom Johnson, CNN",
            "CNN",
            "LOCAL: Should extract 'Tom Johnson', not mark as wire",
        ),
        # Case 6: Local station using CNN content
        ("By CNN", "KMIZ-TV", "SYNDICATED: Should preserve 'CNN', mark as wire"),
        # Case 7: Regular author from local source
        (
            "By Sarah Johnson",
            "Springfield Tribune",
            "LOCAL: Should extract 'Sarah Johnson', not mark as wire",
        ),
    ]

    for i, (byline, source_name, expected) in enumerate(test_cases, 1):
        print(f"Test {i}: {expected}")
        print(f"Byline: '{byline}'")
        print(f"Source: '{source_name}'")

        # Test with JSON return to see wire detection
        result = cleaner.clean_byline(
            byline=byline, return_json=True, source_canonical_name=source_name
        )

        print(f"Authors: {result['authors']}")
        print(f"Wire Services: {result['wire_services']}")
        print(f"Is Wire Content: {result['is_wire_content']}")

        # Show the expected vs actual behavior
        if "LOCAL" in expected:
            if result["is_wire_content"]:
                print("❌ ERROR: Local content incorrectly marked as wire")
            else:
                print("✅ CORRECT: Local content not marked as wire")
        elif "SYNDICATED" in expected:
            if result["is_wire_content"]:
                print("✅ CORRECT: Syndicated content marked as wire")
            else:
                print("❌ ERROR: Syndicated content not marked as wire")

        print("-" * 60)


if __name__ == "__main__":
    test_own_source_wire_detection()
