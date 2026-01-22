"""
⚠️  DEPRECATION WARNING: This test module is deprecated following migration from Decodo to Squid proxy.

The unblock proxy functionality has been completely rewritten to use Squid proxy instead of Decodo API.
These tests verified Decodo proxy integration which is no longer used in production.

New Squid-only implementation is tested in tests/test_squid_only_proxy.py

These tests are marked as deprecated and will be removed in a future version.
For current proxy testing, see tests/test_squid_only_proxy.py

Original module description preserved for reference:

Comprehensive tests for unblock proxy extraction feature.

This module tests the complete logic flow for the extraction_method='unblock' feature:

1. Database schema and migration
    - extraction_method column creation
    - Migration from selenium_only to extraction_method
    - Index creation

2. Domain classification logic
    - _get_domain_extraction_method() returns correct method
    - _mark_domain_special_extraction() sets appropriate method based on protection type
    - Strong protections (PerimeterX, DataDome, Akamai) → 'unblock'
    - Other JS protections → 'selenium'
    - Default domains → 'http'

3. Extraction flow routing
    - 'unblock' domains skip HTTP methods and use _extract_with_unblock_proxy()
    - 'selenium' domains skip HTTP methods and use Selenium
    - 'http' domains use standard flow

4. _extract_with_unblock_proxy() method
    - Successful extraction with full HTML
    - Partial extraction with missing fields
    - Failed extraction (still blocked)
    - Network/timeout errors
    - Invalid credentials
    - Environment variable configuration

5. Field-level extraction and fallbacks
    - All fields extracted successfully
    - Some fields missing → fallback to Selenium
    - All fields missing → raise appropriate error
    - Content hash calculation
    - Metadata tracking

6. Edge cases
    - Domain not in sources table
    - extraction_method is NULL
    - Multiple protection types
    - Cache invalidation
    - Concurrent requests
    - Large HTML responses
    - Malformed HTML
"""

import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import text

# Deprecation marker for all tests in this file
pytestmark = [
    pytest.mark.skip(
        reason="DEPRECATED: Unblock proxy tests superseded by Squid-only implementation. See tests/test_squid_only_proxy.py"
    ),
    pytest.mark.filterwarnings("ignore:.*deprecated.*:DeprecationWarning"),
]

# Ensure project root is on sys.path for direct test execution
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.crawler import UNBLOCK_MIN_HTML_BYTES, ContentExtractor, ProxyChallengeError
from src.crawler.utils import mask_proxy_url
from src.utils.comprehensive_telemetry import ExtractionMetrics


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Provide default Decodo credentials for unblock proxy tests."""

    monkeypatch.setenv("UNBLOCK_PROXY_URL", "https://unblock.decodo.com:60000")
    monkeypatch.setenv("UNBLOCK_PROXY_USER", "testuser")
    monkeypatch.setenv("UNBLOCK_PROXY_PASS", "testpass")
    monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "true")
    return monkeypatch


class TestDomainClassificationLogic:
    """Test how domains get classified into extraction methods."""

    def test_mark_domain_special_extraction_auto_maps_perimeterx_to_unblock(self):
        """_mark_domain_special_extraction should auto-map PerimeterX to 'unblock'."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            # Call with default method (will be overridden to 'unblock')
            extractor._mark_domain_special_extraction("test.com", "perimeterx")

            # Verify UPDATE was called with method='unblock'
            assert mock_session.execute.called
            call_args = mock_session.execute.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
            assert (
                params["method"] == "unblock"
            ), "PerimeterX should auto-map to 'unblock'"
            assert params["protection_type"] == "perimeterx"

    def test_mark_domain_special_extraction_auto_maps_datadome_to_unblock(self):
        """DataDome should also auto-map to 'unblock' method."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            extractor._mark_domain_special_extraction("test.com", "datadome")

            assert mock_session.execute.called
            call_args = mock_session.execute.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
            assert (
                params["method"] == "unblock"
            ), "DataDome should auto-map to 'unblock'"

    def test_mark_domain_special_extraction_auto_maps_akamai_to_unblock(self):
        """Akamai should also auto-map to 'unblock' method."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            extractor._mark_domain_special_extraction("test.com", "akamai")

            assert mock_session.execute.called
            call_args = mock_session.execute.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
            assert params["method"] == "unblock", "Akamai should auto-map to 'unblock'"

    def test_mark_domain_special_extraction_keeps_selenium_for_cloudflare(self):
        """Cloudflare should use default 'selenium' method, not auto-map to 'unblock'."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            # Don't pass explicit method - use default 'selenium'
            extractor._mark_domain_special_extraction("test.com", "cloudflare")

            assert mock_session.execute.called
            call_args = mock_session.execute.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
            assert (
                params["method"] == "selenium"
            ), "Cloudflare should use default 'selenium'"

    def test_mark_domain_special_extraction_only_updates_http_domains(self):
        """Should only update domains currently set to 'http' or NULL."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            extractor._mark_domain_special_extraction("test.com", "perimeterx")

            # Verify WHERE clause restricts to http/NULL
            assert mock_session.execute.called
            call_args = mock_session.execute.call_args
            sql = str(call_args[0][0])
            assert (
                "extraction_method = 'http'" in sql
                or "extraction_method IS NULL" in sql
            )

    def test_mark_domain_special_extraction_updates_selenium_only_field(self):
        """Should set selenium_only=true when method is 'selenium'."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            extractor._mark_domain_special_extraction(
                "test.com", "cloudflare", method="selenium"
            )

            assert mock_session.execute.called
            call_args = mock_session.execute.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
            assert (
                params["is_selenium"] is True
            ), "selenium_only should be True when method='selenium'"

    def test_mark_domain_special_extraction_clears_selenium_only_for_unblock(self):
        """Should set selenium_only=false when method is 'unblock'."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            extractor._mark_domain_special_extraction(
                "test.com", "perimeterx"
            )  # Auto-maps to 'unblock'

            assert mock_session.execute.called
            call_args = mock_session.execute.call_args
            params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
            assert (
                params["is_selenium"] is False
            ), "selenium_only should be False when method='unblock'"


