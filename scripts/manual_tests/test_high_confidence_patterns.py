#!/usr/bin/env python3

"""
Test script to verify high-confidence boilerplate pattern detection
works correctly for social media sharing buttons and other obvious
boilerplate that is shorter than the 150-character threshold.
"""

from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def test_high_confidence_detection():
    """Test the high-confidence boilerplate detection functionality."""

    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    # Test cases: patterns that should be detected as high-confidence
    high_confidence_patterns = [
        "Facebook Twitter WhatsApp SMS Email",
        "Facebook Twitter WhatsApp SMS Email Print Copy article link Save",
        "Share on Facebook Twitter WhatsApp",
        "Back to top",
        "Subscribe to our newsletter",
        "All rights reserved",
        "Follow us on Facebook Twitter Instagram",
        "Share this article",
        "Return to top",
    ]

    # Test cases: patterns that should NOT be detected as high-confidence
    regular_patterns = [
        "This is regular article content that should not be flagged",
        "The mayor announced a new initiative today",
        "Weather forecast calls for rain this weekend",
        "Local school district approves budget increase",
    ]

    print("🧪 TESTING HIGH-CONFIDENCE BOILERPLATE DETECTION")
    print("=" * 60)

    print("\n✅ PATTERNS THAT SHOULD BE HIGH-CONFIDENCE:")
    print("-" * 50)
    all_correct = True
    for pattern in high_confidence_patterns:
        result = cleaner._is_high_confidence_boilerplate(pattern)
        status = "✓" if result else "✗"
        print(f"{status} '{pattern}' (length: {len(pattern)}) -> {result}")
        if not result:
            all_correct = False

    print(f"\nHigh-confidence detection: {'PASS' if all_correct else 'FAIL'}")

    print("\n❌ PATTERNS THAT SHOULD NOT BE HIGH-CONFIDENCE:")
    print("-" * 50)
    all_correct_neg = True
    for pattern in regular_patterns:
        result = cleaner._is_high_confidence_boilerplate(pattern)
        status = "✓" if not result else "✗"
        print(f"{status} '{pattern}' -> {result}")
        if result:
            all_correct_neg = False

    print(f"\nRegular content detection: {'PASS' if all_correct_neg else 'FAIL'}")

    # Test the length override logic
    print("\n🔧 TESTING LENGTH OVERRIDE LOGIC:")
    print("-" * 50)

    test_segments = [
        {"text": "Facebook Twitter WhatsApp SMS Email", "expected": True},
        {
            "text": "This is a very long piece of text that exceeds 150 characters and should be included based on length alone, not because it's high-confidence boilerplate content.",
            "expected": True,
        },
        {"text": "Back to top", "expected": True},
        {"text": "Short regular text", "expected": False},
    ]

    override_correct = True
    for seg in test_segments:
        text = seg["text"]
        expected = seg["expected"]

        # Apply the same logic as the content cleaner
        would_include = len(text) >= 150 or cleaner._is_high_confidence_boilerplate(
            text
        )

        status = "✓" if would_include == expected else "✗"
        reason = (
            "Length >= 150"
            if len(text) >= 150
            else "High-confidence override"
            if cleaner._is_high_confidence_boilerplate(text)
            else "Filtered out"
        )

        print(f"{status} '{text[:50]}...' -> {would_include} ({reason})")

        if would_include != expected:
            override_correct = False

    print(f"\nLength override logic: {'PASS' if override_correct else 'FAIL'}")

    # Overall result
    overall_pass = all_correct and all_correct_neg and override_correct
    print(f"\n🎯 OVERALL TEST RESULT: {'PASS ✅' if overall_pass else 'FAIL ❌'}")

    if overall_pass:
        print("\n✨ High-confidence boilerplate detection is working correctly!")
        print("   Social media sharing buttons and other obvious boilerplate")
        print("   patterns will now be detected even when under 150 characters.")
    else:
        print("\n⚠️  Issues detected with high-confidence pattern detection.")
        print("   Review the failed test cases above.")

    return overall_pass


if __name__ == "__main__":
    test_high_confidence_detection()
