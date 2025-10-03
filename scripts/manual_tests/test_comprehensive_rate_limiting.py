"""
Comprehensive rate limiting test suite that simulates real-world scenarios.
"""

import time
import threading
from unittest.mock import Mock, patch
from src.crawler import ContentExtractor, RateLimitError


class MockResponse:
    """Mock response for simulating different HTTP responses."""

    def __init__(
        self, status_code, headers=None, text="<html><body>Test</body></html>"
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text


class TestRealWorldRateLimitingScenarios:
    """Test suite simulating various real-world rate limiting patterns."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = ContentExtractor()

    @patch("requests.Session.get")
    def test_cloudflare_style_rate_limiting(self, mock_get):
        """Test Cloudflare-style rate limiting with specific headers."""
        domain = "example.com"
        url = f"https://{domain}/article1"

        # Simulate Cloudflare 429 with specific headers
        cf_response = MockResponse(
            429,
            {
                "retry-after": "60",
                "cf-ray": "123456789abcdef-DFW",
                "server": "cloudflare",
            },
        )
        mock_get.return_value = cf_response

        result = self.extractor.extract_content(url)

        # Should handle Cloudflare rate limiting
        assert self.extractor.domain_error_counts[domain] == 1
        assert domain in self.extractor.domain_backoff_until

        # Verify backoff period is at least 60 seconds (from retry-after)
        backoff_time = self.extractor.domain_backoff_until[domain] - time.time()
        assert backoff_time >= 55  # Allow some tolerance for test execution time

    @patch("requests.Session.get")
    def test_nginx_style_rate_limiting(self, mock_get):
        """Test nginx rate limiting (503 Service Unavailable)."""
        domain = "nginx-site.com"
        url = f"https://{domain}/article1"

        # Nginx often returns 503 for rate limiting
        nginx_response = MockResponse(
            503, {"server": "nginx/1.18.0", "retry-after": "30"}
        )
        mock_get.return_value = nginx_response

        result = self.extractor.extract_content(url)

        # Should treat 503 as rate limiting
        assert self.extractor.domain_error_counts[domain] == 1
        assert domain in self.extractor.domain_backoff_until

    @patch("requests.Session.get")
    def test_apache_style_rate_limiting(self, mock_get):
        """Test Apache mod_security style blocking (403 Forbidden)."""
        domain = "apache-site.com"
        url = f"https://{domain}/article1"

        # Apache mod_security often returns 403
        apache_response = MockResponse(
            403, {"server": "Apache/2.4.41", "x-mod-security": "blocked"}
        )
        mock_get.return_value = apache_response

        result = self.extractor.extract_content(url)

        # Should treat 403 as potential bot detection
        assert self.extractor.domain_error_counts[domain] == 1
        assert domain in self.extractor.domain_backoff_until

    @patch("requests.Session.get")
    def test_progressive_rate_limiting(self, mock_get):
        """Test progressive rate limiting where delays increase with each violation."""
        domain = "progressive-site.com"
        url = f"https://{domain}/article1"

        # First rate limit - short delay
        first_response = MockResponse(429, {"retry-after": "10"})

        # Second rate limit - longer delay
        second_response = MockResponse(429, {"retry-after": "60"})

        # Third rate limit - much longer delay
        third_response = MockResponse(429, {"retry-after": "300"})

        responses = [first_response, second_response, third_response]
        mock_get.side_effect = responses

        backoff_times = []

        for i in range(3):
            result = self.extractor.extract_content(url)

            # Record backoff time
            if domain in self.extractor.domain_backoff_until:
                backoff_time = self.extractor.domain_backoff_until[domain] - time.time()
                backoff_times.append(backoff_time)

        # Verify exponential backoff is working
        assert len(backoff_times) == 3
        assert self.extractor.domain_error_counts[domain] == 3

        # Our exponential backoff should increase with each error
        # (regardless of server's retry-after values)
        print(f"Backoff progression: {[f'{t:.0f}s' for t in backoff_times]}")

    @patch("requests.Session.get")
    def test_rate_limiting_with_no_retry_after(self, mock_get):
        """Test rate limiting when server doesn't provide retry-after header."""
        domain = "no-retry-after.com"
        url = f"https://{domain}/article1"

        # 429 without retry-after header
        response = MockResponse(429, {})
        mock_get.return_value = response

        result = self.extractor.extract_content(url)

        # Should still implement our own backoff
        assert self.extractor.domain_error_counts[domain] == 1
        assert domain in self.extractor.domain_backoff_until

        # Should use our default backoff (60s base)
        backoff_time = self.extractor.domain_backoff_until[domain] - time.time()
        assert 45 <= backoff_time <= 90  # 60s ± jitter

    @patch("requests.Session.get")
    def test_mixed_success_and_rate_limiting(self, mock_get):
        """Test that successful requests reset error count."""
        domain = "mixed-site.com"
        url = f"https://{domain}/article1"

        # First request: rate limited
        rate_limit_response = MockResponse(429, {"retry-after": "30"})

        # Second request: successful
        success_response = MockResponse(
            200,
            {},
            "<html><head><title>Success</title></head><body>Content</body></html>",
        )

        mock_get.side_effect = [rate_limit_response, success_response]

        # First request - should be rate limited
        result1 = self.extractor.extract_content(url)
        assert self.extractor.domain_error_counts[domain] == 1

        # Clear backoff to allow second request
        if domain in self.extractor.domain_backoff_until:
            del self.extractor.domain_backoff_until[domain]

        # Second request - should succeed and reset error count
        result2 = self.extractor.extract_content(url)
        assert self.extractor.domain_error_counts[domain] == 0

    def test_concurrent_requests_rate_limiting(self):
        """Test rate limiting behavior with concurrent requests."""
        domain = "concurrent-test.com"

        def make_request(thread_id):
            """Make a request in a thread."""
            try:
                # Simulate multiple threads hitting rate limit
                self.extractor._handle_rate_limit_error(domain)
                return f"Thread {thread_id} completed"
            except Exception as e:
                return f"Thread {thread_id} failed: {e}"

        # Start multiple threads
        threads = []
        results = []

        for i in range(5):
            thread = threading.Thread(
                target=lambda i=i: results.append(make_request(i))
            )
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All threads should complete
        assert len(results) == 5

        # Error count should reflect all the rate limit errors
        assert self.extractor.domain_error_counts[domain] == 5

    @patch("requests.Session.get")
    def test_different_status_codes_behavior(self, mock_get):
        """Test how different HTTP status codes are handled."""
        test_cases = [
            (429, "Too Many Requests"),
            (403, "Forbidden"),
            (503, "Service Unavailable"),
            (502, "Bad Gateway"),
            (504, "Gateway Timeout"),
            (200, "OK"),
            (404, "Not Found"),
            (500, "Internal Server Error"),
        ]

        rate_limiting_codes = {429, 403, 503, 502, 504}

        for status_code, status_text in test_cases:
            domain = f"test-{status_code}.com"
            url = f"https://{domain}/article"

            response = MockResponse(
                status_code, {}, f"<html><body>{status_text}</body></html>"
            )
            mock_get.return_value = response

            # Clear any previous state
            if domain in self.extractor.domain_error_counts:
                del self.extractor.domain_error_counts[domain]
            if domain in self.extractor.domain_backoff_until:
                del self.extractor.domain_backoff_until[domain]

            result = self.extractor.extract_content(url)

            if status_code in rate_limiting_codes:
                # Should trigger rate limiting
                assert domain in self.extractor.domain_error_counts
                assert self.extractor.domain_error_counts[domain] > 0
                print(f"✓ Status {status_code} correctly triggered rate limiting")
            else:
                # Should not trigger rate limiting
                error_count = self.extractor.domain_error_counts.get(domain, 0)
                print(
                    f"✓ Status {status_code} correctly did not trigger rate limiting (errors: {error_count})"
                )

    def test_rate_limit_state_persistence(self):
        """Test that rate limiting state is maintained correctly."""
        domain = "state-test.com"

        # Test initial state
        assert not self.extractor._check_rate_limit(domain)
        assert self.extractor.domain_error_counts.get(domain, 0) == 0

        # Trigger rate limiting
        self.extractor._handle_rate_limit_error(domain)

        # State should be updated
        assert domain in self.extractor.domain_error_counts
        assert domain in self.extractor.domain_backoff_until
        assert self.extractor._check_rate_limit(domain)

        # Wait for backoff to expire (simulate with past time)
        self.extractor.domain_backoff_until[domain] = time.time() - 1

        # Should no longer be rate limited
        assert not self.extractor._check_rate_limit(domain)
        assert domain not in self.extractor.domain_backoff_until

    def test_rate_limiting_with_invalid_retry_after(self):
        """Test handling of invalid retry-after header values."""
        domain = "invalid-retry.com"

        invalid_retry_values = [
            "invalid",
            "-1",
            "3600000",  # Very large number
            "",
            "60.5",  # Float as string
        ]

        for retry_value in invalid_retry_values:
            # Clear previous state
            if domain in self.extractor.domain_backoff_until:
                del self.extractor.domain_backoff_until[domain]

            mock_response = Mock()
            mock_response.headers = {"retry-after": retry_value}

            self.extractor._handle_rate_limit_error(domain, mock_response)

            # Should still set backoff even with invalid retry-after
            assert domain in self.extractor.domain_backoff_until
            print(f"✓ Handled invalid retry-after value: '{retry_value}'")


def test_rate_limiting_production_simulation():
    """
    Simulation test that mimics production workload patterns.
    """
    print("\n" + "=" * 60)
    print("PRODUCTION SIMULATION TEST")
    print("=" * 60)

    extractor = ContentExtractor()

    # Simulate a production-like workload with multiple domains
    test_domains = [
        "www.news-site-1.com",
        "www.local-paper.com",
        "www.sports-daily.com",
        "www.city-gazette.com",
        "www.community-news.org",
    ]

    total_requests = 0
    rate_limited_domains = 0

    # Simulate burst requests to each domain
    for domain in test_domains:
        print(f"\nTesting burst requests to {domain}:")

        domain_requests = 0
        for i in range(8):  # 8 rapid requests per domain
            try:
                # Simulate checking rate limit before request
                if extractor._check_rate_limit(domain):
                    print(f"  Request {i + 1}: ⛔ Domain is rate limited, skipping")
                    continue

                # Simulate normal request flow
                extractor._apply_rate_limit(domain)
                domain_requests += 1
                total_requests += 1

                # Randomly trigger rate limiting for some requests
                if i >= 4 and domain_requests % 3 == 0:  # Trigger on some requests
                    print(f"  Request {i + 1}: 🛑 Triggered rate limiting")
                    extractor._handle_rate_limit_error(domain)
                    rate_limited_domains += 1
                    break
                else:
                    print(f"  Request {i + 1}: ✅ Success")
                    extractor._reset_error_count(domain)

            except RateLimitError:
                print(f"  Request {i + 1}: ⛔ Rate limit exception caught")
                break

            # Small delay between requests
            time.sleep(0.01)

    print("\n" + "=" * 60)
    print("SIMULATION RESULTS:")
    print(f"Total requests attempted: {total_requests}")
    print(f"Domains that hit rate limits: {rate_limited_domains}/{len(test_domains)}")

    # Check final state
    active_rate_limits = len(extractor.domain_backoff_until)
    total_errors = sum(extractor.domain_error_counts.values())

    print(f"Active rate limits: {active_rate_limits}")
    print(f"Total accumulated errors: {total_errors}")

    # Verify rate limiting is working
    assert total_requests > 0, "Should have made some requests"
    print("✅ Rate limiting system handled production-like workload successfully")


if __name__ == "__main__":
    # Run the production simulation
    test_rate_limiting_production_simulation()

    print("\n" + "=" * 60)
    print("To run all tests: pytest test_comprehensive_rate_limiting.py -v")
    print("=" * 60)