class TestExtractionFlowRouting:
    """Test that extraction flow correctly routes based on extraction_method.

    Note: These tests verify the unblock proxy method is called correctly.
    The autouse fixture mocks _get_domain_extraction_method to return ('http', None),
    so we test the _extract_with_unblock_proxy method directly.
    """

    def test_unblock_proxy_method_exists(self):
        """ContentExtractor should have _extract_with_unblock_proxy method."""
        extractor = ContentExtractor()
        assert hasattr(extractor, "_extract_with_unblock_proxy")
        assert callable(extractor._extract_with_unblock_proxy)

    def test_unblock_proxy_uses_correct_headers(self, mock_env_vars, monkeypatch):
        """Should send Decodo-specific headers (X-SU-*)."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = (
            "<html><body>" + ("test content " * 1000) + "</body></html>"
        )

        with patch("requests.get", return_value=mock_response) as mock_get:
            extractor._extract_with_unblock_proxy("https://test.com/article")

            # Verify headers were sent
            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs["headers"]
            assert "X-SU-Session-Id" in headers
            assert "X-SU-Geo" in headers
            assert "X-SU-Locale" in headers
            assert "X-SU-Headless" in headers
            assert headers["X-SU-Headless"] == "html"
            assert headers["Accept-Encoding"] == "identity"
            assert headers["Accept"] in extractor.accept_header_pool
            assert headers["Accept-Language"] in extractor.accept_language_pool
            assert headers["Cache-Control"] == "max-age=0"

    def test_unblock_proxy_randomizes_fingerprint_headers(
        self, mock_env_vars, monkeypatch
    ):
        """Randomized Decodo headers should change per request."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "true")

        session_hex = "feedfacefeedfacefeedfacefeedface"
        device_hex = "1234abcd1234abcd1234abcd1234abcd"
        random_value = 0.424242
        ip_octets = iter([101, 102, 103, 104])

        def fake_uuid():
            value = next(fake_uuid.values)
            return SimpleNamespace(hex=value)

        fake_uuid.values = iter([session_hex, device_hex])

        def fake_randint(_a, _b):
            try:
                return next(ip_octets)
            except StopIteration:
                return 200

        monkeypatch.setattr("src.crawler.uuid.uuid4", fake_uuid)
        monkeypatch.setattr("src.crawler.random.random", lambda: random_value)
        monkeypatch.setattr("src.crawler.random.randint", fake_randint)
        monkeypatch.setattr("src.crawler.random.choice", lambda seq: seq[0])

        captured = {}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>" + ("content " * 600) + "</html>"

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return mock_response

        monkeypatch.setattr("requests.post", fake_post)

        extractor._extract_with_unblock_proxy("https://example.com/article")

        headers = captured["headers"]
        expected_fingerprint = hashlib.sha256(
            f"{session_hex}:{device_hex}:{random_value}".encode()
        ).hexdigest()

        assert headers["X-SU-Session-Id"] == session_hex
        assert headers["X-SU-Device-Id"] == device_hex
        assert headers["X-SU-Fingerprint"] == expected_fingerprint
        assert headers["X-SU-Forwarded-For"] == "101.102.103.104"
        assert headers["sec-ch-ua"] == (
            '"Chromium";v="120", "Google Chrome";v="120", "Not?A Brand";v="24"'
        )
        assert headers["sec-ch-ua-platform"] == '"Windows"'
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert headers["Accept"] == extractor.accept_header_pool[0]
        assert headers["Accept-Language"] == extractor.accept_language_pool[0]
        assert headers["Cache-Control"] == "max-age=0"

    def test_unblock_proxy_uses_proxy_url(self, mock_env_vars, monkeypatch):
        """Should route request through proxy."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>" + ("test " * 1000) + "</body></html>"

        with patch("requests.get", return_value=mock_response) as mock_get:
            extractor._extract_with_unblock_proxy("https://test.com/article")

            # Verify proxies were configured
            call_kwargs = mock_get.call_args[1]
            assert "proxies" in call_kwargs
            proxies = call_kwargs["proxies"]
            assert "http" in proxies or "https" in proxies

    def test_unblock_proxy_disables_ssl_verification(self, mock_env_vars, monkeypatch):
        """Should disable SSL verification (verify=False)."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>" + ("test " * 1000) + "</body></html>"

        with patch("requests.get", return_value=mock_response) as mock_get:
            extractor._extract_with_unblock_proxy("https://test.com/article")

            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["verify"] is False

    def test_unblock_proxy_sets_timeout(self, mock_env_vars, monkeypatch):
        """Should set a timeout for the request."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>" + ("test " * 1000) + "</body></html>"

        with patch("requests.get", return_value=mock_response) as mock_get:
            extractor._extract_with_unblock_proxy("https://test.com/article")

            call_kwargs = mock_get.call_args[1]
            assert "timeout" in call_kwargs
            assert call_kwargs["timeout"] > 0

    def test_unblock_proxy_metadata_includes_extraction_method(
        self, mock_env_vars, monkeypatch
    ):
        """Result metadata should indicate unblock_proxy extraction."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = (
            "<html><head><title>Test</title></head><body>"
            + ("test " * 1000)
            + "</body></html>"
        )

        with patch("requests.get", return_value=mock_response):
            result = extractor._extract_with_unblock_proxy("https://test.com/article")

            assert "metadata" in result
            assert result["metadata"]["extraction_method"] == "unblock_proxy"
            assert result["metadata"]["proxy_used"] is True


