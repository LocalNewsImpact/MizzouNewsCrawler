#!/usr/bin/env python3
"""
Test the new byline cleaning algorithm against original telemetry data
to identify problematic cases and analyze the delta.
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import json
from src.utils.byline_cleaner import BylineCleaner


def test_against_telemetry():
    """Test new algorithm against original telemetry data."""

    print("🔍 TESTING NEW ALGORITHM AGAINST TELEMETRY DATA")
    print("=" * 60)

    # Connect to database
    db_path = os.path.join(os.path.dirname(__file__), "data", "mizzou.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Test specific problematic cases
    test_cases = [
        # Person names that should NOT be removed
        ("matthew mcfarland", "Matthew McFarland should be preserved"),
        ("maggie lebeau", "Maggie LeBeau should be preserved"),
        # Domain suffix case - should clean to just the name
        ("JACK SILBERBERG • @LACLEDERECORD.COM", "Should clean to 'Jack Silberberg'"),
        # Wire services that SHOULD be preserved as-is when they're the sole author
        ("Associated Press", "Wire service should be preserved"),
        ("CNN Newsource", "Wire service should be preserved"),
        ("By Associated Press", "Wire service with 'By' should be preserved"),
        ("The Associated Press", "Wire service with 'The' should be preserved"),
    ]

    cleaner = BylineCleaner(enable_telemetry=False)

    print("🧪 TESTING SPECIFIC CASES:")
    print("-" * 40)

    issues_found = []

    for raw_byline, description in test_cases:
        print(f"\nTest: {description}")
        print(f"Input: '{raw_byline}'")

        # Test new algorithm
        result = cleaner.clean_byline(raw_byline, return_json=False)
        print(f"Result: {result}")

        # Check for issues
        issue_detected = False

        if "matthew mcfarland" in raw_byline.lower():
            if not result or "matthew" not in str(result).lower():
                issue_detected = True
                issues_found.append(
                    f"❌ Matthew McFarland removed: '{raw_byline}' -> {result}"
                )

        elif "maggie lebeau" in raw_byline.lower():
            if not result or "maggie" not in str(result).lower():
                issue_detected = True
                issues_found.append(
                    f"❌ Maggie LeBeau removed: '{raw_byline}' -> {result}"
                )

        elif "jack silberberg" in raw_byline.lower():
            if not result or "jack" not in str(result).lower():
                issue_detected = True
                issues_found.append(
                    f"❌ Jack Silberberg removed: '{raw_byline}' -> {result}"
                )
            elif "@" in str(result) or ".com" in str(result).lower():
                issue_detected = True
                issues_found.append(
                    f"⚠️  Jack Silberberg not cleaned properly: '{raw_byline}' -> {result}"
                )

        elif any(
            wire in raw_byline.lower() for wire in ["associated press", "cnn newsource"]
        ):
            if not result:
                issue_detected = True
                issues_found.append(
                    f"❌ Wire service removed: '{raw_byline}' -> {result}"
                )

        status = "❌ ISSUE" if issue_detected else "✅ OK"
        print(f"Status: {status}")

    print(f"\n{'=' * 60}")
    print("🔍 COMPREHENSIVE TELEMETRY ANALYSIS:")
    print(f"{'=' * 60}")

    # Get sample of real telemetry data to test
    cursor.execute("""
        SELECT DISTINCT raw_byline, final_authors_display, final_authors_json, 
               has_wire_service, likely_valid_authors
        FROM byline_cleaning_telemetry 
        WHERE raw_byline IS NOT NULL 
        AND raw_byline != ''
        ORDER BY RANDOM()
        LIMIT 50
    """)

    telemetry_results = cursor.fetchall()

    print(f"Testing {len(telemetry_results)} random telemetry cases...")

    regressions = []
    improvements = []
    unchanged = []

    for i, (raw_byline, old_display, old_json, is_wire, was_valid) in enumerate(
        telemetry_results
    ):
        # Parse old result
        try:
            old_authors = json.loads(old_json) if old_json else []
        except:
            old_authors = [old_display] if old_display else []

        # Test new algorithm
        new_authors = cleaner.clean_byline(raw_byline, return_json=False)

        # Compare results
        old_set = set(str(author).lower().strip() for author in old_authors)
        new_set = set(str(author).lower().strip() for author in new_authors)

        if old_set == new_set:
            unchanged.append({"raw": raw_byline, "result": new_authors})
        elif len(new_authors) > len(old_authors) or (new_authors and not old_authors):
            improvements.append(
                {
                    "raw": raw_byline,
                    "old": old_authors,
                    "new": new_authors,
                    "reason": "More/better authors extracted",
                }
            )
        elif len(new_authors) < len(old_authors) or (old_authors and not new_authors):
            regressions.append(
                {
                    "raw": raw_byline,
                    "old": old_authors,
                    "new": new_authors,
                    "reason": "Fewer/lost authors",
                }
            )

    print("\n📊 TELEMETRY COMPARISON RESULTS:")
    print(f"   Unchanged: {len(unchanged)}")
    print(f"   Improvements: {len(improvements)}")
    print(f"   Regressions: {len(regressions)}")

    if regressions:
        print("\n⚠️  REGRESSIONS FOUND:")
        for reg in regressions[:10]:  # Show first 10
            print(f"   '{reg['raw']}' -> Old: {reg['old']} | New: {reg['new']}")

    if improvements:
        print("\n✅ IMPROVEMENTS FOUND:")
        for imp in improvements[:5]:  # Show first 5
            print(f"   '{imp['raw']}' -> Old: {imp['old']} | New: {imp['new']}")

    # Summary
    print(f"\n{'=' * 60}")
    print("🎯 SUMMARY:")
    print(f"{'=' * 60}")

    if issues_found:
        print("❌ SPECIFIC ISSUES FOUND:")
        for issue in issues_found:
            print(f"   {issue}")
    else:
        print("✅ All specific test cases passed!")

    if regressions:
        print(f"\n⚠️  {len(regressions)} regressions found in telemetry comparison")
    else:
        print("\n✅ No regressions found in telemetry comparison")

    # Identify the three specific issues from user's report
    print("\n🔍 USER-REPORTED ISSUES ANALYSIS:")

    specific_issues = ["matthew mcfarland", "maggie lebeau", "jack silberberg • .com"]

    for issue_case in specific_issues:
        result = cleaner.clean_byline(issue_case, return_json=False)
        print(f"   '{issue_case}' -> {result}")

        # Check if this should be preserved
        if "matthew mcfarland" in issue_case:
            if not result or "matthew" not in str(result).lower():
                print("     ❌ Matthew McFarland incorrectly removed!")
            else:
                print("     ✅ Matthew McFarland preserved correctly")

        elif "maggie lebeau" in issue_case:
            if not result or "maggie" not in str(result).lower():
                print("     ❌ Maggie LeBeau incorrectly removed!")
            else:
                print("     ✅ Maggie LeBeau preserved correctly")

        elif "jack silberberg" in issue_case:
            if not result or "jack" not in str(result).lower():
                print("     ❌ Jack Silberberg incorrectly removed!")
            elif any(x in str(result).lower() for x in ["@", ".com", "•"]):
                print(
                    "     ⚠️  Jack Silberberg should be cleaned to just 'Jack Silberberg'"
                )
            else:
                print("     ✅ Jack Silberberg cleaned correctly")

    conn.close()


if __name__ == "__main__":
    test_against_telemetry()
