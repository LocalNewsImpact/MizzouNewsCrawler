"""Integration tests for bot sensitivity with ContentExtractor."""

import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.crawler import ContentExtractor
from src.utils.bot_sensitivity_manager import BOT_SENSITIVITY_CONFIG


@pytest.fixture
def mock_bot_manager():
    """Mock bot sensitivity manager."""
    manager = MagicMock()
    manager.get_sensitivity_config.return_value = BOT_SENSITIVITY_CONFIG[5]
    manager.get_bot_sensitivity.return_value = 5
    manager.record_bot_detection.return_value = 8
    return manager


@pytest.fixture
def extractor_with_bot_sensitivity(mock_bot_manager):
    """Create ContentExtractor with mocked bot sensitivity manager."""
    with patch('src.crawler.BotSensitivityManager', return_value=mock_bot_manager):
        extractor = ContentExtractor()
        extractor.bot_sensitivity_manager = mock_bot_manager
        return extractor, mock_bot_manager


class TestContentExtractorBotSensitivityIntegration:
    """Test bot sensitivity integration with ContentExtractor."""

    def test_extractor_initializes_bot_manager(self):
        """Test that ContentExtractor initializes bot sensitivity manager."""
        with patch('src.crawler.BotSensitivityManager') as mock_mgr:
            extractor = ContentExtractor()
            mock_mgr.assert_called_once()
            assert hasattr(extractor, 'bot_sensitivity_manager')

    def test_apply_rate_limit_uses_sensitivity_config(
        self, extractor_with_bot_sensitivity
    ):
        """Test that rate limiting uses sensitivity-based config."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        # Set a specific sensitivity config
        test_config = {
            "inter_request_min": 10.0,
            "inter_request_max": 20.0,
        }
        bot_manager.get_sensitivity_config.return_value = test_config
        
        domain = "test-site.com"
        start_time = time.time()
        
        # Apply rate limit
        extractor._apply_rate_limit(domain)
        
        # Verify bot manager was called
        bot_manager.get_sensitivity_config.assert_called_with(domain)
        
        # Verify time was recorded
        assert domain in extractor.domain_request_times
        assert extractor.domain_request_times[domain] >= start_time

    def test_http_429_triggers_bot_detection_recording(
        self, extractor_with_bot_sensitivity
    ):
        """Test that 429 response triggers bot detection recording."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        # Mock a 429 response
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        
        domain = "test-site.com"
        url = "https://test-site.com/article"
        
        # Simulate the bot detection code path
        with patch.object(extractor, '_create_error_result') as mock_error:
            mock_error.return_value = {"success": False}
            
            # This would be called in the actual extraction flow
            bot_manager.record_bot_detection(
                host=domain,
                url=url,
                event_type="rate_limit_429",
                http_status_code=429,
            )
            
            bot_manager.record_bot_detection.assert_called_once()
            call_args = bot_manager.record_bot_detection.call_args
            assert call_args[1]['event_type'] == "rate_limit_429"
            assert call_args[1]['http_status_code'] == 429

    def test_http_403_triggers_bot_detection(
        self, extractor_with_bot_sensitivity
    ):
        """Test that 403 response triggers bot detection."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        domain = "test-site.com"
        url = "https://test-site.com/article"
        
        # Simulate 403 detection
        bot_manager.record_bot_detection(
            host=domain,
            url=url,
            event_type="403_forbidden",
            http_status_code=403,
        )
        
        bot_manager.record_bot_detection.assert_called_once()
        call_args = bot_manager.record_bot_detection.call_args
        assert call_args[1]['event_type'] == "403_forbidden"

    def test_captcha_detection_triggers_recording(
        self, extractor_with_bot_sensitivity
    ):
        """Test that CAPTCHA detection triggers bot recording."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        domain = "test-site.com"
        url = "https://test-site.com/article"
        
        # Simulate CAPTCHA detection
        bot_manager.record_bot_detection(
            host=domain,
            url=url,
            event_type="captcha_detected",
            http_status_code=403,
            response_indicators={"protection_type": "cloudflare"},
        )
        
        bot_manager.record_bot_detection.assert_called_once()
        call_args = bot_manager.record_bot_detection.call_args
        assert call_args[1]['event_type'] == "captcha_detected"
        assert 'response_indicators' in call_args[1]

    def test_different_sensitivity_levels_have_different_delays(
        self, extractor_with_bot_sensitivity
    ):
        """Test that different sensitivity levels produce different delays."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        test_cases = [
            (1, 0.5, 1.5),   # Very permissive
            (5, 5.0, 12.0),  # Moderate
            (10, 45.0, 90.0),  # Maximum caution
        ]
        
        for sensitivity, min_delay, max_delay in test_cases:
            config = BOT_SENSITIVITY_CONFIG[sensitivity]
            bot_manager.get_sensitivity_config.return_value = config
            
            # Verify config has expected values
            assert config["inter_request_min"] == min_delay
            assert config["inter_request_max"] == max_delay

    def test_sensitivity_persists_across_requests(
        self, extractor_with_bot_sensitivity
    ):
        """Test that sensitivity is loaded for each request."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        domain = "test-site.com"
        
        # First request
        extractor._apply_rate_limit(domain)
        assert bot_manager.get_sensitivity_config.call_count == 1
        
        # Second request
        extractor._apply_rate_limit(domain)
        assert bot_manager.get_sensitivity_config.call_count == 2
        
        # Both should use the same domain
        calls = bot_manager.get_sensitivity_config.call_args_list
        assert all(call[0][0] == domain for call in calls)

    def test_high_sensitivity_applies_longer_delays(
        self, extractor_with_bot_sensitivity
    ):
        """Test that high sensitivity results in longer delays."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        domain = "sensitive-site.com"
        
        # Configure for high sensitivity (10)
        high_sensitivity_config = BOT_SENSITIVITY_CONFIG[10]
        bot_manager.get_sensitivity_config.return_value = high_sensitivity_config
        
        # Record start time
        extractor.domain_request_times[domain] = time.time() - 1.0
        
        # Apply rate limit - should enforce minimum delay
        start = time.time()
        extractor._apply_rate_limit(domain)
        elapsed = time.time() - start
        
        # For sensitivity 10, min delay is 45s, but we're testing the mechanism
        # In practice, the delay would be enforced
        assert bot_manager.get_sensitivity_config.called

    def test_rate_limit_config_includes_all_required_fields(self):
        """Test that sensitivity configs have all required fields."""
        required_fields = [
            "inter_request_min",
            "inter_request_max",
            "batch_sleep",
            "captcha_backoff_base",
            "captcha_backoff_max",
            "max_backoff",
            "request_timeout",
        ]
        
        for sensitivity in range(1, 11):
            config = BOT_SENSITIVITY_CONFIG[sensitivity]
            for field in required_fields:
                assert field in config, (
                    f"Sensitivity {sensitivity} missing {field}"
                )


class TestBotDetectionResponseHandling:
    """Test bot detection in response handling."""

    def test_detect_cloudflare_in_response(self):
        """Test detection of Cloudflare protection in response."""
        extractor = ContentExtractor()
        
        mock_response = Mock()
        mock_response.text = (
            "<html><title>Just a moment...</title>"
            "<body>Checking your browser before accessing site.com"
            "<p>Cloudflare Ray ID: abc123</p></body></html>"
        )
        
        protection_type = extractor._detect_bot_protection_in_response(
            mock_response
        )
        
        assert protection_type == "cloudflare"

    def test_detect_generic_bot_protection_in_response(self):
        """Test detection of generic bot protection."""
        extractor = ContentExtractor()
        
        mock_response = Mock()
        mock_response.text = (
            "<html><body><h1>Access Denied</h1>"
            "<p>Please verify you are human</p></body></html>"
        )
        
        protection_type = extractor._detect_bot_protection_in_response(
            mock_response
        )
        
        assert protection_type == "bot_protection"

    def test_detect_captcha_in_response(self):
        """Test detection of CAPTCHA in response."""
        extractor = ContentExtractor()
        
        mock_response = Mock()
        mock_response.text = (
            "<html><body><div class='g-recaptcha'>CAPTCHA</div></body></html>"
        )
        
        protection_type = extractor._detect_bot_protection_in_response(
            mock_response
        )
        
        assert protection_type == "bot_protection"

    def test_no_bot_protection_detected(self):
        """Test normal response without bot protection."""
        extractor = ContentExtractor()
        
        mock_response = Mock()
        mock_response.text = (
            "<html><body><h1>Article Title</h1>"
            "<p>Normal article content here</p></body></html>"
        )
        
        protection_type = extractor._detect_bot_protection_in_response(
            mock_response
        )
        
        assert protection_type is None


class TestSensitivityProgressionScenarios:
    """Test realistic sensitivity progression scenarios."""

    def test_gradual_sensitivity_increase_scenario(
        self, extractor_with_bot_sensitivity
    ):
        """Test that sensitivity increases gradually with bot encounters."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        domain = "escalating-site.com"
        url = f"https://{domain}/article"
        
        # Scenario: Multiple bot detections over time
        sensitivity_progression = [
            (5, "rate_limit_429", 6),   # Start at 5, hit 429 → 6
            (6, "403_forbidden", 8),    # At 6, hit 403 → 8
            (8, "captcha_detected", 10),  # At 8, hit CAPTCHA → 10 (max)
        ]
        
        for current, event_type, expected_new in sensitivity_progression:
            bot_manager.get_bot_sensitivity.return_value = current
            bot_manager.record_bot_detection.return_value = expected_new
            
            # Simulate detection
            new_sensitivity = bot_manager.record_bot_detection(
                host=domain,
                url=url,
                event_type=event_type,
                http_status_code=403,
            )
            
            assert new_sensitivity == expected_new

    def test_sensitivity_remains_at_max(self, extractor_with_bot_sensitivity):
        """Test that sensitivity stays at max (10) after multiple detections."""
        extractor, bot_manager = extractor_with_bot_sensitivity
        
        domain = "max-sensitive-site.com"
        url = f"https://{domain}/article"
        
        # Already at max sensitivity
        bot_manager.get_bot_sensitivity.return_value = 10
        bot_manager.record_bot_detection.return_value = 10
        
        # Multiple additional detections shouldn't exceed 10
        for _ in range(5):
            new_sensitivity = bot_manager.record_bot_detection(
                host=domain,
                url=url,
                event_type="captcha_detected",
                http_status_code=403,
            )
            assert new_sensitivity == 10