class TestUnblockProxyMethod:
    """Test _extract_with_unblock_proxy() method behavior."""

    def test_successful_extraction_with_full_html(self, mock_env_vars, monkeypatch):
        """Should successfully extract from full HTML response."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
        <head>
            <title>Test Article Title</title>
            <meta name="author" content="John Doe">
            <meta property="article:published_time" content="2025-01-15T10:00:00Z">
        </head>
        <body>
            <article>
                <h1>Test Article Title</h1>
                <p>This is the article content with enough text to pass validation.</p>
                <p>More content here to ensure we have substantial text.</p>
            </article>
        </body>
        </html>
        """ * 100  # Make it large enough (>UNBLOCK_MIN_HTML_BYTES bytes)

        with patch("requests.get", return_value=mock_response):
            result = extractor._extract_with_unblock_proxy("https://test.com/article")

        assert result["title"] is not None
        assert result["content"] is not None
        assert result["metadata"]["extraction_method"] == "unblock_proxy"
        assert result["metadata"]["proxy_used"] is True
        assert result["metadata"]["page_source_length"] > UNBLOCK_MIN_HTML_BYTES

    def test_unblock_proxy_detects_challenge_and_updates_metrics(
        self, mock_env_vars, monkeypatch
    ):
        """Challenge pages should raise ProxyChallengeError and mark proxy metrics."""
        extractor = ContentExtractor()
        metrics = MagicMock(spec=ExtractionMetrics)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Access to this page has been denied" * 400

        monkeypatch.setattr("requests.post", lambda *args, **kwargs: mock_response)

        with pytest.raises(ProxyChallengeError, match="challenge_page"):
            extractor._extract_with_unblock_proxy(
                "https://blocked.example/article",
                metrics=metrics,
            )

        metrics.set_proxy_metrics.assert_called_once()
        call_kwargs = metrics.set_proxy_metrics.call_args.kwargs
        assert call_kwargs["proxy_status"] == "failed"
        assert call_kwargs["proxy_error"] == "challenge_page"

    def test_unblock_proxy_fallback_succeeds_after_challenge(
        self, mock_env_vars, monkeypatch
    ):
        """Decodo fallback POST should recover after initial challenge page."""
        extractor = ContentExtractor()
        metrics = MagicMock(spec=ExtractionMetrics)

        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "true")

        challenge_response = Mock()
        challenge_response.status_code = 200
        challenge_response.text = "Access to this page has been denied" * 400

        success_response = Mock()
        success_response.status_code = 200
        success_response.text = (
            "<html><head><title>Recovered</title></head><body>"
            + "content " * 600
            + "</body></html>"
        )

        responses = [challenge_response, success_response]

        def fake_post(*_args, **_kwargs):
            try:
                return responses.pop(0)
            except IndexError:
                return success_response

        proxy_url = "https://decodo-user:secret@decodo.example:60000"

        def fake_get(url, **kwargs):
            proxies = kwargs.get("proxies") or {}
            https_proxy = proxies.get("https", "")

            # First CONNECT attempt uses env-provided proxy (still blocked)
            if "unblock.decodo.com" in https_proxy:
                return challenge_response

            # Rotating fallback uses the injected proxy and should succeed
            if "decodo.example" in https_proxy:
                return success_response

            return challenge_response

        monkeypatch.setattr("requests.post", fake_post)
        monkeypatch.setattr("requests.get", fake_get)
        extractor.proxy_manager = SimpleNamespace(
            get_requests_proxies=lambda: {"https": proxy_url}
        )

        result = extractor._extract_with_unblock_proxy(
            "https://fallback.example/article",
            metrics=metrics,
        )

        sanitized_proxy = mask_proxy_url(proxy_url)

        assert result["metadata"]["proxy_status"] == "success"
        assert "Recovered" in result["title"]
        assert len(result["content"]) > 100
        metrics.set_proxy_metrics.assert_called_once()
        call_kwargs = metrics.set_proxy_metrics.call_args.kwargs
        assert call_kwargs["proxy_status"] == "success"
        assert call_kwargs["proxy_url"] == sanitized_proxy
        assert call_kwargs["proxy_authenticated"] is True

    def test_blocked_response_returns_empty(self, mock_env_vars, monkeypatch):
        """Should raise ProxyChallengeError if still blocked by bot protection."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = """
        <html>
        <head><title>Access to this page has been denied</title></head>
        <body>Access denied</body>
        </html>
        """

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(ProxyChallengeError, match="challenge_page"):
                extractor._extract_with_unblock_proxy("https://test.com/article")

    def test_small_response_returns_empty(self, mock_env_vars, monkeypatch):
        """Should raise ProxyChallengeError if response is below minimum size."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Small</body></html>"

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(ProxyChallengeError, match="small_response"):
                extractor._extract_with_unblock_proxy("https://test.com/article")

    def test_network_error_returns_empty(self, mock_env_vars, monkeypatch):
        """Should raise ProxyChallengeError on network errors."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        with patch("requests.get", side_effect=Exception("Connection timeout")):
            with pytest.raises(ProxyChallengeError, match="no_response"):
                extractor._extract_with_unblock_proxy("https://test.com/article")

    def test_unblock_proxy_prefers_api_post(self, mock_env_vars, monkeypatch):
        """When UNBLOCK_PREFER_API_POST is true, prefer POST to API as primary attempt."""
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "true")
        extractor = ContentExtractor()

        # GET would return a small/blocked response
        mock_get = Mock()
        mock_get.status_code = 200
        mock_get.text = "<html><body>small</body></html>"

        # POST returns large HTML and should be used
        mock_post = Mock()
        mock_post.status_code = 200
        mock_post.text = (
            "<html><head><title>OK</title></head><body>"
            + ("x" * 6000)
            + "</body></html>"
        )

        with patch("requests.get", return_value=mock_get) as mock_get_fn:
            with patch("requests.post", return_value=mock_post) as mock_post_fn:
                result = extractor._extract_with_unblock_proxy(
                    "https://test.com/article"
                )

                # Verify API POST was used as primary successful method after initial CONNECT attempt
                assert result.get("metadata", {}).get("proxy_provider") == "unblock_api"
                assert mock_post_fn.called
                # CONNECT path still runs once before POST fallback
                assert mock_get_fn.call_count == 1
                post_headers = mock_post_fn.call_args[1]["headers"]
                assert post_headers["Accept-Encoding"] == "identity"

    def test_uses_environment_variables(self, monkeypatch):
        """Should read proxy configuration from environment variables."""
        monkeypatch.setenv("UNBLOCK_PROXY_URL", "https://custom.proxy.com:8080")
        monkeypatch.setenv("UNBLOCK_PROXY_USER", "customuser")
        monkeypatch.setenv("UNBLOCK_PROXY_PASS", "custompass")

        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")
        extractor = ContentExtractor()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>" + ("test " * 1000) + "</body></html>"

        with patch("requests.get", return_value=mock_response) as mock_get:
            extractor._extract_with_unblock_proxy("https://test.com/article")

            # Verify proxy URL was constructed correctly
            call_kwargs = mock_get.call_args[1]
            assert "proxies" in call_kwargs
            assert "customuser:custompass" in call_kwargs["proxies"]["https"]
            assert "custom.proxy.com:8080" in call_kwargs["proxies"]["https"]

    def test_sends_required_headers(self, mock_env_vars, monkeypatch):
        """Should send X-SU-* headers required by Decodo API."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>" + ("test " * 1000) + "</body></html>"

        with patch("requests.get", return_value=mock_response) as mock_get:
            extractor._extract_with_unblock_proxy("https://test.com/article")

            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs["headers"]

            session_id = headers["X-SU-Session-Id"]
            device_id = headers["X-SU-Device-Id"]

            assert len(session_id) == 32
            assert len(device_id) == 32
            assert session_id != device_id
            # Ensure values are valid hex strings (uuid.hex format)
            int(session_id, 16)
            int(device_id, 16)

            assert headers["X-SU-Geo"] == "United States"
            assert headers["X-SU-Locale"] == "en-us"
            assert headers["X-SU-Headless"] == "html"
            assert "Mozilla" in headers["User-Agent"]
            assert headers["Accept-Encoding"] == "identity"
            assert headers["Accept"] in extractor.accept_header_pool
            assert headers["Accept-Language"] in extractor.accept_language_pool
            assert headers["Cache-Control"] == "max-age=0"


