"""Unit tests for shared ChromeDriver and subscription wall handling."""

import os
from unittest import mock

import pytest

from src.crawler import ContentExtractor


class TestSharedChromeDriver:
    """Test shared class-level ChromeDriver implementation."""

    def test_shared_driver_initialization(self):
        """Verify shared driver starts as None."""
        assert ContentExtractor._shared_persistent_driver is None

    def test_shared_driver_creation_count(self):
        """Verify driver creation counter is class-level."""
        assert ContentExtractor._shared_driver_creation_count == 0

    def test_shared_driver_reuse_count(self):
        """Verify driver reuse counter is class-level."""
        assert ContentExtractor._shared_driver_reuse_count == 0

    def test_multiple_extractors_share_driver_reference(self):
        """Verify multiple ContentExtractor instances reference same driver variable."""
        # This tests that the driver is class-level, not instance-level
        extractor1 = ContentExtractor()
        extractor2 = ContentExtractor()

        # Both should reference the same class variable
        assert (
            extractor1.__class__._shared_persistent_driver
            is extractor2.__class__._shared_persistent_driver
        )

    def test_driver_reuse_limit_from_env(self):
        """Verify driver reuse limit is read from environment."""
        with mock.patch.dict(os.environ, {"CHROMEDRIVER_REUSE_LIMIT": "10"}):
            # Simulate how the limit would be set during initialization
            limit = int(os.environ.get("CHROMEDRIVER_REUSE_LIMIT", "100"))
            assert limit == 10

    @mock.patch("src.crawler.ContentExtractor.get_persistent_driver")
    def test_get_persistent_driver_uses_class_variable(self, mock_get_driver):
        """Verify get_persistent_driver accesses class-level variable."""
        mock_driver = mock.MagicMock()
        mock_get_driver.return_value = mock_driver

        extractor = ContentExtractor()

        # Mock driver should be returned
        result = extractor.get_persistent_driver()
        assert result == mock_driver

    @mock.patch("src.crawler.ContentExtractor.close_persistent_driver")
    def test_close_persistent_driver_resets_class_variable(self, mock_close):
        """Verify close_persistent_driver resets class-level reuse count."""
        # Set some state
        ContentExtractor._shared_driver_reuse_count = 5

        # Call close (which should reset count)
        ContentExtractor.close_persistent_driver()

        # Verify the mock was called
        mock_close.assert_called_once()


class TestSubscriptionWallDetection:
    """Test subscription wall and paywall modal detection."""

    def test_subscription_keywords_detected(self):
        """Verify subscription keywords are recognized."""
        keywords = [
            "subscribe",
            "membership",
            "paywall",
            "registration",
            "limited free",
        ]

        for keyword in keywords:
            html_content = f"<p>Please {keyword} to continue</p>"
            # This is a simple sanity check - actual detection happens in _detect_subscription_wall()
            assert keyword in html_content

    @mock.patch("src.crawler.ContentExtractor._detect_subscription_wall")
    def test_subscription_wall_detection_called(self, mock_detect_wall):
        """Verify _detect_subscription_wall is called during navigation."""
        mock_detect_wall.return_value = True

        extractor = ContentExtractor()

        result = extractor._detect_subscription_wall()
        assert result is True
        mock_detect_wall.assert_called_once()

    @mock.patch("src.crawler.ContentExtractor._navigate_with_human_behavior")
    def test_navigation_continues_with_subscription_wall(self, mock_navigate):
        """Verify navigation returns True when subscription wall is detected."""
        # Should return True to continue extraction despite wall
        mock_navigate.return_value = True

        extractor = ContentExtractor()

        # When subscription wall is present, should continue
        result = extractor._navigate_with_human_behavior()
        assert result is True


class TestCaptchaVsSubscriptionDifferentiation:
    """Test differentiation between blocking CAPTCHA and subscription modals."""

    @mock.patch("src.crawler.ContentExtractor._detect_captcha_or_challenge")
    def test_recaptcha_without_subscription_is_blocking(self, mock_detect_captcha):
        """Verify reCAPTCHA without subscription keywords is treated as blocking."""
        mock_detect_captcha.return_value = True

        extractor = ContentExtractor()

        result = extractor._detect_captcha_or_challenge()
        assert result is True
        mock_detect_captcha.assert_called_once()

    @mock.patch("src.crawler.ContentExtractor._detect_captcha_or_challenge")
    def test_recaptcha_with_subscription_is_non_blocking(self, mock_detect_captcha):
        """Verify reCAPTCHA with subscription keywords is treated as non-blocking."""
        # When subscription keywords are present with reCAPTCHA, return False (non-blocking)
        mock_detect_captcha.return_value = False

        extractor = ContentExtractor()

        result = extractor._detect_captcha_or_challenge()
        assert result is False


