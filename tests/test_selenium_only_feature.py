"""Tests for selenium_only feature - forces Selenium-only extraction for JS-based bot protection.

This module tests:
1. Detection of specific bot protection types (PerimeterX, Cloudflare, etc.)
2. _is_domain_selenium_only() method
3. _mark_domain_selenium_only() method
4. Extraction flow skipping HTTP methods for selenium_only domains
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.crawler as crawler_module  # noqa: E402
from src.crawler import ContentExtractor  # noqa: E402

# NOT on the module.
#
# `enable_selenium` switches off two guards for everything it marks:
# `disable_real_selenium`, which keeps SELENIUM_AVAILABLE false, and
# `block_external_network`, which fails a unit test that reaches a
# non-loopback host. Marking the whole file removed both from 35 tests,
# and the ones whose fetch is not mocked went to the real network and
# fell back to real Chrome. Two of them cost 220 of the 358 seconds this
# file takes in the headful job, and the worse offender asserts nothing
# at all.
#
# The mark now sits on the class that is actually about headful Selenium,
# which is what `scripts/ci/test-selenium.sh` selects. Everything else
# runs in the ordinary suite with both guards on, which is also what
# makes it test anything: a mocked path that silently falls through to
# the network is not exercising the branch it names.


class TestBotProtectionTypeDetection:
    """Test detection of specific bot protection types."""

    def test_perimeterx_detection_by_px_app_id(self):
        """Should detect PerimeterX by _pxAppId in response."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <head>
        <script>window._pxAppId = 'PX12345';</script>
        </head>
        <body>Access denied</body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "perimeterx"

    def test_perimeterx_detection_by_px_cloud(self):
        """Should detect PerimeterX by px-cloud.net domain."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <body>
        <iframe src="https://captcha.px-cloud.net/challenge"></iframe>
        </body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "perimeterx"

    def test_perimeterx_detection_by_human_security(self):
        """Should detect PerimeterX by Human Security reference."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <body>
        <p>Contact challengehelp@humansecurity.com for assistance</p>
        </body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "perimeterx"

    def test_cloudflare_detection(self):
        """Should detect Cloudflare challenges."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <head><title>Just a moment...</title></head>
        <body>
        <h1>Checking your browser before accessing example.com</h1>
        <p>Cloudflare Ray ID: 8d3f2a1b0c9e8f7d</p>
        </body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "cloudflare"

    def test_cloudflare_detection_by_challenge_platform(self):
        """Should detect Cloudflare by challenge-platform reference."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <head><title>Just a moment...</title></head>
        <body>
        <div id="challenge-platform">
        <p>Please wait while we verify your browser</p>
        </div>
        <script src="/cdn-cgi/challenge-platform/scripts/jsd.js"></script>
        </body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "cloudflare"

    def test_datadome_detection(self):
        """Should detect DataDome bot protection."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <head>
        <script src="https://ct.datadome.co/tags.js"></script>
        </head>
        <body>Blocked</body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "datadome"

    def test_akamai_detection(self):
        """Should detect Akamai bot protection."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <head>
        <script src="https://example.com/akam/123/abc"></script>
        </head>
        <body>Access Denied - Akamai Reference#1234</body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "akamai"

    def test_kasada_detection(self):
        """Should detect Kasada bot protection."""
        extractor = ContentExtractor()

        response = Mock()
        # Kasada uses specific script patterns with UUIDs
        response.text = """
        <html>
        <head>
        <script src="https://example.com/149e9513-01fa-4fb0-aad4-566afd725d1b/2d206a39-8ed7-437e-a3be-862e0f06eea3/ips.js"></script>
        </head>
        <body>
        <p>Please wait while we verify your browser...</p>
        <p>This page uses Kasada security.</p>
        </body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        # Kasada may be detected as generic bot_protection if pattern doesn't match
        assert protection in ("kasada", "bot_protection")

    def test_incapsula_detection(self):
        """Should detect Incapsula/Imperva bot protection."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <body>
        <p>Incident ID: 12345-incap_ses_67890</p>
        </body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "incapsula"


