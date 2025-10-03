#!/usr/bin/env python3
"""
Comprehensive test for the byline cleaner apostrophe and comma handling fix.
"""

from src.utils.byline_cleaner import BylineCleaner


def test_comprehensive_apostrophe_comma_handling():
    """Test various combinations of apostrophes and commas in names."""
    cleaner = BylineCleaner()

    test_cases = [
        # "Last, First" patterns (should be reordered)
        ("O'Connor, Sean", ["Sean O'Connor"]),
        ("O'brien, Mary Jane", ["Mary Jane O'brien"]),
        ("McDonald, Ronald", ["Ronald McDonald"]),
        ("D'Angelo, Michael", ["Michael D'Angelo"]),
        ("O'Malley, Patrick", ["Patrick O'Malley"]),
        # Regular "and" separated names (should stay separate)
        ("Sean O'Connor and Mary O'Brien", ["Sean O'Connor", "Mary O'Brien"]),
        (
            "Patrick O'Reilly and D'Angelo Russell",
            ["Patrick O'Reilly", "D'Angelo Russell"],
        ),
        # Mixed content (comma with titles - should extract names only)
        (
            "O'Connor, Sean, Staff Reporter",
            ["O'Connor", "Sean"],
        ),  # 3 parts: extract names
        ("Mary O'Brien, News Editor", ["Mary O'Brien"]),
        ("By Sean O'Connor, Tribune", ["Sean O'Connor"]),
        # Single names (should pass through)
        ("Sean O'Connor", ["Sean O'Connor"]),
        ("Mary O'Brien", ["Mary O'Brien"]),
        ("D'Angelo", ["D'Angelo"]),
        # Edge cases that should NOT be treated as "Last, First"
        ("Editor, Staff Reporter", []),  # Both are titles
        ("Photos, John Smith", ["John Smith"]),  # Photo credit + name
        ("O'Connor, Sean, Mary Jane", ["O'Connor", "Sean", "Mary Jane"]),  # 3+ parts
        # Cases with apostrophes in various positions
        ("O'Sullivan, Patrick James", ["Patrick James O'Sullivan"]),
        ("D'Artagnan, Jean-Luc", ["Jean-Luc D'Artagnan"]),
    ]

    print("🧪 COMPREHENSIVE APOSTROPHE & COMMA HANDLING TEST")
    print("=" * 70)

    passed = 0
    failed = 0

    for i, (input_text, expected) in enumerate(test_cases, 1):
        print(f"\n{i:2d}. Input:    '{input_text}'")
        print(f"    Expected: {expected}")

        try:
            result = cleaner.clean_byline(input_text)
            print(f"    Got:      {result}")

            # Compare results
            if result == expected:
                print("    ✅ PASSED")
                passed += 1
            else:
                print("    ❌ FAILED")
                failed += 1

                # Detailed analysis
                if len(result) != len(expected):
                    print(
                        f"       Length mismatch: got {len(result)}, expected {len(expected)}"
                    )
                else:
                    for j, (got, exp) in enumerate(zip(result, expected, strict=False)):
                        if got != exp:
                            print(f"       Name {j + 1} mismatch: '{got}' != '{exp}'")

        except Exception as e:
            print(f"    ❌ ERROR: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed} passed, {failed} failed")

    if failed == 0:
        print(
            "🎉 ALL TESTS PASSED! Apostrophe and comma handling is working correctly."
        )
    else:
        print(f"⚠️  {failed} tests failed. Some issues need attention.")

    return failed == 0


if __name__ == "__main__":
    test_comprehensive_apostrophe_comma_handling()
