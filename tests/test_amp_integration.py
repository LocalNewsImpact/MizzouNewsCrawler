"""
Integration tests for AMP bypass functionality.

Tests the actual behavior with mocked HTTP responses that simulate
real PerimeterX scenarios.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import sys
from pathlib import Path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from src.crawler import ContentExtractor


# Sample HTML responses
PERIMETERX_403_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Access Denied</title>
    <script src="https://client.perimeterx.net/px.js"></script>
</head>
<body>
    <div id="px-captcha">Access to this page has been denied.</div>
</body>
</html>
"""

VALID_AMP_HTML = """
<!DOCTYPE html>
<html amp>
<head>
    <meta charset="utf-8">
    <title>Sample Article Title - Fox 4 Kansas City</title>
    <link rel="canonical" href="https://fox4kc.com/news/article/">
    <meta name="viewport" content="width=device-width,minimum-scale=1">
    <script async src="https://cdn.ampproject.org/v0.js"></script>
    <style amp-boilerplate>body{-webkit-animation:-amp-start 8s steps(1,end) 0s 1 normal both;-moz-animation:-amp-start 8s steps(1,end) 0s 1 normal both;-ms-animation:-amp-start 8s steps(1,end) 0s 1 normal both;animation:-amp-start 8s steps(1,end) 0s 1 normal both}@-webkit-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@-moz-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@-ms-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@-o-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}</style>
</head>
<body>
    <article>
        <h1>Sample Article Title</h1>
        <p class="author">By John Doe</p>
        <time datetime="2025-01-20">January 20, 2025</time>
        <p>This is the first paragraph of the article content with enough text to be meaningful.</p>
        <p>This is the second paragraph with more detailed information about the topic.</p>
        <p>This is the third paragraph continuing the story with additional details.</p>
        <p>This is the fourth paragraph providing more context and information.</p>
        <p>This is the fifth paragraph wrapping up the main points.</p>
        <p>This is the sixth paragraph with concluding remarks.</p>
    </article>
</body>
</html>
"""

REGULAR_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Regular Page</title>
</head>
<body>
    <article>
        <h1>Regular Article</h1>
        <p>Regular content paragraph one.</p>
        <p>Regular content paragraph two.</p>
    </article>
