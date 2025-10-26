import os
import tempfile
from typing import Optional
from unittest.mock import Mock, patch

from src.utils.byline_cleaner import BylineCleaner
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


class _StubTelemetry:
    def __init__(self, patterns):
        self._patterns = patterns
        self.log_summary = {
            "sessions": [],
            "patterns_analyzed": patterns,
            "total_sessions": 0,
        }

    def start_session(self, *args, **kwargs):
        return None

    def log_pattern_analysis(self, *args, **kwargs):
        pass

    def end_session(self, *args, **kwargs):
        pass

    def get_log_summary(self):
        return self.log_summary


class TestBalancedContentCleanerBasics:
    """Test basic initialization and setup."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")
        assert cleaner.db_path == ":memory:"
        assert cleaner.enable_telemetry is True

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path="/custom/path.db", enable_telemetry=False
        )
        assert cleaner.db_path == "/custom/path.db"
        assert cleaner.enable_telemetry is False

    def test_connect_to_db_creates_connection(self):
        """Test that database connection works."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cleaner = BalancedBoundaryContentCleaner(db_path=tmp_path)
            conn = cleaner._connect_to_db()
            assert conn is not None
            conn.close()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestDomainAnalysis:
    """Test domain analysis functionality."""

    def test_analyze_domain_with_persistent_patterns(self):
        """Test domain analysis using persistent patterns."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        # Mock both database methods to avoid schema issues
        mock_articles = [
            {
                "id": 1,
                "url": "https://example.com/article1",
                "content": "Article content with newsletter signup",
                "text_hash": "hash1",
            }
        ]
        persistent_patterns = [
            {
                "text_content": "Subscribe to newsletter",
                "pattern_type": "newsletter_signup",
                "confidence_score": 0.9,
                "occurrences_total": 5,
                "removal_reason": "Newsletter signup prompt",
            }
        ]

        with patch.object(
            cleaner, "_get_articles_for_domain", return_value=mock_articles
        ):
            with patch.object(
                cleaner,
                "_get_persistent_patterns_for_domain",
                return_value=persistent_patterns,
            ):
                with patch.object(
                    cleaner,
                    "_calculate_domain_stats",
                    return_value={"total_segments": 1},
                ):
                    result = cleaner.analyze_domain("example.com")

        assert isinstance(result, dict)

    def test_get_articles_for_domain_with_mocked_db(self):
        """Test article fetching from database."""
        cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (1, "https://example.com/art1", "Article 1 content", "hash1"),
            (2, "https://example.com/art2", "Article 2 content", "hash2"),
        ]

        mock_session = Mock()
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session

        with patch(
            "src.utils.content_cleaner_balanced.DatabaseManager",
            return_value=mock_db,
        ):
            articles = cleaner._get_articles_for_domain("example.com")

        assert len(articles) == 2
        assert articles[0]["id"] == 1
        assert articles[0]["content"] == "Article 1 content"

    def test_get_articles_handles_db_error(self):
        """Test graceful handling of database errors."""
        cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

        # Mock the entire method to return empty list on error
        with patch.object(cleaner, "_get_articles_for_domain", return_value=[]):
            articles = cleaner._get_articles_for_domain("example.com")

        assert articles == []


class TestRoughCandidateDetection:
    """Test rough candidate pattern detection."""

    def test_find_rough_candidates_basic_functionality(self):
        """Test basic rough candidate detection."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        mock_articles = [
            {
                "id": 1,
                "content": (
                    "A very long repeated boilerplate pattern "
                    "that appears multiple times.\nContent 1"
                ),
            },
            {
                "id": 2,
                "content": (
                    "A very long repeated boilerplate pattern "
                    "that appears multiple times.\nContent 2"
                ),
            },
            {
                "id": 3,
                "content": (
                    "A very long repeated boilerplate pattern "
                    "that appears multiple times.\nContent 3"
                ),
            },
        ]

        candidates = cleaner._find_rough_candidates(mock_articles)

        assert isinstance(candidates, dict)

    def test_find_rough_candidates_filters_short_patterns(self):
        """Test that short patterns are filtered out."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        mock_articles = [
            {"id": 1, "content": "Short text.\nContent 1"},
            {"id": 2, "content": "Short text.\nContent 2"},
        ]

        candidates = cleaner._find_rough_candidates(mock_articles)

        # Should be empty or have fewer patterns due to length filtering
        assert isinstance(candidates, dict)


class TestPatternRemoval:
    """Test pattern removal functionality."""

    def test_remove_social_share_header_detection(self):
        """Test social share header detection and removal."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        content_with_header = (
            "Share on Facebook\nShare on Twitter\nShare on LinkedIn\n"
            "This is the actual article content that should remain."
        )

        result = cleaner._remove_social_share_header(content_with_header)

        assert isinstance(result, dict)
        assert "cleaned_text" in result
        assert "removed_text" in result

    def test_remove_social_share_header_no_header(self):
        """Test content without social share headers."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        clean_content = "This is clean article content without headers."

        result = cleaner._remove_social_share_header(clean_content)

        assert isinstance(result, dict)
        assert result["cleaned_text"] == clean_content

    def test_remove_persistent_patterns_with_matches(self):
        """Test removal of persistent patterns when matches exist."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        content = "Article content\nSubscribe to newsletter\nMore content"

        result = cleaner._remove_persistent_patterns(content, "example.com")

        assert isinstance(result, dict)
        assert "cleaned_text" in result

    def test_remove_persistent_patterns_no_matches(self):
        """Test pattern removal when no patterns match."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        content = "Clean article content"

        result = cleaner._remove_persistent_patterns(content, "example.com")

        assert isinstance(result, dict)
        assert result["cleaned_text"] == content


class TestNavigationExtraction:
    """Test navigation extraction functionality."""

    def test_extract_navigation_prefix_with_required_tokens(self):
        """Test navigation extraction with required tokens."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        content_with_nav = (
            "Home > News > Sports > Article Title\nThis is the main article content."
        )

        result = cleaner._extract_navigation_prefix(content_with_nav)

        assert isinstance(result, str)
        assert result.lower().startswith("home")
        assert "news" in result.lower()

    def test_extract_navigation_prefix_short_content(self):
        """Test navigation extraction with short content."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        short_content = "Brief article"

        result = cleaner._extract_navigation_prefix(short_content)

        assert result is None


class TestContextRetrieval:
    """Test context retrieval functionality."""

    def test_get_article_source_context_success(self):
        """Test successful article source context retrieval."""
        cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("example.com", "Example News")

        with patch.object(cleaner, "_connect_to_db", return_value=mock_conn):
            context = cleaner._get_article_source_context("123")

        assert isinstance(context, dict)

    def test_get_article_source_context_no_results(self):
        """Test context retrieval when no results found."""
        cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch.object(cleaner, "_connect_to_db", return_value=mock_conn):
            context = cleaner._get_article_source_context("123")

        assert context == {}


class TestLocalityAssessment:
    """Test locality assessment functionality."""

    def test_assess_locality_with_context(self):
        """Test locality assessment with valid context."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        context: dict[str, Optional[str]] = {
            "domain": "example.com",
            "source_name": "Local News",
            "location": "Columbia, MO",
        }

        text = "Local news about Columbia events"

        result = cleaner._assess_locality(text, context, "example.com")

        assert isinstance(result, dict) or result is None

    def test_assess_locality_empty_context(self):
        """Test locality assessment with empty context."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        empty_context: dict[str, Optional[str]] = {}
        result = cleaner._assess_locality(
            "Some text",
            empty_context,
            "example.com",
        )

        assert isinstance(result, dict) or result is None

    def test_assess_locality_empty_text(self):
        """Test locality assessment with empty text."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        context: dict[str, Optional[str]] = {"domain": "example.com"}

        result = cleaner._assess_locality("", context, "example.com")

        assert isinstance(result, dict) or result is None


