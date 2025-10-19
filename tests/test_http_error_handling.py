"""
Test HTTP error handling in content extraction.

Tests for commits:
- 615f8f9: Exception handling for 404/410 in extract_content()
- c59124a: Comprehensive HTTP error code coverage (all 4xx/5xx)

These tests ensure that HTTP error responses properly stop fallback
extraction attempts and raise appropriate exceptions.
"""

import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crawler import ContentExtractor, NotFoundError, RateLimitError  # noqa: E402


@pytest.fixture
def extractor():
    """Create a ContentExtractor instance for testing."""
    return ContentExtractor()


@pytest.fixture
def mock_response():
    """Create a mock HTTP response object."""

    def _create_response(status_code, text="", elapsed_seconds=1.0):
        response = Mock()
        response.status_code = status_code
        response.text = text
        response.elapsed = Mock()
        response.elapsed.total_seconds.return_value = elapsed_seconds
        # Add proxy metadata attributes
        response._proxy_used = False
        response._proxy_url = None
        response._proxy_authenticated = False
        response._proxy_status = None
        response._proxy_error = None
        return response

    return _create_response


class TestNotFoundErrorHandling:
    """Test 404/410 responses surface structured failures (commit 615f8f9)."""

    def test_404_returns_structured_not_found(self, extractor, mock_response):
        """404 response should return structured metadata instead of raising."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(404, "Not Found")
            mock_session.return_value = mock_sess

            result = extractor._extract_with_newspaper("https://example.com/missing")

        assert result["title"] is None
        assert result["content"] is None
        meta = result.get("metadata", {})
        assert meta.get("http_status") == 404
        assert meta.get("error") == "http_not_found"
        assert meta.get("extraction_method") == "newspaper4k"

    def test_410_returns_structured_not_found(self, extractor, mock_response):
        """410 Gone response should return structured metadata instead of raising."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(410, "Gone")
            mock_session.return_value = mock_sess

            result = extractor._extract_with_newspaper("https://example.com/gone")

        assert result["title"] is None
        assert result["content"] is None
        meta = result.get("metadata", {})
        assert meta.get("http_status") == 410
        assert meta.get("error") == "http_not_found"
        assert meta.get("extraction_method") == "newspaper4k"

    def test_404_not_found_stops_extract_content_fallback(self, extractor):
        """
        Test that NotFoundError in newspaper4k stops BS/Selenium fallback.
        """
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_np,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            # newspaper4k raises NotFoundError
            mock_np.side_effect = NotFoundError(
                "URL not found (404): https://example.com/test"
            )

            with pytest.raises(NotFoundError):
                extractor.extract_content("https://example.com/test")

            # Verify BeautifulSoup and Selenium were NEVER called
            mock_bs.assert_not_called()
            mock_sel.assert_not_called()

    def test_410_gone_stops_extract_content_fallback(self, extractor):
        """Test that 410 Gone stops all fallback methods."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_np,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            # newspaper4k raises NotFoundError for 410
            mock_np.side_effect = NotFoundError(
                "URL not found (410): https://example.com/gone"
            )

            with pytest.raises(NotFoundError):
                extractor.extract_content("https://example.com/gone")

            # Verify BeautifulSoup and Selenium were NEVER called
            mock_bs.assert_not_called()
            mock_sel.assert_not_called()


class TestRateLimitErrorHandling:
    """Test rate limiting responses stop fallback attempts (commit 615f8f9)."""

    def test_429_raises_rate_limit_error(self, extractor, mock_response):
        """Test that 429 response raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(429, "Too Many Requests")
            mock_session.return_value = mock_sess

            with pytest.raises(RateLimitError, match="Rate limited \\(429\\)"):
                extractor._extract_with_newspaper("https://example.com/article")

    def test_rate_limit_error_stops_extract_content_fallback(self, extractor):
        """Test that RateLimitError stops BS/Selenium fallback."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_np,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            # newspaper4k raises RateLimitError
            mock_np.side_effect = RateLimitError("Rate limited (429) by example.com")

            with pytest.raises(RateLimitError):
                extractor.extract_content("https://example.com/article")

            # Verify BeautifulSoup and Selenium were NEVER called
            mock_bs.assert_not_called()
            mock_sel.assert_not_called()


class Test4xxClientErrorHandling:
    """Test 4xx client error responses (commit c59124a)."""

    def test_400_bad_request_raises_not_found_error(self, extractor, mock_response):
        """Test that 400 Bad Request raises NotFoundError (permanent error)."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(400, "Bad Request")
            mock_session.return_value = mock_sess

            with pytest.raises(NotFoundError, match="Client error \\(400\\)"):
                extractor._extract_with_newspaper("https://example.com/bad-request")

    def test_405_method_not_allowed_raises_not_found_error(
        self, extractor, mock_response
    ):
        """Test that 405 Method Not Allowed raises NotFoundError."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(405, "Method Not Allowed")
            mock_session.return_value = mock_sess

            with pytest.raises(NotFoundError, match="Client error \\(405\\)"):
                extractor._extract_with_newspaper("https://example.com/no-get")

    def test_406_not_acceptable_raises_not_found_error(self, extractor, mock_response):
        """Test that 406 Not Acceptable raises NotFoundError."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(406, "Not Acceptable")
            mock_session.return_value = mock_sess

            with pytest.raises(NotFoundError, match="Client error \\(406\\)"):
                extractor._extract_with_newspaper("https://example.com/not-acceptable")

    def test_451_unavailable_for_legal_reasons_raises_not_found_error(
        self, extractor, mock_response
    ):
        """Test that 451 Unavailable For Legal Reasons raises NotFoundError."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(
                451, "Unavailable For Legal Reasons"
            )
            mock_session.return_value = mock_sess

            with pytest.raises(NotFoundError, match="Client error \\(451\\)"):
                extractor._extract_with_newspaper("https://example.com/blocked")

    def test_408_request_timeout_raises_rate_limit_error(
        self, extractor, mock_response
    ):
        """Test that 408 Request Timeout raises RateLimitError (temporary error)."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(408, "Request Timeout")
            mock_session.return_value = mock_sess

            with pytest.raises(RateLimitError, match="Client error \\(408\\)"):
                extractor._extract_with_newspaper("https://example.com/timeout")

    def test_4xx_errors_stop_extract_content_fallback(self, extractor):
        """Test that 4xx errors stop BeautifulSoup/Selenium fallback."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_newspaper,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            # newspaper4k raises NotFoundError for 400
            mock_newspaper.side_effect = NotFoundError(
                "Client error (400): https://example.com/bad"
            )

            with pytest.raises(NotFoundError):
                extractor.extract_content("https://example.com/bad")

            # Verify BeautifulSoup and Selenium were NEVER called
            mock_bs.assert_not_called()
            mock_sel.assert_not_called()


class Test5xxServerErrorHandling:
    """Test 5xx server error responses (commit c59124a)."""

    def test_500_internal_server_error_raises_rate_limit_error(
        self, extractor, mock_response
    ):
        """Test that 500 Internal Server Error raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(500, "Internal Server Error")
            mock_session.return_value = mock_sess

            with pytest.raises(RateLimitError, match="Server error \\(500\\)"):
                extractor._extract_with_newspaper("https://example.com/error")

    def test_501_not_implemented_raises_rate_limit_error(
        self, extractor, mock_response
    ):
        """Test that 501 Not Implemented raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(501, "Not Implemented")
            mock_session.return_value = mock_sess

            with pytest.raises(RateLimitError, match="Server error \\(501\\)"):
                extractor._extract_with_newspaper("https://example.com/not-impl")

    def test_505_http_version_not_supported_raises_rate_limit_error(
        self, extractor, mock_response
    ):
        """Test that 505 HTTP Version Not Supported raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(
                505, "HTTP Version Not Supported"
            )
            mock_session.return_value = mock_sess

            with pytest.raises(RateLimitError, match="Server error \\(505\\)"):
                extractor._extract_with_newspaper("https://example.com/version")

    def test_5xx_errors_stop_extract_content_fallback(self, extractor):
        """Test that 5xx errors stop BeautifulSoup/Selenium fallback."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_newspaper,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            # newspaper4k raises RateLimitError for 500
            mock_newspaper.side_effect = RateLimitError(
                "Server error (500) on example.com"
            )

            with pytest.raises(RateLimitError):
                extractor.extract_content("https://example.com/error")

            # Verify BeautifulSoup and Selenium were NEVER called
            mock_bs.assert_not_called()
            mock_sel.assert_not_called()


class TestExplicitlyHandledErrorCodes:
    """Test that explicitly handled error codes work correctly."""

    def test_403_forbidden_with_bot_protection_raises_rate_limit_error(
        self, extractor, mock_response
    ):
        """Test that 403 with bot protection raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(
                extractor, "_detect_bot_protection_in_response"
            ) as mock_detect,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):

            mock_sess = Mock()
            response = mock_response(403, "Access Denied - Cloudflare")
            mock_sess.get.return_value = response
            mock_session.return_value = mock_sess
            mock_detect.return_value = "cloudflare"

            with pytest.raises(RateLimitError, match="Bot protection"):
                extractor._extract_with_newspaper("https://example.com/protected")

    def test_502_bad_gateway_raises_rate_limit_error(self, extractor, mock_response):
        """Test that 502 Bad Gateway raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(
                extractor, "_detect_bot_protection_in_response"
            ) as mock_detect,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):

            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(502, "Bad Gateway")
            mock_session.return_value = mock_sess
            mock_detect.return_value = None  # No bot protection detected

            with pytest.raises(RateLimitError, match="Server error \\(502\\)"):
                extractor._extract_with_newspaper("https://example.com/gateway")

    def test_503_service_unavailable_raises_rate_limit_error(
        self, extractor, mock_response
    ):
        """Test that 503 Service Unavailable raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(
                extractor, "_detect_bot_protection_in_response"
            ) as mock_detect,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):

            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(503, "Service Unavailable")
            mock_session.return_value = mock_sess
            mock_detect.return_value = None

            with pytest.raises(RateLimitError, match="Server error \\(503\\)"):
                extractor._extract_with_newspaper("https://example.com/unavailable")

    def test_504_gateway_timeout_raises_rate_limit_error(
        self, extractor, mock_response
    ):
        """Test that 504 Gateway Timeout raises RateLimitError."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(
                extractor, "_detect_bot_protection_in_response"
            ) as mock_detect,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):

            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(504, "Gateway Timeout")
            mock_session.return_value = mock_sess
            mock_detect.return_value = None

            with pytest.raises(RateLimitError, match="Server error \\(504\\)"):
                extractor._extract_with_newspaper("https://example.com/timeout")


class TestUnexpectedStatusCodes:
    """Test handling of unexpected status codes."""

    def test_3xx_redirect_raises_rate_limit_error(self, extractor, mock_response):
        """Test that 3xx redirect (if not auto-handled) raises RateLimitError."""
        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            # Simulate a 3xx that wasn't auto-followed
            mock_sess.get.return_value = mock_response(301, "Moved Permanently")
            mock_session.return_value = mock_sess

            with pytest.raises(RateLimitError, match="Unexpected status \\(301\\)"):
                extractor._extract_with_newspaper("https://example.com/moved")


class TestSuccessfulExtraction:
    """Test that successful extractions still work correctly."""

    def test_200_ok_allows_extraction(self, extractor, mock_response):
        """Test that 200 OK allows normal extraction to proceed."""
        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(
                extractor, "_detect_bot_protection_in_response"
            ) as mock_detect,
            patch.object(extractor, "_reset_error_count"),
        ):

            mock_sess = Mock()
            response = mock_response(200, "<html><body>Article content</body></html>")
            mock_sess.get.return_value = response
            mock_session.return_value = mock_sess
            mock_detect.return_value = None  # No bot protection

            # Should not raise exception
            result = extractor._extract_with_newspaper("https://example.com/article")

            # Result should contain extracted data
            assert result is not None
            assert "url" in result
            assert result["url"] == "https://example.com/article"


class TestFallbackBehavior:
    """Test that fallback still works for non-HTTP errors."""

    def test_parsing_error_allows_beautifulsoup_fallback(self, extractor):
        """Test that parsing errors still allow BeautifulSoup fallback."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_newspaper,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_get_missing_fields") as mock_missing,
        ):

            # newspaper4k fails with generic parsing error (not HTTP error)
            mock_newspaper.side_effect = Exception("Failed to parse HTML")

            # Multiple calls track missing fields before/after BS fallback
            mock_missing.side_effect = [
                ["title", "content"],  # After newspaper fails
                ["title", "content"],  # Before BS fallback
                [],  # After BS fallback
                [],  # Final check
            ]

            # BeautifulSoup succeeds
            mock_bs.return_value = {
                "title": "Test Article",
                "content": "Test content",
                "author": None,
                "publish_date": None,
                "metadata": {},
            }

            result = extractor.extract_content("https://example.com/article")

            # Verify BeautifulSoup WAS called (fallback allowed)
            mock_bs.assert_called_once()
            assert result is not None

    def test_connection_error_allows_beautifulsoup_fallback(self, extractor):
        """Test that connection errors still allow BeautifulSoup fallback."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_newspaper,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_get_missing_fields") as mock_missing,
        ):

            # newspaper4k fails with connection error
            mock_newspaper.side_effect = ConnectionError("Connection refused")

            mock_missing.side_effect = [
                ["title", "content"],  # After newspaper
                ["title", "content"],  # Before BS
                [],  # After BS
                [],  # Final
            ]

            mock_bs.return_value = {
                "title": "Test Article",
                "content": "Test content",
                "author": None,
                "publish_date": None,
                "metadata": {},
            }

            result = extractor.extract_content("https://example.com/article")

            # Verify BeautifulSoup WAS called (fallback allowed)
            mock_bs.assert_called_once()
            assert result is not None


class TestDeadURLCaching:
    """Test that permanent errors are cached as dead URLs."""

    def test_404_caches_url_as_dead(self, extractor, mock_response):
        """Test that 404 caches URL in dead_urls dict."""
        extractor.dead_url_ttl = 3600  # Enable caching
        extractor.dead_urls = {}

        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(404, "Not Found")
            mock_session.return_value = mock_sess

            url = "https://example.com/missing"

            result = extractor._extract_with_newspaper(url)

        # Verify URL was cached as dead
        assert url in extractor.dead_urls
        assert extractor.dead_urls[url] > time.time()

        metadata = result.get("metadata", {})
        assert metadata.get("http_status") == 404
        assert metadata.get("error") == "http_not_found"
        assert "cache_ttl_expires_at" in metadata

    def test_400_caches_url_as_dead(self, extractor, mock_response):
        """Test that 400 Bad Request caches URL as dead."""
        extractor.dead_url_ttl = 3600
        extractor.dead_urls = {}

        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(400, "Bad Request")
            mock_session.return_value = mock_sess

            url = "https://example.com/bad"

            with pytest.raises(NotFoundError):
                extractor._extract_with_newspaper(url)

            # Verify URL was cached as dead
            assert url in extractor.dead_urls

    def test_500_does_not_cache_url(self, extractor, mock_response):
        """Test that 500 server errors do NOT cache URL (temporary error)."""
        extractor.dead_url_ttl = 3600
        extractor.dead_urls = {}

        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(extractor, "_handle_rate_limit_error"),
        ):
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(500, "Internal Server Error")
            mock_session.return_value = mock_sess

            url = "https://example.com/error"

            with pytest.raises(RateLimitError):
                extractor._extract_with_newspaper(url)

            # Verify URL was NOT cached (temporary error)
            assert url not in extractor.dead_urls


class TestMetricsTracking:
    """Test that extraction metrics are properly tracked."""

    def test_404_tracks_metrics(self, extractor, mock_response):
        """Test that 404 error is tracked in metrics."""
        mock_metrics = Mock()

        with patch.object(extractor, "_get_domain_session") as mock_session:
            mock_sess = Mock()
            mock_sess.get.return_value = mock_response(404, "Not Found")
            mock_session.return_value = mock_sess

            result = extractor.extract_content(
                "https://example.com/missing", metrics=mock_metrics
            )

        assert result is not None

        # Verify metrics were recorded
        assert mock_metrics.start_method.called
        assert mock_metrics.end_method.called

        # Ensure newspaper4k was recorded with structured failure metadata
        matching_calls = [
            entry
            for entry in mock_metrics.end_method.call_args_list
            if entry[0][0] == "newspaper4k"
        ]
        assert matching_calls, "Expected newspaper4k metrics to be recorded"
        meta_arg = matching_calls[-1][0][3]
        assert meta_arg.get("metadata", {}).get("error") == "http_not_found"

    def test_successful_extraction_tracks_metrics(self, extractor, mock_response):
        """Test that successful extraction tracks metrics."""
        mock_metrics = Mock()

        with (
            patch.object(extractor, "_get_domain_session") as mock_session,
            patch.object(
                extractor, "_detect_bot_protection_in_response"
            ) as mock_detect,
            patch.object(extractor, "_reset_error_count"),
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            mock_sess = Mock()
            response = mock_response(200, "<html><body>Content</body></html>")
            mock_sess.get.return_value = response
            mock_session.return_value = mock_sess
            mock_detect.return_value = None

            # Prevent selenium fallback for missing fields
            mock_sel.return_value = None

            extractor.extract_content(
                "https://example.com/article", metrics=mock_metrics
            )

            # Verify metrics were recorded for newspaper4k
            # It may be called multiple times (newspaper + selenium attempt)
            assert mock_metrics.start_method.call_count >= 1
            # Verify newspaper4k was one of the methods called
            calls = [call[0][0] for call in mock_metrics.start_method.call_args_list]
            assert "newspaper4k" in calls


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