# Store original method for tests that need to test the real implementation
_original_get_domain_extraction_method = ContentExtractor._get_domain_extraction_method


class TestSeleniumOnlyDatabaseMethods:
    """Test _get_domain_extraction_method and _mark_domain_special_extraction methods."""

    @pytest.fixture(autouse=True)
    def restore_real_method(self, monkeypatch):
        """Restore the real _get_domain_extraction_method method for these tests.

        The global autouse fixture mocks this method, but we need the real
        implementation to test it.
        """
        monkeypatch.setattr(
            ContentExtractor,
            "_get_domain_extraction_method",
            _original_get_domain_extraction_method,
        )

    def test_get_domain_extraction_method_returns_http_by_default(self):
        """New domains should return 'http' method by default."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db_cls:
            mock_session = MagicMock()
            mock_db_cls.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )
            # Simulate no row found
            mock_session.execute.return_value.fetchone.return_value = None

            # Clear any cache
            extractor._extraction_method_cache = {}

            result = extractor._get_domain_extraction_method("example.com")
            assert result == ("http", None)

    def test_get_domain_extraction_method_returns_unblock_for_perimeterx(self):
        """Should return 'unblock' for domains with PerimeterX."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db_cls:
            mock_session = MagicMock()
            mock_db_cls.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )
            # Simulate database returning extraction_method='unblock', protection_type='perimeterx'
            mock_session.execute.return_value.fetchone.return_value = (
                "unblock",
                "perimeterx",
            )

            # Clear any cache
            extractor._extraction_method_cache = {}

            result = extractor._get_domain_extraction_method("fox4kc.com")
            assert result == ("unblock", "perimeterx")

    def test_mark_domain_special_extraction_updates_database(self):
        """Should update database when marking domain with special extraction."""
        extractor = ContentExtractor()

        with patch("src.models.database.DatabaseManager") as mock_db_cls:
            mock_session = MagicMock()
            mock_db_cls.return_value.get_session.return_value.__enter__.return_value = (
                mock_session
            )

            extractor._mark_domain_special_extraction("fox4kc.com", "perimeterx")

            # Verify execute was called (for the UPDATE statement)
            assert mock_session.execute.called
            # Verify commit was called
            assert mock_session.commit.called


