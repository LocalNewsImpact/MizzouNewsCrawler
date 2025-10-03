#!/usr/bin/env python3
"""Test script to verify user agent rotation and cookie clearing."""

import logging
import time
from src.crawler import ContentExtractor

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def test_user_agent_rotation():
    """Test user agent rotation and session management."""
    print("Testing User Agent Rotation and Cookie Management")
    print("=" * 50)

    # Initialize extractor
    extractor = ContentExtractor()

    # Test URLs from different domains
    test_urls = [
        "https://httpbin.org/user-agent",  # Returns the user agent used
        "https://httpbin.org/headers",  # Returns all headers
        "https://httpbin.org/cookies",  # Returns cookies
    ]

    print(f"\nInitial user agent pool size: {len(extractor.user_agent_pool)}")
    print("Sample user agents:")
    for i, ua in enumerate(extractor.user_agent_pool[:3]):
        print(f"  {i + 1}. {ua[:60]}...")

    print("\nTesting rotation with multiple requests...")

    # Make multiple requests to trigger rotation
    for i in range(12):  # Should trigger at least one rotation
        try:
            url = test_urls[i % len(test_urls)]
            print(f"\n--- Request {i + 1} to {url} ---")

            # Get session for this URL (may trigger rotation)
            session = extractor._get_domain_session(url)
            current_ua = session.headers.get("User-Agent", "Unknown")

            print(f"Using UA: {current_ua[:60]}...")

            # Make the request
            response = session.get(url, timeout=10)
            if response.status_code == 200:
                print(f"✅ Request successful (Status: {response.status_code})")

                # For httpbin user-agent endpoint, show what was detected
                if "user-agent" in url:
                    data = response.json()
                    detected_ua = data.get("user-agent", "Unknown")
                    print(f"   Server detected UA: {detected_ua[:60]}...")

                    # Verify it matches what we sent
                    if detected_ua == current_ua:
                        print("   ✅ User agent correctly transmitted")
                    else:
                        print("   ❌ User agent mismatch!")

            else:
                print(f"❌ Request failed (Status: {response.status_code})")

            # Small delay between requests
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ Request failed: {e}")

    # Show rotation statistics
    print("\n--- Final Rotation Statistics ---")
    stats = extractor.get_rotation_stats()
    print(f"Total domains accessed: {stats['total_domains_accessed']}")
    print(f"Active sessions: {stats['active_sessions']}")
    print(f"Request counts per domain: {stats['request_counts']}")

    print("\nDomain-specific user agents:")
    for domain, ua in stats["domain_user_agents"].items():
        print(f"  {domain}: {ua}")

    print("\n--- Test Cookie Clearing ---")
    # Test that cookies are cleared between user agent changes
    cookie_test_url = "https://httpbin.org/cookies/set/test_cookie/12345"

    try:
        session = extractor._get_domain_session(cookie_test_url)
        print("Setting test cookie...")
        response = session.get(cookie_test_url, timeout=10)

        if response.status_code == 200:
            print("✅ Cookie set successfully")

            # Force a user agent rotation by making many requests
            print("Forcing user agent rotation...")
            for _ in range(15):
                extractor._get_domain_session("https://httpbin.org/")

            # Check if cookies were cleared
            new_session = extractor._get_domain_session("https://httpbin.org/cookies")
            response = new_session.get("https://httpbin.org/cookies", timeout=10)

            if response.status_code == 200:
                data = response.json()
                cookies = data.get("cookies", {})
                if "test_cookie" in cookies:
                    print("❌ Cookie persisted after rotation (not properly cleared)")
                else:
                    print("✅ Cookies properly cleared after user agent rotation")

    except Exception as e:
        print(f"Cookie test failed: {e}")

    print("\n--- Test Complete ---")
    print("User agent rotation and cookie management test finished.")


if __name__ == "__main__":
    test_user_agent_rotation()
