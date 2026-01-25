"""
Test wire service detection in HTML footers and copyright notices.

These tests validate that ContentTypeDetector correctly identifies wire
service attribution in page footers, copyright notices, and "Powered by"
statements that appear at the end of HTML pages.
"""

import pytest
from sqlalchemy import text

from src.utils.content_type_detector import ContentTypeDetector


@pytest.fixture
def wire_patterns_session(tmp_path):
    """Create test database with Daypop and AP wire patterns and return session."""
    from src.models.database import DatabaseManager

    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"

    db = DatabaseManager(database_url=db_url)
    with db.get_session() as session:
        # Create wire_services table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS wire_services (
                id INTEGER PRIMARY KEY,
                pattern TEXT NOT NULL,
                service_name TEXT NOT NULL,
                pattern_type TEXT NOT NULL,
                case_sensitive BOOLEAN NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 50,
                active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Insert Daypop patterns
        session.execute(text("""
            INSERT INTO wire_services (pattern, service_name, pattern_type, case_sensitive, priority, active, created_at, updated_at)
            VALUES
                ('Powered by Daypop', 'Daypop', 'content', 0, 50, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('Daypop', 'Daypop', 'content', 0, 50, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('© .* Daypop', 'Daypop', 'copyright', 0, 50, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))

        # Insert AP pattern for other tests
        session.execute(text("""
            INSERT INTO wire_services (pattern, service_name, pattern_type, case_sensitive, priority, active, created_at, updated_at)
            VALUES ('© .* The Associated Press', 'AP', 'copyright', 0, 50, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))

        session.commit()
        yield session


class TestFooterWireDetection:
    """Test wire service detection in HTML footers."""

    def test_detects_daypop_in_html_footer(self, wire_patterns_session):
        """Should detect Daypop attribution in HTML footer."""
        # Simulate typical article structure: cleaned content without footer
        # but raw HTML includes footer with Daypop attribution
        cleaned_content = "Nick Reiner's son has rare genetic disorder..."

        # Raw HTML includes typical footer structure with Daypop attribution
        raw_html = """
        <html>
        <body>
            <article>
                <p>Nick Reiner's son has rare genetic disorder...</p>
            </article>
            <footer class="site-footer">
                <div class="powered-by">Powered by Daypop</div>
                <p>© 2025 KTTS Radio</p>
            </footer>
        </body>
        </html>
        """

        detector = ContentTypeDetector(session=wire_patterns_session)
        result = detector.detect(
            url="https://www.ktts.com/2025/12/16/nick-reiner-son...",
            title="Nick Reiner's son has rare genetic disorder",
            metadata={},
            content=cleaned_content,
            raw_html=raw_html,
        )

        assert result is not None, "Should detect Daypop in footer"
        assert result.status == "wire"
        assert "daypop" in str(result.evidence).lower()
        # Raw HTML used for detection
        assert (
            "footer" in str(result.evidence).lower()
            or "raw_html" in str(result.evidence).lower()
        )

    def test_detects_copyright_in_html_footer(self):
        """Should detect wire service in copyright notice at end of HTML."""
        cleaned_content = "Article text without copyright notice..."

        # Copyright at end of HTML
        raw_html = """
        <html>
        <body>
            <article><p>Article text without copyright notice...</p></article>
            <div class="copyright">© 2025 The Associated Press. All rights reserved.</div>
        </body>
        </html>
        """

        detector = ContentTypeDetector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="News Story",
            metadata={},
            content=cleaned_content,
            raw_html=raw_html,
        )

        assert result is not None, "Should detect AP in copyright"
        assert result.status == "wire"
        assert "associated press" in str(result.evidence).lower()

    def test_prefers_cleaned_content_copyright_when_present(self):
        """Should detect copyright in cleaned content if present."""
        # Copyright in both cleaned content and raw HTML
        cleaned_content = "Story text...\n\n© 2025 Reuters. All rights reserved."
        raw_html = "<html><body><p>Story text...</p><footer>© 2025 Reuters</footer></body></html>"

        detector = ContentTypeDetector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="Story Title",
            metadata={},
            content=cleaned_content,
            raw_html=raw_html,
        )

        assert result is not None
        assert result.status == "wire"
        # Should find it in cleaned_content section first
        assert "cleaned_content" in str(result.evidence).lower()

    def test_no_false_positive_for_unrelated_footer_text(self):
        """Should not trigger on common footer text without wire patterns."""
        cleaned_content = "Local news story..."
        raw_html = """
        <html>
        <body>
            <article><p>Local news story...</p></article>
            <footer>
                <p>Contact us: news@local.com</p>
                <p>© 2025 Local News Inc.</p>
            </footer>
        </body>
        </html>
        """

        detector = ContentTypeDetector()
        result = detector.detect(
            url="https://localnews.com/story",
            title="Local News Story",
            metadata={},
            content=cleaned_content,
            raw_html=raw_html,
        )

        # Should not detect wire service
        assert result is None or result.status != "wire"

    def test_detects_multiple_patterns_in_footer(self, wire_patterns_session):
        """Should detect when multiple wire indicators in footer."""
        cleaned_content = "Article text..."
        raw_html = """
        <html>
        <body>
            <article><p>Article text...</p></article>
            <footer>
                <p>Powered by Daypop</p>
                <p>© 2025 Daypop Media Services</p>
            </footer>
        </body>
        </html>
        """

        detector = ContentTypeDetector(session=wire_patterns_session)
        result = detector.detect(
            url="https://example.com/news",
            title="Article Title",
            metadata={},
            content=cleaned_content,
            raw_html=raw_html,
        )

        assert result is not None
        assert result.status == "wire"
        # Should detect Daypop pattern in footer
        assert "daypop" in str(result.evidence).lower()

    @pytest.mark.skip(
        reason="Detector requires cleaned content - footer-only detection not yet implemented"
    )
    def test_footer_detection_without_cleaned_content(self, wire_patterns_session):
        """Should still detect in footer even if cleaned content missing."""
        # No cleaned content (extraction failed), but raw HTML available
        raw_html = """
        <html>
        <body>
            <article><p>Story text...</p></article>
            <footer>© 2025 The Associated Press</footer>
        </body>
        </html>
        """

        detector = ContentTypeDetector(session=wire_patterns_session)
        result = detector.detect(
            url="https://example.com/news",
            title="News Article",
            metadata={},
            content=None,  # No cleaned content
            raw_html=raw_html,
        )

        assert result is not None
        assert result.status == "wire"
        assert "associated press" in str(result.evidence).lower()