class TestExtractionFlowWithSeleniumOnly:
    """Test that extraction flow properly skips HTTP methods for selenium/unblock domains."""

    def test_extract_content_checks_extraction_method(self):
        """extract_content should check extraction_method at start."""
        extractor = ContentExtractor()

        from src.crawler import ProxyChallengeError

        with patch.object(
            extractor,
            "_get_domain_extraction_method",
            return_value=("unblock", "perimeterx"),
        ) as mock_check:
            with patch.object(extractor, "_extract_with_unblock_proxy") as mock_unblock:
                # Unblock proxy returns challenge error (no mock response configured)
                mock_unblock.side_effect = ProxyChallengeError(
                    "Proxy challenge detected"
                )

                # Call extract_content - should raise ProxyChallengeError (no fallback)
                with pytest.raises(ProxyChallengeError):
                    extractor.extract_content("https://fox4kc.com/news/story")

                # Verify selenium_only check was made
                mock_check.assert_called_once_with("fox4kc.com")

    def test_extract_content_skips_mcmetadata_for_selenium_only(self):
        """Should not call mcmetadata for selenium_only domains."""
        extractor = ContentExtractor()

        with patch.object(
            extractor,
            "_get_domain_extraction_method",
            return_value=("selenium", "perimeterx"),
        ):
            with patch.object(extractor, "_extract_with_selenium") as mock_selenium:
                with patch.object(
                    extractor, "_parse_with_mcmetadata"
                ) as mock_mcmetadata:
                    mock_selenium.return_value = {
                        "title": "Test",
                        "text": "Content " * 50,
                    }

                    extractor.extract_content("https://fox4kc.com/news/story")

                    # mcmetadata should NOT be called
                    mock_mcmetadata.assert_not_called()

    def test_extract_content_skips_newspaper_for_selenium_only(self):
        """Should not call newspaper4k for selenium_only domains."""
        extractor = ContentExtractor()

        with patch.object(
            extractor,
            "_get_domain_extraction_method",
            return_value=("selenium", "perimeterx"),
        ):
            with patch.object(extractor, "_extract_with_selenium") as mock_selenium:
                with patch.object(extractor, "_parse_with_newspaper") as mock_newspaper:
                    mock_selenium.return_value = {
                        "title": "Test",
                        "text": "Content " * 50,
                    }

                    extractor.extract_content("https://fox4kc.com/news/story")

                    # newspaper4k should NOT be called
                    mock_newspaper.assert_not_called()

    def test_extract_content_uses_selenium_for_selenium_only(self, monkeypatch):
        """Should use Selenium for selenium_only domains.

        `SELENIUM_AVAILABLE` is set here rather than by marking the test
        `enable_selenium`, which would also switch off the network guard.
        The flag is what this test needs; unrestricted egress is not.
        """
        extractor = ContentExtractor()
        monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)

        with patch.object(
            extractor,
            "_get_domain_extraction_method",
            return_value=("selenium", "perimeterx"),
        ):
            with patch.object(extractor, "_extract_with_selenium") as mock_selenium:
                mock_selenium.return_value = {
                    "title": "Test Article",
                    "text": "This is the article content with sufficient length.",
                }

                extractor.extract_content("https://fox4kc.com/news/story")

                # Selenium SHOULD be called
                mock_selenium.assert_called()

    def test_extract_content_normal_flow_for_non_selenium_only(self, monkeypatch):
        """A normal domain takes the HTTP path, and not Selenium.

        This asserted nothing -- it called `extract_content` and ended on
        a comment saying mcmetadata "may or may not" have been called. It
        also left its fetch unmocked, so with the file-wide
        `enable_selenium` mark removing the network guard it went out to
        normalnews.com and fell back to real headful Chrome: 177 seconds
        of the headful job, for a test that could not fail.
        """
        extractor = ContentExtractor()
        monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)
        monkeypatch.setattr(crawler_module, "MCMETADATA_AVAILABLE", True)

        with (
            patch.object(
                extractor, "_get_domain_extraction_method", return_value=("http", None)
            ),
            patch.object(
                extractor, "_fetch_page_html", return_value="<html>capture</html>"
            ),
            patch.object(
                extractor, "_parse_with_mcmetadata", return_value=True
            ) as mock_mcmetadata,
            patch.object(extractor, "_get_missing_fields", return_value=[]),
            patch.object(extractor, "_run_selenium_extraction") as mock_selenium,
        ):
            extractor.extract_content(
                "https://normalnews.com/article",
                html="<html><body>Test</body></html>",
            )

        mock_mcmetadata.assert_called_once()
        mock_selenium.assert_not_called()


