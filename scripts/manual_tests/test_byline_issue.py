#!/usr/bin/env python3
"""
Test case to debug the specific byline cleaning issue.

Issue: "By DORIAN DUCRE Special tot he Courier-Post"
Should clean to: "Dorian Ducre"
Actually cleans to: "Dorian Ducre Special Tot He"
"""

import os
import sys

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.utils.byline_cleaner import BylineCleaner


def test_specific_case():
    """Test the specific problematic byline."""
    cleaner = BylineCleaner(enable_telemetry=False)

    # The problematic byline
    byline = "By DORIAN DUCRE Special tot he Courier-Post"

    print(f"Original byline: {byline}")

    # Clean it
    result = cleaner.clean_byline(
        byline=byline, return_json=True, source_name="Courier-Post"
    )

    print(f"Cleaned result: {result}")
    print(f"Authors: {result.get('authors', [])}")

    # Expected result should be just "Dorian Ducre"
    expected = ["Dorian Ducre"]
    actual = result.get("authors", [])

    if actual == expected:
        print("✅ Test PASSED")
    else:
        print("❌ Test FAILED")
        print(f"Expected: {expected}")
        print(f"Actual: {actual}")


def test_similar_cases():
    """Test similar patterns that should be handled."""
    cleaner = BylineCleaner(enable_telemetry=False)

    test_cases = [
        # Original case
        (
            "By DORIAN DUCRE Special tot he Courier-Post",
            "Courier-Post",
            ["Dorian Ducre"],
        ),
        # Proper spelling
        (
            "By DORIAN DUCRE Special to the Courier-Post",
            "Courier-Post",
            ["Dorian Ducre"],
        ),
        # Different publications
        ("By JANE SMITH Special to the Herald", "Herald", ["Jane Smith"]),
        # All caps with special correspondent
        ("By JOHN DOE SPECIAL CORRESPONDENT", None, ["John Doe"]),
        # Mixed case
        ("By Mary Johnson Special to The Times", "The Times", ["Mary Johnson"]),
    ]

    for byline, source, expected in test_cases:
        print(f"\nTesting: {byline}")
        result = cleaner.clean_byline(
            byline=byline, return_json=True, source_name=source
        )

        # Handle both dict and list returns
        if isinstance(result, dict):
            actual = result.get("authors", [])
        else:
            actual = result if isinstance(result, list) else []

        if actual == expected:
            print(f"✅ PASS: {actual}")
        else:
            print(f"❌ FAIL: Expected {expected}, got {actual}")


if __name__ == "__main__":
    print("Testing specific byline cleaning issue...")
    test_specific_case()

    print("\n" + "=" * 50)
    print("Testing similar cases...")
    test_similar_cases()
