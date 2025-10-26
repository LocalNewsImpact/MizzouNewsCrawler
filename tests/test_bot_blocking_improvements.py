"""Test bot blocking improvements and anti-detection features."""

import sys
from pathlib import Path
from unittest.mock import Mock

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crawler import ContentExtractor, NewsCrawler  # noqa: E402


class TestUserAgentImprovements:
    """Test user agent pool improvements."""

    def test_user_agent_pool_size(self):
        """User agent pool should have sufficient variety."""
        extractor = ContentExtractor()
        assert (
            len(extractor.user_agent_pool) >= 10
        ), "Should have at least 10 user agents"

    def test_recent_chrome_versions(self):
        """User agents should include recent Chrome versions."""
        extractor = ContentExtractor()
        chrome_agents = [ua for ua in extractor.user_agent_pool if "Chrome" in ua]
        assert len(chrome_agents) > 0, "Should have Chrome user agents"

        # Check for recent versions (127+)
        recent_versions = [
            ua
            for ua in chrome_agents
            if any(f"Chrome/{v}" in ua for v in ["127", "128", "129"])
        ]
        assert len(recent_versions) > 0, "Should have recent Chrome versions"

    def test_multiple_browsers(self):
        """User agent pool should include different browser types."""
        extractor = ContentExtractor()
        ua_text = " ".join(extractor.user_agent_pool)

        assert "Chrome" in ua_text, "Should have Chrome user agents"
        assert "Firefox" in ua_text, "Should have Firefox user agents"
        assert "Safari" in ua_text, "Should have Safari user agents"

    def test_multiple_platforms(self):
        """User agent pool should include different platforms."""
        extractor = ContentExtractor()
        ua_text = " ".join(extractor.user_agent_pool)

        assert "Windows" in ua_text, "Should have Windows user agents"
        assert (
            "Macintosh" in ua_text or "Mac OS X" in ua_text
        ), "Should have macOS user agents"
        assert "Linux" in ua_text or "X11" in ua_text, "Should have Linux user agents"

    def test_news_crawler_realistic_ua(self):
        """NewsCrawler should use realistic User-Agent by default."""
        crawler = NewsCrawler()

        # Should not identify as crawler/bot
        assert "Crawler" not in crawler.user_agent
        assert "Bot" not in crawler.user_agent

        # Should look like a real browser
        assert "Mozilla/5.0" in crawler.user_agent
        assert any(
            browser in crawler.user_agent
            for browser in ["Chrome", "Firefox", "Safari", "Edge"]
        )


class TestHeaderImprovements:
    """Test header generation improvements."""

    def test_accept_header_pool_exists(self):
        """Accept header pool should exist with multiple variations."""
        extractor = ContentExtractor()
        assert hasattr(extractor, "accept_header_pool")
        assert len(extractor.accept_header_pool) > 0

    def test_modern_accept_headers(self):
        """Accept headers should support modern image formats."""
        extractor = ContentExtractor()
        modern_formats = ["image/webp", "image/avif", "image/apng"]

        headers_text = " ".join(extractor.accept_header_pool)
        has_modern = any(fmt in headers_text for fmt in modern_formats)
        assert has_modern, "Should support modern image formats"

    def test_accept_language_variations(self):
        """Accept-Language should have multiple variations."""
        extractor = ContentExtractor()
        assert len(extractor.accept_language_pool) >= 5

    def test_accept_encoding_variations(self):
        """Accept-Encoding should have multiple variations."""
        extractor = ContentExtractor()
        assert len(extractor.accept_encoding_pool) >= 2

        # Should support Brotli compression
        encoding_text = " ".join(extractor.accept_encoding_pool)
        assert "br" in encoding_text, "Should support Brotli encoding"


class TestRefererGeneration:
    """Test Referer header generation."""

    def test_referer_generation_works(self):
        """Referer generation should produce valid URLs."""
        extractor = ContentExtractor()
        test_url = "https://example.com/news/article-123"

        referer = extractor._generate_referer(test_url)
        # May be None (10% of the time), or a valid referer
        if referer:
            assert referer.startswith("http"), "Referer should be a valid URL"

    def test_referer_variation(self):
        """Referer generation should produce varied results."""
        extractor = ContentExtractor()
        test_url = "https://example.com/news/article-123"

        referers = set()
        for _ in range(30):
            referer = extractor._generate_referer(test_url)
            if referer:
                referers.add(referer)

        # Should generate at least 2 different referers
        assert len(referers) >= 2, "Should generate varied referers"

    def test_referer_same_domain(self):
        """Some referers should be from the same domain."""
        extractor = ContentExtractor()
        test_url = "https://example.com/news/article-123"

        referers = []
        for _ in range(50):
            referer = extractor._generate_referer(test_url)
            if referer:
                referers.append(referer)

        same_domain = [r for r in referers if "example.com" in r]
        assert len(same_domain) > 0, "Should have some same-domain referers"

    def test_referer_invalid_url(self):
        """Invalid URLs should not cause errors."""
        extractor = ContentExtractor()

        # Should not crash with invalid URLs
        referer = extractor._generate_referer("")
        assert referer is None or isinstance(referer, str)

        referer = extractor._generate_referer("not-a-url")
        assert referer is None or isinstance(referer, str)


class TestBotProtectionDetection:
    """Test bot protection detection."""

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

    def test_generic_bot_protection(self):
        """Should detect generic bot protection."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = """
        <html>
        <body>
        <h1>Access Denied</h1>
        <p>You have been blocked by our security check.</p>
        </body>
        </html>
        """
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "bot_protection"

    def test_captcha_detection(self):
        """Should detect CAPTCHA pages."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = "<html><body><h1>Please complete the CAPTCHA</h1></body></html>"
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "bot_protection"

    def test_short_response_detection(self):
        """Should detect suspiciously short error responses."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = "<html><body>Forbidden</body></html>"
        response.status_code = 403

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection == "suspicious_short_response"

    def test_normal_page_not_flagged(self):
        """Normal pages should not be flagged as bot protection."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = (
            """
        <!DOCTYPE html>
        <html>
        <head><title>News Article</title></head>
        <body>
        <article>
        <h1>This is a real news article</h1>
        <p>This is the content of the article with lots of text.</p>
        """
            + "<p>More content.</p>" * 20
            + """
        </article>
        </body>
        </html>
        """
        )
        response.status_code = 200

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection is None

    def test_none_response(self):
        """Should handle None response gracefully."""
        extractor = ContentExtractor()

        protection = extractor._detect_bot_protection_in_response(None)
        assert protection is None

    def test_empty_response(self):
        """Should handle empty response gracefully."""
        extractor = ContentExtractor()

        response = Mock()
        response.text = ""
        response.status_code = 200

        protection = extractor._detect_bot_protection_in_response(response)
        assert protection is None


class TestSessionManagement:
    """Test session management improvements."""

    def test_rotation_stats_available(self):
        """Rotation stats should be available."""
        extractor = ContentExtractor()
        stats = extractor.get_rotation_stats()

        assert "total_domains_accessed" in stats
        assert "active_sessions" in stats
        assert "user_agent_pool_size" in stats
        assert stats["user_agent_pool_size"] > 0
