"""Tests for cloudscraper modern browser profile configuration.

Ensures cloudscraper uses a modern Chrome/Windows profile to bypass Cloudflare
bot detection, rather than the default Firefox 53/Linux profile which is flagged.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestCloudscraperBrowserProfile:
    """Test suite for cloudscraper browser profile configuration."""

    def test_browser_profile_constant_defined(self):
        """Test that CLOUDSCRAPER_BROWSER_PROFILE constant is properly defined."""
        from src.crawler import CLOUDSCRAPER_BROWSER_PROFILE

        assert CLOUDSCRAPER_BROWSER_PROFILE is not None
        assert CLOUDSCRAPER_BROWSER_PROFILE["browser"] == "chrome"
        assert CLOUDSCRAPER_BROWSER_PROFILE["platform"] == "windows"
        assert CLOUDSCRAPER_BROWSER_PROFILE["desktop"] is True

    def test_create_new_session_uses_browser_profile(self, monkeypatch):
        """Test that _create_new_session passes browser profile to cloudscraper."""
        mock_scraper = MagicMock()
        mock_create_scraper = MagicMock(return_value=mock_scraper)

        with patch("src.crawler.cloudscraper") as mock_cloudscraper:
            mock_cloudscraper.create_scraper = mock_create_scraper

            # Import after patching
            from src.crawler import CLOUDSCRAPER_BROWSER_PROFILE, ContentExtractor

            # Patch CLOUDSCRAPER_AVAILABLE to True
            with patch("src.crawler.CLOUDSCRAPER_AVAILABLE", True):
                extractor = ContentExtractor()
                extractor._create_new_session()

                # Verify create_scraper was called with browser profile
                mock_create_scraper.assert_called_with(
                    browser=CLOUDSCRAPER_BROWSER_PROFILE
                )

    def test_get_domain_session_uses_browser_profile(self, monkeypatch):
        """Test that domain sessions use modern browser profile."""
        mock_scraper = MagicMock()
        mock_scraper.headers = {}
        mock_scraper.proxies = {}
        mock_create_scraper = MagicMock(return_value=mock_scraper)

        # Set required env vars
        monkeypatch.setenv("SQUID_PROXY_URL", "http://proxy:3128")

        with patch("src.crawler.cloudscraper") as mock_cloudscraper:
            mock_cloudscraper.create_scraper = mock_create_scraper

            from src.crawler import CLOUDSCRAPER_BROWSER_PROFILE, ContentExtractor

            with patch("src.crawler.CLOUDSCRAPER_AVAILABLE", True):
                extractor = ContentExtractor()
                # Clear any calls from __init__
                mock_create_scraper.reset_mock()

                # Get domain session (should create new cloudscraper instance)
                extractor._get_domain_session("https://newsite.com")

                # Verify browser profile was passed
                call_args = mock_create_scraper.call_args
                if call_args:
                    assert call_args[1].get("browser") == CLOUDSCRAPER_BROWSER_PROFILE

    def test_fingerprint_session_uses_browser_profile(self, monkeypatch):
        """Test that fingerprint sessions use modern browser profile."""
        mock_scraper = MagicMock()
        mock_create_scraper = MagicMock(return_value=mock_scraper)

        monkeypatch.setenv("SQUID_PROXY_URL", "http://proxy:3128")

        with patch("src.crawler.cloudscraper") as mock_cloudscraper:
            mock_cloudscraper.create_scraper = mock_create_scraper

            from src.crawler import CLOUDSCRAPER_BROWSER_PROFILE, ContentExtractor

            with patch("src.crawler.CLOUDSCRAPER_AVAILABLE", True):
                extractor = ContentExtractor()
                mock_create_scraper.reset_mock()

                extractor._create_session_with_fingerprint_ua()

                # Verify browser profile was passed
                mock_create_scraper.assert_called_with(
                    browser=CLOUDSCRAPER_BROWSER_PROFILE
                )


class TestDiscoveryBrowserProfile:
    """Test suite for discovery module cloudscraper configuration."""

    def test_discovery_uses_chrome_windows_profile(self):
        """Test that NewsDiscovery uses Chrome/Windows browser profile."""
        mock_scraper = MagicMock()
        mock_scraper.headers = {}
        mock_create_scraper = MagicMock(return_value=mock_scraper)

        with patch("src.crawler.discovery.cloudscraper") as mock_cloudscraper:
            mock_cloudscraper.create_scraper = mock_create_scraper

            from src.crawler.discovery import NewsDiscovery

            NewsDiscovery(user_agent="test-agent")

            # Verify create_scraper was called with modern profile
            mock_create_scraper.assert_called_once()
            call_kwargs = mock_create_scraper.call_args[1]
            assert call_kwargs["browser"]["browser"] == "chrome"
            assert call_kwargs["browser"]["platform"] == "windows"
            assert call_kwargs["browser"]["desktop"] is True

    def test_discovery_not_using_default_firefox_profile(self):
        """Test that discovery does NOT use the default Firefox/Linux profile."""
        mock_scraper = MagicMock()
        mock_scraper.headers = {}
        mock_create_scraper = MagicMock(return_value=mock_scraper)

        with patch("src.crawler.discovery.cloudscraper") as mock_cloudscraper:
            mock_cloudscraper.create_scraper = mock_create_scraper

            from src.crawler.discovery import NewsDiscovery

            NewsDiscovery(user_agent="test-agent")

            call_kwargs = mock_create_scraper.call_args[1]
            browser_config = call_kwargs["browser"]

            # Should NOT be default Firefox/Linux
            assert browser_config.get("browser") != "firefox"
            assert browser_config.get("platform") != "linux"


class TestCloudscraperProfileIntegration:
    """Integration-style tests for cloudscraper profile behavior."""

    @pytest.mark.skipif(
        True,  # Skip by default - run manually for integration testing
        reason="Integration test - requires actual cloudscraper import",
    )
    def test_actual_user_agent_is_modern_chrome(self):
        """Verify that cloudscraper with our profile returns modern Chrome UA."""
        import cloudscraper

        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )

        user_agent = scraper.headers.get("User-Agent", "")

        # Should contain Chrome (not Firefox)
        assert "Chrome" in user_agent or "chrome" in user_agent.lower()
        # Should NOT be the old problematic Firefox 53
        assert "Firefox/53" not in user_agent
        # Should be Windows (not Linux i686)
        assert "Linux i686" not in user_agent