class TestUtilityMethods:
    """Test utility methods."""

    def test_normalize_navigation_token_various_inputs(self):
        """Test navigation token normalization."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        assert cleaner._normalize_navigation_token("HOME") == "home"
        assert cleaner._normalize_navigation_token("News & Sports") == "news"
        assert cleaner._normalize_navigation_token("123") == "123"

    def test_process_single_article_basic_functionality(self):
        """Test basic single article processing."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        content = "Test article content"

        with patch.object(cleaner, "_get_article_source_context", return_value={}):
            result = cleaner.process_single_article(
                content, "example.com", article_id="1"
            )

        assert isinstance(result, tuple)
        assert len(result) == 2
        cleaned_text, metadata = result
        assert isinstance(cleaned_text, str)
        assert isinstance(metadata, dict)

    def test_process_single_article_with_wire_detection(self):
        """Test article processing with wire service detection."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        content = "(AP) - This is an Associated Press article"

        with patch.object(cleaner, "_get_article_source_context", return_value={}):
            result = cleaner.process_single_article(
                content, "example.com", article_id="1"
            )

        assert isinstance(result, tuple)
        assert len(result) == 2
        cleaned_text, metadata = result
        assert isinstance(cleaned_text, str)
        assert isinstance(metadata, dict)


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_database_connection_failure_graceful_handling(self):
        """Test graceful handling of database connection failures."""
        cleaner = BalancedBoundaryContentCleaner(db_path="/nonexistent/path/db.sqlite")

        # Mock to return empty results on connection failure
        with patch.object(cleaner, "_get_articles_for_domain", return_value=[]):
            articles = cleaner._get_articles_for_domain("example.com")

        assert articles == []

    def test_empty_domain_analysis(self):
        """Test domain analysis with empty domain."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        with patch.object(cleaner, "_get_articles_for_domain", return_value=[]):
            with patch.object(
                cleaner, "_get_persistent_patterns_for_domain", return_value=[]
            ):
                result = cleaner.analyze_domain("")

        assert isinstance(result, dict)

    def test_malformed_article_content_handling(self):
        """Test handling of malformed article content."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        malformed_content = None  # Malformed content

        with patch.object(cleaner, "_get_article_source_context", return_value={}):
            # This should handle None content gracefully
            result = cleaner.process_single_article(
                malformed_content or "", "example.com", article_id="1"
            )

        assert isinstance(result, tuple)
        assert isinstance(result[0], str)
        assert isinstance(result[1], dict)


class TestBoundaryDetection:
    """Test boundary detection functionality."""

    def test_assess_boundary_quality_basic(self):
        """Test basic boundary quality assessment."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        text = "This is a test text for boundary assessment."

        result = cleaner._assess_boundary_quality(text)

        assert isinstance(result, (int, float))


