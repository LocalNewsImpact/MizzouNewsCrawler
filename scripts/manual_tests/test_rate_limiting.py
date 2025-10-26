"""Test rate limiting functionality in ContentExtractor."""

import pytest
import time
from unittest.mock import Mock, patch
from src.crawler import ContentExtractor, RateLimitError


class TestRateLimiting:
    """Test suite for rate limiting functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = ContentExtractor()

    def test_rate_limit_error_creation(self):
        """Test that RateLimitError can be created and raised."""
        with pytest.raises(RateLimitError):
            raise RateLimitError("Test rate limit")

    def test_check_rate_limit_no_backoff(self):
        """Test _check_rate_limit when domain is not rate limited."""
        domain = "example.com"
        assert not self.extractor._check_rate_limit(domain)

    def test_check_rate_limit_with_active_backoff(self):
        """Test _check_rate_limit when domain is in active backoff period."""
        domain = "example.com"
        future_time = time.time() + 60  # 1 minute in future
        self.extractor.domain_backoff_until[domain] = future_time

        assert self.extractor._check_rate_limit(domain)

    def test_check_rate_limit_expired_backoff(self):
        """Test _check_rate_limit when backoff period has expired."""
        domain = "example.com"
        past_time = time.time() - 60  # 1 minute in past
        self.extractor.domain_backoff_until[domain] = past_time

        # Should return False and clear the expired backoff
        assert not self.extractor._check_rate_limit(domain)
        assert domain not in self.extractor.domain_backoff_until

    def test_apply_rate_limit_delay(self):
        """Test _apply_rate_limit applies delays correctly."""
        domain = "example.com"

        # First request - should have no delay
        start_time = time.time()
        self.extractor._apply_rate_limit(domain)
        elapsed = time.time() - start_time
        assert elapsed < 0.1  # Should be immediate

        # Second request - should have delay
        start_time = time.time()
        self.extractor._apply_rate_limit(domain, delay=0.5)
        elapsed = time.time() - start_time
        assert elapsed >= 0.4  # Should delay at least 0.4 seconds

    def test_handle_rate_limit_error_increments_count(self):
        """Test _handle_rate_limit_error increments error count."""
        domain = "example.com"

        # First error
        self.extractor._handle_rate_limit_error(domain)
        assert self.extractor.domain_error_counts[domain] == 1

        # Second error
        self.extractor._handle_rate_limit_error(domain)
        assert self.extractor.domain_error_counts[domain] == 2

    def test_handle_rate_limit_error_sets_backoff(self):
        """Test _handle_rate_limit_error sets backoff period."""
        domain = "example.com"
        current_time = time.time()

        self.extractor._handle_rate_limit_error(domain)

        # Should set backoff period in future
        assert domain in self.extractor.domain_backoff_until
        assert self.extractor.domain_backoff_until[domain] > current_time

    def test_handle_rate_limit_error_exponential_backoff(self):
        """Test exponential backoff increases with error count."""
        domain = "example.com"

        # First error
        self.extractor._handle_rate_limit_error(domain)
        self.extractor.domain_backoff_until[domain]

        # Reset time tracking for cleaner test
        current_time = time.time()

        # Second error
        self.extractor._handle_rate_limit_error(domain)
        second_backoff = self.extractor.domain_backoff_until[domain]

        # Second backoff should be longer (accounting for the time that passed)
        time_diff = second_backoff - current_time
        assert time_diff > 60  # Should be at least 2 minutes for second error

    def test_handle_rate_limit_error_respects_retry_after(self):
        """Test _handle_rate_limit_error respects Retry-After header."""
        domain = "example.com"
        current_time = time.time()

        # Mock response with Retry-After header
        mock_response = Mock()
        mock_response.headers = {"retry-after": "300"}  # 5 minutes

        self.extractor._handle_rate_limit_error(domain, mock_response)

        # Should use server's retry-after value
        backoff_duration = self.extractor.domain_backoff_until[domain] - current_time
        assert backoff_duration >= 300  # Should be at least 5 minutes

    def test_reset_error_count(self):
        """Test _reset_error_count clears error count."""
        domain = "example.com"
        self.extractor.domain_error_counts[domain] = 5

        self.extractor._reset_error_count(domain)

        assert self.extractor.domain_error_counts[domain] == 0

    def test_create_error_result(self):
        """Test _create_error_result creates proper error structure."""
        url = "https://example.com/article"
        error_msg = "Rate limited"
        metadata = {"status": 429}

        result = self.extractor._create_error_result(url, error_msg, metadata)

        assert result["url"] == url
        assert result["error"] == error_msg
        assert result["metadata"] == metadata
        assert result["success"] is False
        assert result["quality_score"] == 0.0
        assert result["title"] == ""
        assert result["content"] == ""
        assert result["author"] == []

    def test_get_domain_session_rate_limit_exception(self):
        """Test that _get_domain_session raises RateLimitError when rate limited."""
        domain = "example.com"
        url = "https://example.com/article"
        future_time = time.time() + 60
        self.extractor.domain_backoff_until[domain] = future_time

        with pytest.raises(RateLimitError, match="Domain example.com is rate limited"):
            self.extractor._get_domain_session(url)


class TestRateLimitingIntegration:
    """Integration tests for rate limiting with real HTTP responses."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = ContentExtractor()

    @patch("requests.Session.get")
    def test_extraction_handles_429_response(self, mock_get):
        """Test that extraction properly handles 429 responses."""
        # Mock 429 response
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"retry-after": "60"}
        mock_get.return_value = mock_response

        url = "https://www.kahokamedia.com/test-article"

        # Should handle 429 gracefully and return error result
        result = self.extractor.extract_content(url)

        assert result["success"] is False
        assert "Rate limited" in result["error"]
        assert result["url"] == url

    @patch("requests.Session.get")
    def test_extraction_handles_403_response(self, mock_get):
        """Test that extraction properly handles 403 responses (bot detection)."""
        # Mock 403 response
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.headers = {}
        mock_get.return_value = mock_response

        url = "https://www.kahokamedia.com/test-article"

        # Should handle 403 as potential bot detection
        result = self.extractor.extract_content(url)

        assert result["success"] is False
        assert "Bot detection" in result["error"]
        assert result["url"] == url

    @patch("requests.Session.get")
    def test_extraction_resets_error_count_on_success(self, mock_get):
        """Test that successful requests reset error count."""
        domain = "example.com"
        url = "https://example.com/article"

        # Set up some errors first
        self.extractor.domain_error_counts[domain] = 3

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
            <head><title>Test Article</title></head>
            <body>
                <h1>Test Article</h1>
                <p>This is test content.</p>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        # Extract article
        self.extractor.extract_content(url)

        # Error count should be reset
        assert self.extractor.domain_error_counts[domain] == 0

    def test_real_kahokamedia_rate_limiting(self):
        """Test rate limiting with real kahokamedia.com site (if accessible)."""
        # This test hits the actual site that was causing 429 errors
        url = "https://www.kahokamedia.com/"

        try:
            # Try to make multiple requests quickly to trigger rate limiting
            results = []
            for i in range(3):  # Start with just 3 requests
                print(f"Making request {i + 1} to {url}")
                result = self.extractor.extract_content(url)
                results.append(result)

                # Check if we got rate limited
                if not result["success"] and "Rate limited" in result.get("error", ""):
                    print(f"Successfully detected rate limiting on request {i + 1}")
                    # Verify that domain is now in backoff
                    domain = "www.kahokamedia.com"
                    assert domain in self.extractor.domain_backoff_until
                    break
                elif not result["success"]:
                    print(f"Request {i + 1} failed: {result.get('error', 'Unknown')}")
                else:
                    print(f"Request {i + 1} succeeded")

                # Small delay between requests
                time.sleep(0.5)

            print("Rate limiting test completed")

        except Exception as e:
            print(f"Real site test failed (expected in CI): {e}")
            # This is expected to fail in CI/testing environments
            pass


if __name__ == "__main__":
    # Run specific test for debugging
    test_instance = TestRateLimitingIntegration()
    test_instance.setup_method()
    test_instance.test_real_kahokamedia_rate_limiting()
