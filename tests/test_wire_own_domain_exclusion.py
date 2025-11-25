"""Tests for wire service own-domain exclusion logic.

Tests that ContentTypeDetector correctly excludes wire services' own domains
(e.g., apnews.com, reuters.com) from being flagged as syndicated wire content.
"""

from src.utils.content_type_detector import ContentTypeDetector


class TestWireOwnDomainExclusion:
    """Test that wire services' own domains are excluded from detection."""

    def test_ap_news_own_domain_excluded(self):
        """Test that apnews.com articles are not flagged as wire content."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://apnews.com/article/politics-biden-123456",
            title="Biden Announces New Policy",
            metadata={"byline": "Associated Press"},
            content="WASHINGTON (AP) — President Biden announced...",
        )

        # Should return None because this is AP's own content, not syndicated
        assert result is None

    def test_reuters_own_domain_excluded(self):
        """Test that reuters.com articles are not flagged as wire content."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.reuters.com/world/europe/uk-politics-2024",
            title="UK Political Update",
            metadata={"byline": "Reuters Staff"},
            content="LONDON (Reuters) — British lawmakers voted...",
        )

        assert result is None

    def test_cnn_own_domain_excluded(self):
        """Test that cnn.com articles are not flagged as wire content."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.cnn.com/2024/11/25/politics/election",
            title="Election Coverage",
            metadata={"byline": "CNN Political Team"},
            content="CNN — The election results show...",
        )

        assert result is None

    def test_nyt_own_domain_excluded(self):
        """Test that nytimes.com articles are not flagged as wire content."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.nytimes.com/2024/11/25/us/politics/congress.html",
            title="Congress Passes Bill",
            metadata={"byline": "The New York Times"},
            content="Congress passed legislation today...",
        )

        assert result is None

    def test_npr_own_domain_excluded(self):
        """Test that npr.org articles are not flagged as wire content."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.npr.org/2024/11/25/health-policy",
            title="Health Policy Update",
            metadata={"byline": "NPR News"},
            content="NPR — Health officials announced...",
        )

        assert result is None

    def test_states_newsroom_own_domain_excluded(self):
        """Test that statesnewsroom.org is excluded."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://statesnewsroom.org/2024/state-policy",
            title="State Policy Changes",
            metadata={"byline": "States Newsroom"},
            content="Multiple states announced policy changes...",
        )

        assert result is None

    def test_kansas_reflector_own_domain_excluded(self):
        """Test that kansasreflector.com is excluded."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://kansasreflector.com/2024/kansas-legislature",
            title="Kansas Legislature Update",
            metadata={"byline": "Kansas Reflector"},
            content="The Kansas legislature voted today...",
        )

        assert result is None

    def test_missouri_independent_own_domain_excluded(self):
        """Test that missouriindependent.com is excluded."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://missouriindependent.com/2024/mo-politics",
            title="Missouri Politics",
            metadata={"byline": "Missouri Independent"},
            content="Missouri lawmakers passed legislation...",
        )

        assert result is None

    def test_syndicated_ap_content_detected(self):
        """Test that AP content on local news site IS detected as wire."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://localnews.com/national/politics-story",
            title="National Political Update",
            metadata={"byline": "Associated Press"},
            content="WASHINGTON (AP) — Congress voted today...",
        )

        # Should be detected as wire because it's syndicated on localnews.com
        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence

    def test_syndicated_reuters_content_detected(self):
        """Test that Reuters content on local site IS detected as wire."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://localnewspaper.com/world/international-news",
            title="International News",
            metadata={"byline": "Reuters"},
            content="LONDON (Reuters) — British officials...",
        )

        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence

    def test_usa_today_own_domain_excluded(self):
        """Test that usatoday.com is excluded."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.usatoday.com/story/news/nation/2024/11/25/story",
            title="National Story",
            metadata={"byline": "USA TODAY"},
            content="A national story from USA TODAY...",
        )

        assert result is None

    def test_bloomberg_own_domain_excluded(self):
        """Test that bloomberg.com is excluded."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.bloomberg.com/news/articles/2024-markets",
            title="Market Analysis",
            metadata={"byline": "Bloomberg News"},
            content="Markets surged today...",
        )

        assert result is None

    def test_wsj_own_domain_excluded(self):
        """Test that wsj.com is excluded."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.wsj.com/articles/business-news-123456",
            title="Business News",
            metadata={"byline": "Wall Street Journal"},
            content="The market continues to...",
        )

        assert result is None

    def test_wave3_own_domain_excluded(self):
        """Test that wave3.com is excluded."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://www.wave3.com/2024/11/25/local-story",
            title="Louisville Local News",
            metadata={"byline": "WAVE"},
            content="Local Louisville news...",
        )

        assert result is None

    def test_subdomain_variations_excluded(self):
        """Test that subdomains are also excluded (www., mobile., etc.)."""
        detector = ContentTypeDetector()

        # Test www subdomain
        result = detector.detect(
            url="https://www.apnews.com/article/story-123",
            title="AP Story",
            metadata={"byline": "Associated Press"},
            content="News story...",
        )
        assert result is None

        # Test mobile subdomain
        result = detector.detect(
            url="https://mobile.reuters.com/article/world-news",
            title="Reuters Story",
            metadata={"byline": "Reuters"},
            content="News story...",
        )
        assert result is None

    def test_case_insensitive_domain_check(self):
        """Test that domain checking is case-insensitive."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://WWW.APNEWS.COM/article/STORY",
            title="AP Story",
            metadata={"byline": "Associated Press"},
            content="News story...",
        )

        assert result is None

    def test_non_wire_domain_with_wire_byline_detected(self):
        """Test that wire bylines on non-wire domains ARE detected."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="https://localcitynews.com/story",
            title="Local Story with AP Byline",
            metadata={"byline": "Associated Press"},
            content="Story content...",
        )

        # Should be detected as wire
        assert result is not None
        assert result.status == "wire"

    def test_malformed_url_handled_gracefully(self):
        """Test that malformed URLs don't crash the detector."""
        detector = ContentTypeDetector()

        # URL without protocol
        result = detector.detect(
            url="apnews.com/article/story",
            title="Story",
            metadata={"byline": "Associated Press"},
            content="Content...",
        )

        # Should still exclude (domain check should handle this)
        # or at minimum not crash
        assert result is None or result.status == "wire"

    def test_path_only_url_with_wire_content(self):
        """Test relative/path-only URLs with wire indicators."""
        detector = ContentTypeDetector()

        result = detector.detect(
            url="/national/politics/story-123",
            title="Political Story",
            metadata={"byline": "Associated Press"},
            content="WASHINGTON (AP) — News...",
        )

        # Should detect as wire based on /national/ path and AP byline
        assert result is not None
        assert result.status == "wire"
