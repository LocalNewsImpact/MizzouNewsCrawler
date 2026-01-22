"""Test cross-publication byline detection with raw HTML."""

import pytest

from src.utils.content_type_detector import ContentTypeDetector


class TestCrossPublicationDetection:
    """Test detection of cross-publication syndication via author bios in raw HTML."""

    def test_detects_miami_herald_bio_on_kansas_city_star(self):
        """Test that Miami Herald author bio is detected on Kansas City Star (McClatchy syndication)."""
        detector = ContentTypeDetector()

        # Simulate raw HTML with author bio (like what newspaper4k provides)
        raw_html = """
        <html>
        <body>
        <article>
            <h1>About Miami Dolphins defensive coordinator Anthony Weaver</h1>
            <div class="byline">By C. Isaiah Smalls II</div>
            <div class="article-body">
                <p>Article content about the Miami Dolphins...</p>
            </div>
            <div class="author-bio">
                <p>C. Isaiah Smalls II is a sports reporter for the Miami Herald.
                He covers the Miami Dolphins.</p>
            </div>
        </article>
        </body>
        </html>
        """

        # Kansas City Star is also McClatchy, so this is cross-publication syndication
        result = detector.detect(
            url="https://www.kansascity.com/sports/article313786330.html",
            title="About Miami Dolphins defensive coordinator Anthony Weaver",
            metadata={"byline": "C. Isaiah Smalls II"},
            content="Article content about the Miami Dolphins...",  # Cleaned text (no bio)
            raw_html=raw_html,  # Raw HTML includes author bio
        )

        assert result is not None
        assert result.status == "wire"
        assert result.reason == "wire_service_detected"
        assert "Miami Herald" in str(result.evidence)
        assert result.confidence in ("high", "medium")

    def test_uses_cleaned_content_when_raw_html_not_available(self):
        """Test that detector falls back to cleaned content when raw HTML is missing."""
        detector = ContentTypeDetector()

        # Simulate cleaned content WITHOUT author bio (typical newspaper4k output)
        cleaned_content = "Article content about the Miami Dolphins..."

        result = detector.detect(
            url="https://www.kansascity.com/sports/article313786330.html",
            title="About Miami Dolphins defensive coordinator Anthony Weaver",
            metadata={"byline": "C. Isaiah Smalls II"},
            content=cleaned_content,
            raw_html=None,  # No raw HTML available
        )

        # Without the bio in content, detection should NOT happen
        # (unless byline itself has wire indicators)
        assert result is None or result.status != "wire"

    def test_detects_fort_worth_star_telegram_on_mcclatchy_site(self):
        """Test detection of Fort Worth Star-Telegram author on another McClatchy site."""
        detector = ContentTypeDetector()

        raw_html = """
        <html>
        <body>
        <article>
            <h1>Local sports story</h1>
            <div class="byline">By Nick Harris</div>
            <div class="article-body">
                <p>Sports coverage content...</p>
            </div>
            <div class="author-bio">
                <p>Nick Harris is the reporter for the Fort Worth Star-Telegram
                covering high school sports.</p>
            </div>
        </article>
        </body>
        </html>
        """

        result = detector.detect(
            url="https://www.kansascity.com/sports/high-school/article12345.html",
            title="Local sports story",
            metadata={"byline": "Nick Harris"},
            content="Sports coverage content...",
            raw_html=raw_html,
        )

        assert result is not None
        assert result.status == "wire"
        assert "Fort Worth Star-Telegram" in str(
            result.evidence
        ) or "Star-Telegram" in str(result.evidence)

    def test_no_false_positive_for_local_author(self):
        """Test that local author bios don't trigger false positives."""
        detector = ContentTypeDetector()

        raw_html = """
        <html>
        <body>
        <article>
            <h1>Local city council meeting</h1>
            <div class="byline">By Sarah Johnson</div>
            <div class="article-body">
                <p>The city council met Tuesday...</p>
            </div>
            <div class="author-bio">
                <p>Sarah Johnson is a reporter for The Columbia Missourian
                covering local government.</p>
            </div>
        </article>
        </body>
        </html>
        """

        # Author bio mentions the SAME publication as the URL
        result = detector.detect(
            url="https://www.columbiamissourian.com/news/local_government/article.html",
            title="Local city council meeting",
            metadata={"byline": "Sarah Johnson"},
            content="The city council met Tuesday...",
            raw_html=raw_html,
        )

        # Should NOT be detected as wire (author matches publisher)
        assert result is None or result.status != "wire"

    def test_raw_html_evidence_tracking(self):
        """Test that evidence correctly tracks whether raw HTML was used."""
        detector = ContentTypeDetector()

        raw_html = """
        <html><body><article>
            <h1>Title</h1>
            <div class="byline">By Reporter Name</div>
            <p>Content</p>
            <div class="bio">Reporter Name covers news for the Chicago Tribune.</div>
        </article></body></html>
        """

        result = detector.detect(
            url="https://www.example.com/news/article.html",
            title="Title",
            metadata={},
            content="Content",
            raw_html=raw_html,
        )

        if result and result.status == "wire":
            # Verify evidence includes raw_html flag
            assert "raw_html" in str(result.evidence).lower()