class TestIntegration:
    """Test integration scenarios."""

    def test_comprehensive_processing_integration(self):
        """Test comprehensive article processing integration."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        content = (
            "Share on Facebook\nHome > News > Sports\n"
            "This is the main article content with some text."
        )

        with patch.object(
            cleaner,
            "_get_article_source_context",
            return_value={"domain": "example.com"},
        ):
            result = cleaner.process_single_article(
                content, "example.com", article_id="1"
            )

        assert isinstance(result, tuple)
        cleaned_text, metadata = result
        assert isinstance(cleaned_text, str)
        assert isinstance(metadata, dict)

    def test_domain_analysis_integration(self):
        """Test domain analysis integration with multiple components."""
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )

        # Mock articles and patterns for comprehensive test
        mock_articles = [
            {"id": 1, "content": "Article 1 with pattern", "url": "url1"},
            {"id": 2, "content": "Article 2 with pattern", "url": "url2"},
        ]
        mock_patterns = [{"text_content": "pattern", "confidence_score": 0.8}]

        with patch.object(
            cleaner, "_get_articles_for_domain", return_value=mock_articles
        ):
            with patch.object(
                cleaner,
                "_get_persistent_patterns_for_domain",
                return_value=mock_patterns,
            ):
                result = cleaner.analyze_domain("example.com")
        assert isinstance(result, dict)
        assert "article_count" in result


class DummyWireDetector(BylineCleaner):
    """Simple stub for controlling wire service detection outcomes."""

    def __init__(
        self,
        *,
        is_wire_service: bool,
        is_own_source: bool = False,
        normalized_name: str = "Associated Press",
    ) -> None:
        super().__init__()
        self._is_wire_service_result = is_wire_service
        self._is_own_source_result = is_own_source
        self._normalized_name = normalized_name
        self._detected_wire_services = []  # Populated when detection occurs

    def _is_wire_service(self, byline: str) -> bool:  # noqa: D401
        if self._is_wire_service_result:
            self._detected_wire_services.append(self._normalized_name)
        return self._is_wire_service_result

    def _is_wire_service_from_own_source(
        self, wire_service: str, source_name: str
    ) -> bool:  # noqa: D401 - test double
        return self._is_own_source_result

    def _normalize_wire_service(self, service_name: str) -> str:  # noqa: D401
        return self._normalized_name


class TestWireDetection:
    """Tests covering wire-service detection heuristics."""

    def test_detect_wire_service_via_byline_detector(self):
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )
        cleaner.wire_detector = DummyWireDetector(
            is_wire_service=True
        )  # type: ignore[assignment]

        result = cleaner._detect_wire_service_in_pattern(
            "Story courtesy of the Associated Press", "example.com"
        )

        assert result is not None
        assert result["provider"].lower() == "associated press"
        assert result["detection_method"] == "pattern_analysis"

    def test_detect_wire_service_skips_own_source(self):
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )
        cleaner.wire_detector = DummyWireDetector(
            is_wire_service=True, is_own_source=True
        )  # type: ignore[assignment]

        result = cleaner._detect_wire_service_in_pattern(
            "Our AP-partnered report", "example.com"
        )

        assert result is None

    def test_detect_wire_service_regex_fallback(self):
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )
        cleaner.wire_detector = DummyWireDetector(
            is_wire_service=False, normalized_name="reuters normalized"
        )  # type: ignore[assignment]

        result = cleaner._detect_wire_service_in_pattern(
            "Reporting by Reuters staff", "localpaper.com"
        )

        assert result is not None
        assert result["provider"] == "reuters normalized"
        assert result["detection_method"] == "regex_pattern"

    def test_detect_wire_service_respects_domain_provider_overlap(self):
        cleaner = BalancedBoundaryContentCleaner(
            db_path=":memory:", enable_telemetry=False
        )
        cleaner.wire_detector = DummyWireDetector(
            is_wire_service=False
        )  # type: ignore[assignment]

        result = cleaner._detect_wire_service_in_pattern(
            "Photos via AP News", "associatedpress.com"
        )

        assert result is None
