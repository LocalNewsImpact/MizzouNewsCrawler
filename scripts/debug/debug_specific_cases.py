#!/usr/bin/env python3
"""
Debug specific problematic cases in byline cleaning.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils.byline_cleaner import BylineCleaner


def debug_case(byline, description):
    """Debug a specific byline case with detailed output."""
    print(f"\n{'='*60}")
    print(f"DEBUGGING: {description}")
    print(f"Input: '{byline}'")
    print(f"{'='*60}")

    cleaner = BylineCleaner(enable_telemetry=True)

    # Test with detailed JSON output
    result = cleaner.clean_byline(byline, return_json=True)

    print(f"Final Result: {result.get('authors', [])}")

    # Check wire service detection specifically
    is_wire = cleaner._is_wire_service(byline)
    print(f"Wire service detected: {is_wire}")

    # Check organization filtering
    filtered = cleaner._filter_organization_words(byline)
    print(f"After org filtering: '{filtered}'")

    # Check pattern removal
    after_patterns = cleaner._remove_patterns(byline)
    print(f"After pattern removal: '{after_patterns}'")

    return result

def main():
    """Test the specific problematic cases."""

    # Test cases from user's report
    test_cases = [
        ("matthew mcfarland", "Valid person name being removed"),
        ("maggie lebeau", "Valid person name being removed"),
        ("jack silberberg • .com", "Name with domain suffix"),
        ("Associated Press", "Wire service should be preserved"),
        ("CNN Newsource", "Wire service should be preserved"),
        ("Reuters", "Wire service should be preserved"),
        ("AP", "Wire service abbreviation should be preserved"),
    ]

    results = []

    for byline, description in test_cases:
        result = debug_case(byline, description)
        results.append((byline, result.get('authors', []), description))

    print(f"\n{'='*80}")
    print("SUMMARY OF ISSUES:")
    print(f"{'='*80}")

    for byline, authors, description in results:
        status = "✅ OK" if authors else "❌ PROBLEM"
        print(f"{status} '{byline}' -> {authors}")
        if not authors and any(keyword in description.lower() for keyword in ['wire service', 'person name']):
            print(f"    ⚠️  {description}")

    print(f"\n{'='*80}")
    print("WIRE SERVICE DETECTION TEST:")
    print(f"{'='*80}")

    cleaner = BylineCleaner()
    wire_services = ["Associated Press", "AP", "Reuters", "CNN Newsource", "Bloomberg"]

    for wire in wire_services:
        is_detected = cleaner._is_wire_service(wire)
        print(f"'{wire}' -> Wire service: {is_detected}")

if __name__ == "__main__":
    main()
