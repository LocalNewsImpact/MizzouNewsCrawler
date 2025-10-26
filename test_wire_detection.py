#!/usr/bin/env python3
"""Quick test of wire service detection in content_type_detector."""

from src.utils.content_type_detector import ContentTypeDetector


def test_wire_detection():
    """Test wire service detection with sample content."""
    detector = ContentTypeDetector()
    
    # Test 1: CNN URL pattern
    print("\n=== Test 1: CNN URL Pattern ===")
    result = detector.detect(
        url="https://abc17news.com/cnn-health/2025/10/22/article-title",
        title="Some Health Article",
        metadata={},
        content=None,
    )
    print(f"Status: {result.status if result else 'None'}")
    print(f"Confidence: {result.confidence if result else 'N/A'}")
    print(f"Evidence: {result.evidence if result else 'N/A'}")
    
    # Test 2: AP dateline in content
    print("\n=== Test 2: AP Dateline in Content ===")
    content_with_ap = """WASHINGTON (AP) — The president announced today a new policy initiative that will affect millions of Americans. The announcement came during a press conference at the White House."""
    result = detector.detect(
        url="https://example.com/article",
        title="President Announces Policy",
        metadata={},
        content=content_with_ap,
    )
    print(f"Status: {result.status if result else 'None'}")
    print(f"Confidence: {result.confidence if result else 'N/A'}")
    print(f"Evidence: {result.evidence if result else 'N/A'}")
    
    # Test 3: Reuters closing attribution
    print("\n=== Test 3: Reuters Closing Attribution ===")
    content_with_reuters = """This is a long article about international news that goes on for many paragraphs and covers various topics related to global affairs and economics.

Additional reporting by Reuters. ©2025 Reuters. All rights reserved."""
    result = detector.detect(
        url="https://example.com/world/article",
        title="Global Markets Update",
        metadata={},
        content=content_with_reuters,
    )
    print(f"Status: {result.status if result else 'None'}")
    print(f"Confidence: {result.confidence if result else 'N/A'}")
    print(f"Evidence: {result.evidence if result else 'N/A'}")
    
    # Test 4: Combined URL + content detection
    print("\n=== Test 4: Combined URL + Content ===")
    result = detector.detect(
        url="https://abc17news.com/cnn-national/2025/10/20/story",
        title="National News Story",
        metadata={},
        content="NEW YORK (CNN) — Breaking news from the city that never sleeps.",
    )
    print(f"Status: {result.status if result else 'None'}")
    print(f"Confidence: {result.confidence if result else 'N/A'}")
    print(f"Evidence: {result.evidence if result else 'N/A'}")
    
    # Test 5: Non-wire article (should return None or other type)
    print("\n=== Test 5: Local Article (No Wire) ===")
    result = detector.detect(
        url="https://localcounty news.com/local/city-council-meeting",
        title="City Council Votes on Budget",
        metadata={},
        content="The city council met last night to discuss the annual budget and approved several initiatives for local infrastructure improvements.",
    )
    print(f"Status: {result.status if result else 'None (no wire detected)'}")
    if result:
        print(f"Confidence: {result.confidence}")
        print(f"Reason: {result.reason}")


if __name__ == "__main__":
    test_wire_detection()