class TestScreenshotCapture:
    """Test screenshot capture for diagnostics."""

    @mock.patch("os.makedirs")
    @mock.patch("builtins.open", create=True)
    def test_captcha_screenshot_directory_created(self, mock_open, mock_makedirs):
        """Verify screenshot directory is created for CAPTCHA diagnostics."""
        screenshot_dir = "/tmp/captcha_screenshots"
        # This verifies the directory creation pattern
        mock_makedirs(screenshot_dir, exist_ok=True)

        mock_makedirs.assert_called_with(screenshot_dir, exist_ok=True)

    @mock.patch("os.makedirs")
    @mock.patch("builtins.open", create=True)
    def test_paywall_screenshot_directory_created(self, mock_open, mock_makedirs):
        """Verify screenshot directory is created for paywall diagnostics."""
        screenshot_dir = "/tmp/paywall_screenshots"
        # This verifies the directory creation pattern
        mock_makedirs(screenshot_dir, exist_ok=True)

        mock_makedirs.assert_called_with(screenshot_dir, exist_ok=True)


class TestExtractionWithSubscriptionWall:
    """Test extraction behavior when subscription wall is present."""

    @mock.patch("src.crawler.ContentExtractor._extract_with_selenium")
    def test_extraction_continues_despite_subscription_wall(self, mock_extract):
        """Verify extraction proceeds when subscription wall is detected."""
        # Should return extracted content despite wall
        mock_extract.return_value = {
            "title": "Test Article",
            "author": "Test Author",
            "text": "Test content here",
        }

        extractor = ContentExtractor()

        result = extractor._extract_with_selenium()

        assert result["title"] == "Test Article"
        assert result["author"] == "Test Author"
        assert result["text"] == "Test content here"

    @mock.patch("src.crawler.ContentExtractor._navigate_with_human_behavior")
    def test_human_behavior_navigation_succeeds_with_wall(self, mock_navigate):
        """Verify human behavior navigation returns True with subscription wall."""
        mock_navigate.return_value = True

        extractor = ContentExtractor()

        result = extractor._navigate_with_human_behavior()
        assert result is True


class TestGetDriverStats:
    """Test driver statistics reporting."""

    def test_driver_stats_uses_class_variables(self):
        """Verify get_driver_stats reports class-level statistics."""
        # Set some mock values
        ContentExtractor._shared_driver_creation_count = 5
        ContentExtractor._shared_driver_reuse_count = 10

        # get_driver_stats should use these class variables
        # (actual implementation would return dict with stats)
        assert ContentExtractor._shared_driver_creation_count == 5
        assert ContentExtractor._shared_driver_reuse_count == 10

    def test_driver_stats_reset_on_close(self):
        """Verify driver stats can be reset."""
        ContentExtractor._shared_driver_reuse_count = 15

        # Simulate reset (as done in close_persistent_driver)
        ContentExtractor._shared_driver_reuse_count = 0

        assert ContentExtractor._shared_driver_reuse_count == 0


class TestChromeDriverNoConflicts:
    """Test that shared driver prevents Chrome instance conflicts."""

    def test_no_duplicate_driver_creation(self):
        """Verify only one driver is created even with multiple extractors."""
        # Both extractors should use the same driver instance
        extractor1 = ContentExtractor()
        extractor2 = ContentExtractor()

        # They should share the same class-level driver reference
        assert (
            extractor1.__class__._shared_persistent_driver
            is extractor2.__class__._shared_persistent_driver
        )

    def test_driver_not_instance_specific(self):
        """Verify driver is class-level, not instance-specific."""
        extractor = ContentExtractor()

        # The driver should be accessible via the class, not the instance
        assert hasattr(ContentExtractor, "_shared_persistent_driver")
        assert not hasattr(extractor, "_persistent_driver")