</body>
</html>
""" * 5  # Make it long enough


class TestAMPBypassIntegration:
    """Integration tests for full AMP bypass flow."""
    
    @patch('src.crawler.ContentExtractor._get_domain_lock')
    @patch('src.crawler.ContentExtractor._check_rate_limit')
    @patch('src.crawler.ContentExtractor._get_domain_session')
    @patch('src.crawler.ContentExtractor._get_domain_amp_support')
    @patch('src.crawler.ContentExtractor._mark_domain_amp_supported')
    @patch('src.crawler.BotSensitivityManager')
    @patch('src.crawler.DatabaseManager')
    def test_full_amp_bypass_flow(
        self, 
        mock_db_class,
        mock_bot_manager_class, 
        mock_mark_amp,
        mock_get_amp_support,
        mock_session,
        mock_rate_limit,
        mock_lock
    ):
        """Test complete flow: 403 PerimeterX → Try AMP → Success."""
        # Setup mocks
        mock_rate_limit.return_value = False
        mock_get_amp_support.return_value = None  # Unknown domain
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        
        # Mock HTTP responses
        mock_403_response = Mock()
        mock_403_response.status_code = 403
        mock_403_response.text = PERIMETERX_403_HTML
        mock_403_response.elapsed.total_seconds.return_value = 0.3
        
        mock_amp_response = Mock()
        mock_amp_response.status_code = 200
        mock_amp_response.text = VALID_AMP_HTML
        mock_amp_response.elapsed.total_seconds.return_value = 0.5
        
        # Mock session - first call 403, then AMP success
        mock_session_obj = Mock()
        mock_session_obj.get.side_effect = [mock_403_response, mock_amp_response]
        mock_session.return_value = mock_session_obj
        
        # Mock bot sensitivity manager
        mock_bot_manager = MagicMock()
        mock_bot_manager_class.return_value = mock_bot_manager
        
        # Create extractor
        extractor = ContentExtractor()
        extractor.bot_sensitivity_manager = mock_bot_manager
        extractor.proxy_manager = MagicMock()
        extractor._reset_error_count = Mock()
        extractor._detect_bot_protection_in_response = Mock(return_value="perimeterx")
        extractor._record_bot_protection_detection = Mock()
        
        # Test extraction
        url = "https://fox4kc.com/news/article/"
        result = extractor._extract_with_newspaper(url)
        
        # Verify AMP bypass was used
        assert result is not None
        assert result.get('title') == 'Sample Article Title - Fox 4 Kansas City'
        assert len(result.get('content', '')) > 100
        assert 'first paragraph' in result.get('content', '')
        
        # Verify amp_supported was marked True
        mock_mark_amp.assert_called_with("fox4kc.com", True)
        
        # Verify telemetry
        calls = mock_bot_manager.record_bot_detection.call_args_list
        amp_success_calls = [c for c in calls if 'amp_bypass_success' in str(c)]
        assert len(amp_success_calls) > 0, "Should record amp_bypass_success event"
    
    @patch('src.crawler.ContentExtractor._get_domain_lock')
    @patch('src.crawler.ContentExtractor._check_rate_limit')
    @patch('src.crawler.ContentExtractor._get_domain_session')
    @patch('src.crawler.ContentExtractor._get_domain_amp_support')
    @patch('src.crawler.BotSensitivityManager')
    def test_preemptive_amp_for_known_domain(
        self,
        mock_bot_manager_class,
        mock_get_amp_support,
        mock_session,
        mock_rate_limit,
        mock_lock
    ):
        """Test preemptive AMP fetch for domains known to support AMP."""
        # Setup mocks
        mock_rate_limit.return_value = False
        mock_get_amp_support.return_value = True  # Known to support AMP
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        
        # Mock successful AMP response on first try
        mock_amp_response = Mock()
        mock_amp_response.status_code = 200
        mock_amp_response.text = VALID_AMP_HTML
        mock_amp_response.elapsed.total_seconds.return_value = 0.4
        
        mock_session_obj = Mock()
        mock_session_obj.get.return_value = mock_amp_response
        mock_session.return_value = mock_session_obj
        
        # Mock bot sensitivity manager
        mock_bot_manager = MagicMock()
        mock_bot_manager_class.return_value = mock_bot_manager
        
        # Create extractor
        extractor = ContentExtractor()
        extractor.bot_sensitivity_manager = mock_bot_manager
        extractor.proxy_manager = MagicMock()
        
        # Test extraction
        url = "https://fox4kc.com/news/article/"
        result = extractor._extract_with_newspaper(url)
        
        # Verify extraction succeeded
        assert result is not None
        assert result.get('title') == 'Sample Article Title - Fox 4 Kansas City'
        
        # Verify preemptive AMP telemetry
        calls = mock_bot_manager.record_bot_detection.call_args_list
        preemptive_calls = [c for c in calls if 'amp_preemptive_success' in str(c)]
        assert len(preemptive_calls) > 0, "Should record amp_preemptive_success event"
    
    @patch('src.crawler.ContentExtractor._get_domain_lock')
    @patch('src.crawler.ContentExtractor._check_rate_limit')
    @patch('src.crawler.ContentExtractor._get_domain_session')
    @patch('src.crawler.ContentExtractor._get_domain_amp_support')
    @patch('src.crawler.ContentExtractor._mark_domain_amp_supported')
    @patch('src.crawler.BotSensitivityManager')
    def test_amp_bypass_failure_fallback(
        self,
        mock_bot_manager_class,
        mock_mark_amp,
        mock_get_amp_support,
        mock_session,
        mock_rate_limit,
        mock_lock
    ):
        """Test that AMP bypass failure triggers Selenium fallback."""
        # Setup mocks
        mock_rate_limit.return_value = False
        mock_get_amp_support.return_value = None  # Unknown domain
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        
        # Mock HTTP responses - all fail
        mock_403_response = Mock()
        mock_403_response.status_code = 403
        mock_403_response.text = PERIMETERX_403_HTML
        mock_403_response.elapsed.total_seconds.return_value = 0.3
        
        # All AMP attempts also fail
        mock_session_obj = Mock()
        mock_session_obj.get.return_value = mock_403_response
        mock_session.return_value = mock_session_obj
        
        # Mock bot sensitivity manager
        mock_bot_manager = MagicMock()
        mock_bot_manager_class.return_value = mock_bot_manager
        
        # Create extractor
        extractor = ContentExtractor()
        extractor.bot_sensitivity_manager = mock_bot_manager
        extractor.proxy_manager = MagicMock()
        extractor._detect_bot_protection_in_response = Mock(return_value="perimeterx")
        extractor._record_bot_protection_detection = Mock()
        extractor._is_js_required_protection = Mock(return_value=True)
        extractor._mark_domain_special_extraction = Mock()
        
        # Test extraction - should raise exception for Selenium fallback
        url = "https://example.com/news/article/"
        
        with pytest.raises(Exception) as exc_info:
            extractor._extract_with_newspaper(url)
        
        # Verify exception mentions Selenium
        assert "Selenium" in str(exc_info.value) or "selenium" in str(exc_info.value).lower()
        
        # Verify amp_supported was marked False
        mock_mark_amp.assert_called_with("example.com", False)
        
        # Verify failure telemetry
        calls = mock_bot_manager.record_bot_detection.call_args_list
        failure_calls = [c for c in calls if 'amp_bypass_failure' in str(c)]
        assert len(failure_calls) > 0, "Should record amp_bypass_failure event"
    
    @patch('src.crawler.ContentExtractor._get_domain_lock')
    @patch('src.crawler.ContentExtractor._check_rate_limit')
    @patch('src.crawler.ContentExtractor._get_domain_session')
    @patch('src.crawler.ContentExtractor._get_domain_amp_support')
    @patch('src.crawler.BotSensitivityManager')
    def test_normal_flow_non_perimeterx(
        self,
        mock_bot_manager_class,
        mock_get_amp_support,
        mock_session,
        mock_rate_limit,
        mock_lock
    ):
        """Test normal extraction flow for non-PerimeterX sites."""
        # Setup mocks
        mock_rate_limit.return_value = False
        mock_get_amp_support.return_value = False  # Known NOT to support AMP
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        
        # Mock successful regular HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = REGULAR_HTML
        mock_response.elapsed.total_seconds.return_value = 0.3
        
        mock_session_obj = Mock()
        mock_session_obj.get.return_value = mock_response
        mock_session.return_value = mock_session_obj
        
        # Mock bot sensitivity manager
        mock_bot_manager = MagicMock()
        mock_bot_manager_class.return_value = mock_bot_manager
        
        # Create extractor
        extractor = ContentExtractor()
        extractor.bot_sensitivity_manager = mock_bot_manager
        extractor.proxy_manager = MagicMock()
        extractor._reset_error_count = Mock()
        
        # Test extraction
        url = "https://regular-site.com/news/article/"
        result = extractor._extract_with_newspaper(url)
        
        # Verify extraction succeeded with regular flow
        assert result is not None
        assert result.get('title') is not None
        
        # Verify no AMP telemetry
        calls = mock_bot_manager.record_bot_detection.call_args_list
        amp_calls = [c for c in calls if 'amp' in str(c).lower()]
        assert len(amp_calls) == 0, "Should not record any AMP events"


class TestAMPURLPatterns:
    """Test AMP URL pattern generation for various real-world scenarios."""
    
    def test_fox4kc_pattern(self):
        """Test AMP URL generation for fox4kc.com."""
        extractor = ContentExtractor()
        url = "https://fox4kc.com/news/local-news/article-title/"
        
        amp_urls = extractor._convert_to_amp_url(url)
        
        assert "https://fox4kc.com/news/local-news/article-title/amp/" in amp_urls
        
    def test_fourstateshomepage_pattern(self):
        """Test AMP URL generation for fourstateshomepage.com."""
        extractor = ContentExtractor()
        url = "https://www.fourstateshomepage.com/news/local-news/joplin-news/article/"
        
        amp_urls = extractor._convert_to_amp_url(url)
        
        expected = "https://www.fourstateshomepage.com/news/local-news/joplin-news/article/amp/"
        assert expected in amp_urls
        
    def test_complex_url_with_params(self):
        """Test AMP URL generation for URLs with query parameters."""
        extractor = ContentExtractor()
        url = "https://fox4kc.com/article?id=123&category=news"
        
        amp_urls = extractor._convert_to_amp_url(url)
        
        # Should append &amp=1
        assert "https://fox4kc.com/article?id=123&category=news&amp=1" in amp_urls
        
    def test_url_with_fragment(self):
        """Test AMP URL generation for URLs with fragments."""
        extractor = ContentExtractor()
        url = "https://fox4kc.com/article#section"
        
        amp_urls = extractor._convert_to_amp_url(url)
        
        # Should still add /amp/ before fragment
        assert len(amp_urls) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