class TestHeadfulPrimarySelenium:
    """Verify headful mode behavior with HTTP and unblock domains.

    Headful mode affects HOW Selenium runs (visible browser), not WHEN.
    - HTTP domains: HTTP methods first, Selenium as fallback
    - Unblock domains: Selenium first (PerimeterX/Akamai require it)
    """

    # What the headful job runs (scripts/ci/test-selenium.sh).
    pytestmark = pytest.mark.enable_selenium

    def test_headful_mode_uses_http_first_for_http_domains(self, monkeypatch):
        """Headful mode should NOT force Selenium-first for HTTP domains."""
        extractor = ContentExtractor(selenium_mode="headful")

        monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)
        monkeypatch.setattr(crawler_module, "MCMETADATA_AVAILABLE", True)

        with (
            patch.object(
                extractor,
                "_get_domain_extraction_method",
                return_value=("http", None),
            ),
            patch.object(
                extractor,
                "_fetch_page_html",
                return_value="<html>capture</html>",
            ),
            patch.object(
                extractor,
                "_run_selenium_extraction",
            ) as mock_selenium,
            patch.object(
                extractor,
                "_parse_with_mcmetadata",
                return_value=True,
            ) as mock_mcmetadata,
            patch.object(
                extractor,
                "_get_missing_fields",
                return_value=[],  # HTTP methods succeeded
            ),
        ):
            extractor.extract_content("https://example.com/http-domain")

        # HTTP methods should be tried first
        mock_mcmetadata.assert_called_once()
        # Selenium should NOT be called when HTTP methods succeed
        mock_selenium.assert_not_called()

    def test_headful_mode_skips_http_when_selenium_succeeds(self, monkeypatch):
        """Headful mode should still try HTTP methods first for HTTP domains.

        This test verifies that HTTP domains use HTTP extraction methods first,
        even when in headful mode. Selenium should only be used as a fallback
        when HTTP methods fail to extract required fields.
        """
        extractor = ContentExtractor(selenium_mode="headful")

        monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)
        monkeypatch.setattr(crawler_module, "MCMETADATA_AVAILABLE", True)
        monkeypatch.setattr(crawler_module, "NEWSPAPER_AVAILABLE", True)

        with (
            patch.object(
                extractor,
                "_get_domain_extraction_method",
                return_value=("http", None),
            ),
            patch.object(
                extractor,
                "_fetch_page_html",
                return_value="<html>capture</html>",
            ),
            patch.object(
                extractor,
                "_run_selenium_extraction",
            ) as mock_selenium,
            patch.object(
                extractor,
                "_parse_with_mcmetadata",
                return_value=True,  # mcmetadata succeeds
            ) as mock_mcmetadata,
            patch.object(
                extractor,
                "_parse_with_newspaper",
                return_value=True,  # newspaper succeeds
            ),
            patch.object(
                extractor,
                "_parse_with_beautifulsoup",
                return_value=True,  # beautifulsoup succeeds
            ),
            patch.object(
                extractor,
                "_get_missing_fields",
                return_value=[],  # No missing fields, HTTP extraction was successful
            ),
        ):
            extractor.extract_content("https://example.com/http-domain")

        # HTTP domain should use HTTP methods first
        # Selenium should NOT be called since HTTP extraction succeeded
        mock_mcmetadata.assert_called_once()
        mock_selenium.assert_not_called()


class TestBotProtectionAutoMarking:
    """Test that JS-based bot protection automatically marks domains as selenium_only."""

    def test_perimeterx_detection_triggers_selenium_only_marking(self):
        """When PerimeterX is detected, domain should be marked selenium_only."""
        extractor = ContentExtractor()

        # Test that the detection returns the correct type
        response = Mock()
        response.text = "window._pxAppId = 'test'"
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)

        # The detection itself returns the type
        assert protection == "perimeterx"

        # Verify this is a JS-required protection type
        js_required_protections = {
            "perimeterx",
            "cloudflare",
            "datadome",
            "akamai",
            "kasada",
            "incapsula",
        }
        assert protection in js_required_protections


class TestJSRequiredBotProtectionTypes:
    """Test that certain bot protection types are recognized as requiring JavaScript."""

    @pytest.mark.parametrize(
        "protection_type,requires_js",
        [
            ("perimeterx", True),
            ("cloudflare", True),
            ("datadome", True),
            ("akamai", True),
            ("kasada", True),
            ("incapsula", True),
            ("bot_protection", False),  # Generic - might not require JS
            ("suspicious_short_response", False),
            (None, False),
        ],
    )
    def test_js_required_protections(self, protection_type, requires_js):
        """Verify which protection types are known to require JavaScript."""
        js_required_protections = {
            "perimeterx",
            "cloudflare",
            "datadome",
            "akamai",
            "kasada",
            "incapsula",
        }

        if protection_type:
            result = protection_type in js_required_protections
            assert result == requires_js