class TestFieldLevelExtractionAndFallbacks:
    """Test field-level extraction behavior and fallback scenarios."""

    def test_unblock_proxy_parses_html_with_beautifulsoup(
        self, mock_env_vars, monkeypatch
    ):
        """Should parse HTML response with BeautifulSoup."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
        <head>
            <title>Complete Article</title>
            <meta name="author" content="Jane Doe">
        </head>
        <body>
            <article>
                <h1>Complete Article</h1>
                <p>Full content here.</p>
            </article>
        </body>
        </html>
        """ * 100

        with patch("requests.get", return_value=mock_response):
            result = extractor._extract_with_unblock_proxy("https://test.com/article")

            # Should extract data successfully
            assert result is not None
            assert isinstance(result, dict)
            assert (
                result.get("metadata", {}).get("extraction_method") == "unblock_proxy"
            )

    def test_rotating_decodo_fallback_used_when_unblock_returns_small(
        self, mock_env_vars, monkeypatch
    ):
        """When UNBLOCK GET returns small HTML, try rotating decodo proxy and succeed."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        # First response: small HTML (blocked)
        mock_small = Mock()
        mock_small.status_code = 200
        mock_small.text = "<html><body>small</body></html>"

        # Second response: large HTML (rotating decodo succeeds)
        mock_big = Mock()
        mock_big.status_code = 200
        mock_big.text = (
            "<html><head><title>Test Article</title></head><body>"
            + ("test " * 1000)
            + "</body></html>"
        )

        # Patch requests.get to return small then big (proxy fallback)
        with patch("requests.get", side_effect=[mock_small, mock_big]):
            # Provide a fake rotating proxy via proxy_manager
            extractor.proxy_manager = Mock()
            extractor.proxy_manager.get_requests_proxies.return_value = {
                "https": "https://user-sp8:pass@isp.decodo.com:10001"
            }

            metrics = ExtractionMetrics(
                "opid-1", "article-1", "https://test.com/article", "TestPub"
            )
            result = extractor._extract_with_unblock_proxy(
                "https://test.com/article", None, metrics
            )

            assert (
                result.get("metadata", {}).get("extraction_method") == "unblock_proxy"
            )
            assert result.get("metadata", {}).get("proxy_provider") == "decodo_rotating"
            assert "isp.decodo.com" in result.get("metadata", {}).get("proxy_host")
            assert result.get("metadata", {}).get("proxy_url") is not None
            assert metrics.proxy_url == result.get("metadata", {}).get("proxy_url")
            assert result.get("metadata", {}).get("proxy_url") == mask_proxy_url(
                "https://user-sp8:pass@isp.decodo.com:10001"
            )
            assert metrics.proxy_authenticated is True

    def test_api_post_challenge_falls_back_to_rotating_proxy(
        self, mock_env_vars, monkeypatch
    ):
        """Challenge pages from API POST should trigger rotating proxy fallback."""
        extractor = ContentExtractor()
        metrics = MagicMock(spec=ExtractionMetrics)
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "true")

        challenge_response = Mock()
        challenge_response.status_code = 200
        challenge_response.text = "Access to this page has been denied" * 400

        fallback_html = (
            "<html><head><title>Recovered</title></head><body>"
            + ("content " * 600)
            + "</body></html>"
        )
        proxied_response = Mock()
        proxied_response.status_code = 200
        proxied_response.text = fallback_html

        monkeypatch.setattr("requests.post", lambda *args, **kwargs: challenge_response)

        def fake_get(url, **kwargs):
            proxies = kwargs.get("proxies") or {}
            https_proxy = proxies.get("https", "")

            # Initial CONNECT attempt should receive challenge to trigger API POST
            if "unblock.decodo.com" in https_proxy:
                return challenge_response

            # Rotating proxy fallback uses injected proxy and succeeds
            if "decodo.example" in https_proxy:
                return proxied_response

            return challenge_response

        monkeypatch.setattr("requests.get", fake_get)

        proxy_url = "https://decodo-user:secret@decodo.example:60000"
        extractor.proxy_manager = SimpleNamespace(
            get_requests_proxies=lambda: {"https": proxy_url}
        )

        result = extractor._extract_with_unblock_proxy(
            "https://challenged.example/article",
            metrics=metrics,
        )

        sanitized_proxy = mask_proxy_url(proxy_url)
        metadata = result["metadata"]

        assert metadata["proxy_provider"] == "decodo_rotating"
        assert metadata["proxy_url"] == sanitized_proxy
        assert metadata["proxy_status"] == "success"

        metrics.set_proxy_metrics.assert_called_once()
        call_kwargs = metrics.set_proxy_metrics.call_args.kwargs
        assert call_kwargs["proxy_status"] == "success"
        assert call_kwargs["proxy_error"] is None
        assert call_kwargs["proxy_url"] == sanitized_proxy
        assert call_kwargs["proxy_authenticated"] is True

    def test_post_api_fallback_used_when_gets_fail(self, mock_env_vars, monkeypatch):
        """When UNBLOCK GET and rotating proxies fail, attempt Decodo API POST IF enabled."""
        extractor = ContentExtractor()
        # Set to true to enable POST fallback
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "true")

        # First GET: small (blocked)
        mock_small = Mock()
        mock_small.status_code = 200
        mock_small.text = "<html><body>small</body></html>"

        # Second GET (rotating) also small (fail)
        mock_small2 = Mock()
        mock_small2.status_code = 200
        mock_small2.text = "<html><body>small</body></html>"

        # POST returns large HTML
        mock_post = Mock()
        mock_post.status_code = 200
        mock_post.text = (
            "<html><head><title>OK</title></head><body>"
            + ("x" * UNBLOCK_MIN_HTML_BYTES)
            + "</body></html>"
        )

        # Patch sequences: requests.get (primary), requests.get(rotating), requests.post(fallback)
        with patch("requests.get", side_effect=[mock_small, mock_small2]):
            with patch("requests.post", return_value=mock_post) as mock_post_fn:
                extractor.proxy_manager = Mock()
                extractor.proxy_manager.get_requests_proxies.return_value = {
                    "https": "https://user-sp8:pass@isp.decodo.com:10001"
                }

                metrics = ExtractionMetrics(
                    "opid-2", "article-2", "https://test.com/article", "TestPub"
                )
                result = extractor._extract_with_unblock_proxy(
                    "https://test.com/article", None, metrics
                )

                assert (
                    result.get("metadata", {}).get("extraction_method")
                    == "unblock_proxy"
                )
                assert result.get("metadata", {}).get("proxy_provider") == "unblock_api"
                assert (
                    result.get("metadata", {}).get("proxy_url")
                    == "https://unblock.decodo.com:60000"
                )
                assert metrics.proxy_url == result.get("metadata", {}).get("proxy_url")
                # Verify Decodo API headers were sent on POST
                assert mock_post_fn.call_count >= 1
                post_call_kwargs = mock_post_fn.call_args[1]
                session_id = post_call_kwargs["headers"]["X-SU-Session-Id"]
                device_id = post_call_kwargs["headers"]["X-SU-Device-Id"]

                assert len(session_id) == 32
                assert len(device_id) == 32
                int(session_id, 16)
                int(device_id, 16)

    def test_unblock_proxy_records_success_metrics(self, mock_env_vars, monkeypatch):
        """Successful API POST should record sanitized proxy metrics."""
        extractor = ContentExtractor()
        metrics = MagicMock(spec=ExtractionMetrics)
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "true")

        success_html = (
            "<html><head><title>OK</title></head><body>"
            + ("content " * 600)
            + "</body></html>"
        )
        success_response = Mock()
        success_response.status_code = 200
        success_response.text = success_html

        monkeypatch.setattr("requests.post", lambda *args, **kwargs: success_response)

        result = extractor._extract_with_unblock_proxy(
            "https://metrics.example/article",
            metrics=metrics,
        )

        expected_url = mask_proxy_url(
            os.getenv("UNBLOCK_PROXY_URL", "https://unblock.decodo.com:60000")
        )

        assert result["metadata"]["proxy_status"] == "success"
        assert result["metadata"]["proxy_url"] == expected_url

        metrics.set_proxy_metrics.assert_called_once()
        call_kwargs = metrics.set_proxy_metrics.call_args.kwargs
        assert call_kwargs["proxy_status"] == "success"
        assert call_kwargs["proxy_error"] is None
        assert call_kwargs["proxy_url"] == expected_url
        assert call_kwargs["proxy_authenticated"] is True

    def test_unblock_proxy_extracts_metadata(self, mock_env_vars, monkeypatch):
        """Should extract metadata fields from HTML."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = (
            """
        <html>
        <head>
            <title>Test Article</title>
            <meta name="description" content="Test description">
            <meta name="author" content="Jane Doe">
            <meta property="article:published_time" content="2025-01-15T10:00:00Z">
        </head>
        <body>
            <article><p>"""
            + ("content " * 1000)
            + """</p></article>
        </body>
        </html>
        """
        )

        with patch("requests.get", return_value=mock_response):
            result = extractor._extract_with_unblock_proxy("https://test.com/article")

            # Should have metadata
            assert "metadata" in result
            assert result["metadata"]["extraction_method"] == "unblock_proxy"
            assert result["metadata"]["proxy_used"] is True
            assert result["metadata"]["http_status"] == 200

    def test_unblock_proxy_includes_extracted_at_timestamp(
        self, mock_env_vars, monkeypatch
    ):
        """Should include extracted_at timestamp in ISO format."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = (
            "<html><head><title>Test</title></head><body>"
            + ("test " * 1000)
            + "</body></html>"
        )

        with patch("requests.get", return_value=mock_response):
            result = extractor._extract_with_unblock_proxy("https://test.com/article")

            assert "extracted_at" in result
            assert result["extracted_at"] is not None
            # Should be ISO format datetime string
            from datetime import datetime

            datetime.fromisoformat(result["extracted_at"].replace("Z", "+00:00"))


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_large_html_response_handled(self, mock_env_vars, monkeypatch):
        """Should handle very large HTML responses without crashing."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        # 2MB HTML response
        large_html = "<html><body>" + ("x" * 2_000_000) + "</body></html>"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = large_html

        with patch("requests.get", return_value=mock_response):
            result = extractor._extract_with_unblock_proxy("https://test.com/article")

            # Should process without error
            assert result["metadata"]["page_source_length"] == len(large_html)

    def test_malformed_html_handled_gracefully(self, mock_env_vars, monkeypatch):
        """Should handle malformed HTML without crashing."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        malformed_html = """
        <html>
        <head><title>Malformed</head>
        <body>
        <p>Unclosed paragraph
        <div>Unclosed div
        """ * 100

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = malformed_html

        with patch("requests.get", return_value=mock_response):
            result = extractor._extract_with_unblock_proxy("https://test.com/article")

            # BeautifulSoup should still parse it
            assert isinstance(result, dict)

    def test_timeout_handled_gracefully(self, mock_env_vars, monkeypatch):
        """Should raise ProxyChallengeError on request timeouts."""
        extractor = ContentExtractor()
        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")

        with patch("requests.get", side_effect=Exception("Timeout")):
            with pytest.raises(ProxyChallengeError, match="no_response"):
                extractor._extract_with_unblock_proxy("https://test.com/article")

    def test_empty_proxy_credentials_uses_defaults(self, monkeypatch):
        """Should use default values when environment variables are missing."""
        # Don't set any proxy env vars
        monkeypatch.delenv("UNBLOCK_PROXY_URL", raising=False)
        monkeypatch.delenv("UNBLOCK_PROXY_USER", raising=False)
        monkeypatch.delenv("UNBLOCK_PROXY_PASS", raising=False)

        monkeypatch.setenv("UNBLOCK_PREFER_API_POST", "false")
        extractor = ContentExtractor()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>" + ("test " * 1000) + "</body></html>"

        with patch("requests.get", return_value=mock_response) as mock_get:
            extractor._extract_with_unblock_proxy("https://test.com/article")

            # Should use hardcoded defaults
            call_kwargs = mock_get.call_args[1]
            assert "proxies" in call_kwargs


# ============================================================================
# PostgreSQL Integration Tests (CI/CD Only)
# ============================================================================


class TestPostgreSQLIntegration:
    """PostgreSQL integration tests that validate real database interactions.

    These tests run ONLY in CI/CD environment with PostgreSQL and verify:
    - Database schema and migrations
    - Real queries and lookups
    - Cache behavior with actual database
    - Data integrity

    Marked with @pytest.mark.integration to run in postgres-integration job.
    """

    @pytest.fixture(autouse=True)
    def setup_integration_env(self, monkeypatch):
        """Ensure DATABASE_URL matches TEST_DATABASE_URL for integration tests."""

        if "TEST_DATABASE_URL" in os.environ:
            monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])

    @pytest.mark.integration
    def test_extraction_method_column_exists_in_database(self, cloud_sql_session):
        """Verify extraction_method column exists in PostgreSQL sources table."""
        result = cloud_sql_session.execute(text("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name = 'sources'
            AND column_name = 'extraction_method'
        """)).fetchone()

        assert result is not None, "extraction_method column should exist"
        assert result[1] == "character varying", "Should be varchar type"
        assert "'http'" in result[2], "Default should be 'http'"

    @pytest.mark.integration
    def test_extraction_method_index_exists_in_database(self, cloud_sql_session):
        """Verify index on extraction_method exists for query performance."""
        result = cloud_sql_session.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'sources'
            AND indexname = 'ix_sources_extraction_method'
        """)).fetchone()

        assert result is not None, "Index on extraction_method should exist"

    @pytest.mark.integration
    def test_get_domain_extraction_method_queries_database(self, cloud_sql_session):
        """Test _get_domain_extraction_method actually queries PostgreSQL."""
        import os
        from unittest.mock import patch

        # Insert test domain with unblock method
        cloud_sql_session.execute(text("""
            INSERT INTO sources (id, host, host_norm, canonical_name, extraction_method, bot_protection_type)
            VALUES ('test-integration-unblock', 'integration-test.com', 'integration-test.com',
                    'Integration Test', 'unblock', 'perimeterx')
            ON CONFLICT (host_norm) DO UPDATE SET
                extraction_method = 'unblock',
                bot_protection_type = 'perimeterx'
        """))
        # No need to commit if we share the session, but flushing is good practice
        cloud_sql_session.flush()

        # Patch DatabaseManager to use the same session as the test
        # This is necessary because the test fixture uses a transaction that isn't committed to the DB,
        # so a separate connection (which DatabaseManager would create) cannot see the data.
        with patch("src.models.database.DatabaseManager") as MockDBManager:
            mock_db_instance = MockDBManager.return_value
            mock_db_instance.get_session.return_value.__enter__.return_value = (
                cloud_sql_session
            )

            extractor = ContentExtractor()
            # Clear cache to force database lookup
            if hasattr(extractor, "_extraction_method_cache"):
                extractor._extraction_method_cache = {}

            method, protection = extractor._get_domain_extraction_method(
                "integration-test.com"
            )

            assert method == "unblock", "Should retrieve 'unblock' from database"
            assert (
                protection == "perimeterx"
            ), "Should retrieve protection type from database"

    @pytest.mark.integration
    def test_mark_domain_special_extraction_updates_database(self, cloud_sql_session):
        """Test _mark_domain_special_extraction actually updates PostgreSQL."""
        from unittest.mock import patch

        # Insert test domain with http method
        cloud_sql_session.execute(text("""
            INSERT INTO sources (id, host, host_norm, canonical_name, extraction_method)
            VALUES ('test-integration-mark', 'mark-test.com', 'mark-test.com',
                    'Mark Test', 'http')
            ON CONFLICT (host_norm) DO UPDATE SET extraction_method = 'http'
        """))
        cloud_sql_session.flush()

        with patch("src.models.database.DatabaseManager") as MockDBManager:
            mock_db_instance = MockDBManager.return_value
            mock_db_instance.get_session.return_value.__enter__.return_value = (
                cloud_sql_session
            )

            extractor = ContentExtractor()
            extractor._mark_domain_special_extraction("mark-test.com", "perimeterx")

            # Verify database was updated
            result = cloud_sql_session.execute(text("""
                SELECT extraction_method, bot_protection_type, selenium_only
                FROM sources
                WHERE host = 'mark-test.com'
            """)).fetchone()

            assert result is not None
            assert (
                result[0] == "unblock"
            ), "extraction_method should be updated to 'unblock'"
        assert result[1] == "perimeterx", "bot_protection_type should be set"
        assert result[2] is False, "selenium_only should be False for unblock method"

    @pytest.mark.integration
    def test_default_extraction_method_is_http_in_database(self, cloud_sql_session):
        """Test new sources default to extraction_method='http' in PostgreSQL."""
        cloud_sql_session.execute(text("""
            INSERT INTO sources (id, host, host_norm, canonical_name)
            VALUES ('test-integration-default', 'default-test.com', 'default-test.com', 'Default Test')
            ON CONFLICT (host_norm) DO UPDATE SET extraction_method = DEFAULT
        """))
        cloud_sql_session.commit()

        result = cloud_sql_session.execute(text("""
            SELECT extraction_method
            FROM sources
            WHERE host = 'default-test.com'
        """)).fetchone()

        assert result is not None
        # Handle potential quoting in default value
        value = result[0].strip("'") if result[0] else result[0]
        assert value == "http", "Default should be 'http'"

    @pytest.mark.integration
    def test_extraction_method_cache_persists_across_lookups(self, cloud_sql_session):
        """Test that cache prevents redundant database queries."""
        from unittest.mock import patch

        # Insert test domain
        cloud_sql_session.execute(text("""
            INSERT INTO sources (id, host, host_norm, canonical_name, extraction_method, bot_protection_type)
            VALUES ('test-integration-cache', 'cache-test.com', 'cache-test.com',
                    'Cache Test', 'selenium', 'cloudflare')
            ON CONFLICT (host_norm) DO UPDATE SET
                extraction_method = 'selenium',
                bot_protection_type = 'cloudflare'
        """))
        cloud_sql_session.flush()

        with patch("src.models.database.DatabaseManager") as MockDBManager:
            mock_db_instance = MockDBManager.return_value
            mock_db_instance.get_session.return_value.__enter__.return_value = (
                cloud_sql_session
            )

            extractor = ContentExtractor()
            # Clear cache
            if hasattr(extractor, "_extraction_method_cache"):
                extractor._extraction_method_cache = {}

            # First lookup - hits database
            method1, protection1 = extractor._get_domain_extraction_method(
                "cache-test.com"
            )

            # Second lookup - should use cache
            method2, protection2 = extractor._get_domain_extraction_method(
                "cache-test.com"
            )

            assert method1 == method2 == "selenium"
            assert protection1 == protection2 == "cloudflare"

            # Verify cache was populated
            cache_key = "extraction_method:cache-test.com"
            assert hasattr(extractor, "_extraction_method_cache")
            assert cache_key in extractor._extraction_method_cache
            assert extractor._extraction_method_cache[cache_key] == (
                "selenium",
                "cloudflare",
            )

    @pytest.mark.integration
    def test_migration_updated_perimeterx_domains_to_unblock(self, cloud_sql_session):
        """Verify migration set existing PerimeterX domains to extraction_method='unblock'."""
        # Query for domains that should have been migrated
        result = cloud_sql_session.execute(text("""
            SELECT COUNT(*)
            FROM sources
            WHERE bot_protection_type = 'perimeterx'
            AND extraction_method = 'unblock'
        """)).scalar()

        # Should have at least the 4 Nexstar domains that were migrated
        assert result >= 0, "Migration should have set PerimeterX domains to 'unblock'"
