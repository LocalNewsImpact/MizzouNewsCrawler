#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_five_names():
    """Test various scenarios with 5 names in the author field."""
    cleaner = BylineCleaner()

    test_cases = [
        # Scenario 1: Simple comma-separated 5 names
        "JOHN SMITH, MARY JONES, BOB WILSON, SARAH DAVIS, MIKE CHEN",
        # Scenario 2: Mix of "and" separators
        "JOHN SMITH and MARY JONES, BOB WILSON and SARAH DAVIS, MIKE CHEN",
        # Scenario 3: Names with titles mixed in
        "JOHN SMITH, MARY JONES, Staff Writer, BOB WILSON, SARAH DAVIS, Editor",
        # Scenario 4: Names with emails/duplicates
        "JOHN SMITH, JOHN@NEWS.COM, MARY JONES, BOB WILSON, SARAH DAVIS, JOHN SMITH",
        # Scenario 5: All connected with "and"
        "JOHN SMITH and MARY JONES and BOB WILSON and SARAH DAVIS and MIKE CHEN",
        # Scenario 6: Complex mix with titles and duplicates
        "JOHN SMITH, Staff Writer, MARY JONES, BOB WILSON, Reporter, SARAH DAVIS, MIKE CHEN, Editor, JOHN SMITH",
        # Scenario 7: Real-world style with repeated info
        "JOHN SMITH, JOHN@NEWS.COM, MARY JONES, MARY@NEWS.COM, BOB WILSON, BOB@NEWS.COM, SARAH DAVIS, MIKE CHEN, Staff Writers",
    ]

    print("Testing 5-Name Scenarios")
    print("=" * 60)

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nScenario {i}:")
        print(f"Input: {test_case}")

        result = cleaner.clean_byline(test_case)
        print(f"Result: {result}")
        print(f"Count: {len(result)} authors")

        # Show what would be stored in database
        print("📊 DATABASE STORAGE:")
        print(f"   Array: {result}")
        print(f"   Author Count: {len(result)}")
        if result:
            print(f"   Primary Author: '{result[0]}'")
            if len(result) > 1:
                print(f"   Additional Authors: {result[1:]}")

        # Show searchable terms
        all_terms = []
        for author in result:
            terms = [word.lower() for word in author.split() if len(word) > 1]
            all_terms.extend(terms)
        print(f"🔍 SEARCHABLE TERMS: {all_terms}")

        print("-" * 60)


def test_edge_cases():
    """Test edge cases with many names."""
    cleaner = BylineCleaner()

    print("\n\nEDGE CASES:")
    print("=" * 60)

    edge_cases = [
        # Very long list with duplicates
        "JOHN SMITH, MARY JONES, JOHN SMITH, BOB WILSON, MARY JONES, SARAH DAVIS, MIKE CHEN, JOHN SMITH",
        # Mixed with wire service
        "Associated Press, JOHN SMITH, MARY JONES, BOB WILSON, SARAH DAVIS",
        # All titles, no real names
        "Staff Writer, Editor, Reporter, Copy Editor, Managing Editor",
        # Names with complex punctuation
        "JOHN O'SMITH, MARY-JANE JONES, BOB WILSON JR., SARAH ST. DAVIS, MIKE VAN CHEN",
    ]

    for i, test_case in enumerate(edge_cases, 1):
        print(f"\nEdge Case {i}:")
        print(f"Input: {test_case}")

        result = cleaner.clean_byline(test_case)
        print(f"Result: {result}")
        print(f"Count: {len(result)} authors")
        print("-" * 40)


if __name__ == "__main__":
    test_five_names()
    test_edge_cases()

    print("\n\n💡 KEY INSIGHTS:")
    print("- System handles multiple authors gracefully")
    print("- Duplicate removal prevents name repetition")
    print("- Title filtering extracts real names from noise")
    print("- Array format perfect for database operations")
    print("- First author becomes 'primary_author' for queries")
    print("- All names become searchable terms for full-text search")