class TestChallengeBypass:
    """Test the _try_bypass_challenge method for handling JS bot challenges."""

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        """No-op the bypass waits: these tests use Mock drivers whose state
        never changes with time, so the real 5-10s challenge waits per test
        (~50s across the class) verify nothing. Scoped to this class — the
        real-browser (enable_selenium) classes in this file need real waits.
        """
        monkeypatch.setattr("src.crawler.time.sleep", lambda *_a, **_k: None)

    def test_bypass_auto_resolve_cloudflare(self):
        """Test that Cloudflare-style challenges that auto-resolve are detected."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        # First call: challenge still there (after wait). Second call: challenge gone (auto-resolved)
        with patch.object(
            extractor, "_detect_captcha_or_challenge", side_effect=[False]
        ):
            result = extractor._try_bypass_challenge(mock_driver, "https://example.com")

        assert result is True

    def test_bypass_click_verification_button(self):
        """Test clicking a verification button to bypass challenge."""
        extractor = ContentExtractor()
        mock_driver = Mock()
        mock_element = Mock()
        mock_element.is_displayed.return_value = True
        mock_element.is_enabled.return_value = True

        # Challenge present after wait, gone after click
        with patch.object(
            extractor, "_detect_captcha_or_challenge", side_effect=[True, False]
        ):
            mock_driver.find_elements.return_value = [mock_element]

            result = extractor._try_bypass_challenge(mock_driver, "https://example.com")

        assert result is True

    def test_bypass_tries_multiple_selectors(self):
        """Test that bypass tries multiple CSS selectors for verification buttons."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        # No elements found for any selector, challenge persists
        mock_driver.find_elements.return_value = []
        mock_driver.find_element.side_effect = Exception("No element")

        with patch.object(extractor, "_detect_captcha_or_challenge", return_value=True):
            result = extractor._try_bypass_challenge(mock_driver, "https://example.com")

        assert result is False
        # Should have tried multiple selectors
        assert mock_driver.find_elements.call_count > 5

    def test_bypass_returns_false_when_challenge_persists(self):
        """Test that bypass returns False when challenge cannot be bypassed."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        mock_driver.find_elements.return_value = []
        mock_driver.find_element.side_effect = Exception("No element")

        with patch.object(extractor, "_detect_captcha_or_challenge", return_value=True):
            result = extractor._try_bypass_challenge(mock_driver, "https://example.com")

        assert result is False

    def test_bypass_handles_click_exception(self):
        """Test that exceptions during clicking are handled gracefully."""
        extractor = ContentExtractor()
        mock_driver = Mock()
        mock_element = Mock()
        mock_element.is_displayed.return_value = True
        mock_element.is_enabled.return_value = True
        mock_element.click.side_effect = Exception("Click failed")

        mock_driver.find_elements.return_value = [mock_element]
        mock_driver.find_element.side_effect = Exception("No element")

        with patch.object(extractor, "_detect_captcha_or_challenge", return_value=True):
            # Should not raise, just return False
            result = extractor._try_bypass_challenge(mock_driver, "https://example.com")

        assert result is False

    def test_bypass_final_wait_success(self):
        """Test that final wait can succeed if challenge resolves slowly."""
        extractor = ContentExtractor()
        mock_driver = Mock()

        mock_driver.find_elements.return_value = []
        mock_driver.find_element.side_effect = Exception("No element")

        # The bypass method checks _detect_captcha_or_challenge at these points:
        # 1. After initial 5s wait (Phase 1) - return True (challenge still there)
        # 2. After final 5s wait (Phase 4) - return False (challenge resolved)
        # Note: Phase 2 only calls detection if elements are found AND clicked,
        #       and Phase 3 only calls if px_button.is_displayed() succeeds

        with patch.object(
            extractor, "_detect_captcha_or_challenge", side_effect=[True, False]
        ):
            result = extractor._try_bypass_challenge(mock_driver, "https://example.com")

        # The bypass should succeed because challenge resolved in final wait
        assert result is True
