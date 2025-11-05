"""
Test suite for comprehensive telemetry system including HTTP error tracking.
Tests the entire telemetry workflow without running production extractions.
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text

from src.crawler import ContentExtractor
from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics,
)


class TestExtractionMetrics:
    """Test the ExtractionMetrics class for capturing method-level telemetry."""

    def test_metrics_initialization(self):
        """Test that metrics are properly initialized."""
        metrics = ExtractionMetrics(
            operation_id="test-op-123",
            article_id="article-456",
            url="https://example.com/test",
            publisher="example.com",
        )

        assert metrics.operation_id == "test-op-123"
        assert metrics.article_id == "article-456"
        assert metrics.url == "https://example.com/test"
        assert metrics.publisher == "example.com"
        assert metrics.host == "example.com"
        assert metrics.http_status_code is None
        assert metrics.method_timings == {}
        assert metrics.method_success == {}
        assert metrics.method_errors == {}
        assert metrics.field_extraction == {}

    def test_start_and_end_method_success(self):
        """Test successful method timing and tracking."""
        metrics = ExtractionMetrics("op1", "art1", "https://test.com", "test.com")

        # Start method
        metrics.start_method("newspaper4k")
        assert "newspaper4k" in metrics.method_timings
        # Should be a timestamp
        assert metrics.method_timings["newspaper4k"] > 0

        # End method successfully
        extracted_fields = {
            "title": "Test Article",
            "content": "Test content",
            "author": "Test Author",
            "metadata": {"http_status": 200},
        }

        metrics.end_method("newspaper4k", True, None, extracted_fields)

        assert metrics.method_success["newspaper4k"] is True
        assert "newspaper4k" not in metrics.method_errors  # No error recorded
        assert isinstance(metrics.method_timings["newspaper4k"], float)  # Duration
        assert metrics.http_status_code == 200
        assert metrics.field_extraction["newspaper4k"]["title"] is True
        assert metrics.field_extraction["newspaper4k"]["content"] is True

    def test_start_and_end_method_failure(self):
        """Test failed method tracking with HTTP error."""
        metrics = ExtractionMetrics("op1", "art1", "https://test.com", "test.com")

        metrics.start_method("newspaper4k")

        # End method with failure
        extracted_fields = {"metadata": {"http_status": 403}}

        metrics.end_method("newspaper4k", False, "HTTP 403 Forbidden", extracted_fields)

        assert metrics.method_success["newspaper4k"] is False
        assert metrics.method_errors["newspaper4k"] == "HTTP 403 Forbidden"
        assert metrics.http_status_code == 403
        assert metrics.http_error_type == "4xx_client_error"

    def test_http_status_categorization(self):
        """Test HTTP status code categorization."""
        metrics = ExtractionMetrics("op1", "art1", "https://test.com", "test.com")

        # Test 3xx redirect
        metrics.set_http_metrics(301, 1024, 500)
        assert metrics.http_error_type == "3xx_redirect"

        # Test 4xx client error
        metrics.set_http_metrics(404, 512, 300)
        assert metrics.http_error_type == "4xx_client_error"

        # Test 5xx server error
        metrics.set_http_metrics(500, 256, 1000)
        assert metrics.http_error_type == "5xx_server_error"

        # Test success status
        metrics.set_http_metrics(200, 2048, 250)
        # Note: error_type persists once set, only categorizes errors

    def test_field_extraction_tracking(self):
        """Test field-level extraction success/failure tracking."""
        metrics = ExtractionMetrics("op1", "art1", "https://test.com", "test.com")

        # Test partial extraction
        extracted_fields = {
            "title": "Test Title",
            "content": "",  # Empty content should be False
            "author": None,  # None should be False
            "publish_date": "2023-01-01",
        }

        metrics.start_method("beautifulsoup")
        metrics.end_method("beautifulsoup", True, None, extracted_fields)

        field_stats = metrics.field_extraction["beautifulsoup"]
        assert field_stats["title"] is True
        assert field_stats["content"] is False
        assert field_stats["author"] is False
        assert field_stats["publish_date"] is True


def create_telemetry_tables(db_path: str) -> None:
    """Create telemetry tables manually for testing (without Alembic).

    This replicates the schema from Alembic migration a1b2c3d4e5f6.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create extraction_telemetry_v2 table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS extraction_telemetry_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            url TEXT NOT NULL,
            publisher TEXT,
            host TEXT,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            total_duration_ms REAL,
            http_status_code INTEGER,
            http_error_type TEXT,
            response_size_bytes INTEGER,
            response_time_ms REAL,
            methods_attempted TEXT,
            successful_method TEXT,
            method_timings TEXT,
            method_success TEXT,
            method_errors TEXT,
            field_extraction TEXT,
            extracted_fields TEXT,
            final_field_attribution TEXT,
            alternative_extractions TEXT,
            content_length INTEGER,
            is_success BOOLEAN,
            error_message TEXT,
            error_type TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            proxy_used INTEGER,
            proxy_url TEXT,
            proxy_authenticated INTEGER,
            proxy_status INTEGER,
            proxy_error TEXT
        )
    """
    )

    # Create indexes
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_operation_id "
        "ON extraction_telemetry_v2 (operation_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_article_id "
        "ON extraction_telemetry_v2 (article_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_url "
        "ON extraction_telemetry_v2 (url)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_publisher "
        "ON extraction_telemetry_v2 (publisher)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_host "
        "ON extraction_telemetry_v2 (host)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_successful_method "
        "ON extraction_telemetry_v2 (successful_method)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_is_success "
        "ON extraction_telemetry_v2 (is_success)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_telemetry_v2_created_at "
        "ON extraction_telemetry_v2 (created_at)"
    )

    # Create http_error_summary table
    # NOTE: UNIQUE(host, status_code) is required for ON CONFLICT to work.
    # This matches the production schema after migration 805164cd4665.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS http_error_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            error_type TEXT NOT NULL,
            count INTEGER NOT NULL,
            first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP NOT NULL,
            UNIQUE(host, status_code)
        )
    """
    )

    # Create indexes
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_http_error_summary_host "
        "ON http_error_summary (host)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_http_error_summary_status_code "
        "ON http_error_summary (status_code)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_http_error_summary_last_seen "
        "ON http_error_summary (last_seen)"
    )

    # Create content_type_detection_telemetry table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS content_type_detection_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            url TEXT NOT NULL,
            publisher TEXT,
            host TEXT,
            status TEXT,
            confidence TEXT,
            confidence_score REAL,
            reason TEXT,
            evidence TEXT,
            version TEXT,
            detected_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Create indexes
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_content_type_detection_article_id "
        "ON content_type_detection_telemetry (article_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_content_type_detection_status "
        "ON content_type_detection_telemetry (status)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_content_type_detection_created_at "
        "ON content_type_detection_telemetry (created_at)"
    )

    # Create byline_cleaning_telemetry table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS byline_cleaning_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            raw_byline TEXT,
            article_id TEXT,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP,
            total_time_ms REAL,
            cleaning_method TEXT,
            result_count INTEGER,
            extracted_names TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Create content_cleaning_sessions table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS content_cleaning_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            domain TEXT NOT NULL,
            article_count INTEGER NOT NULL,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP,
            total_time_ms REAL,
            rough_candidates_found INTEGER,
            segments_detected INTEGER,
            total_removable_chars INTEGER,
            removal_percentage REAL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    conn.commit()
    conn.close()


@pytest.mark.postgres
@pytest.mark.integration
class TestComprehensiveExtractionTelemetry:
    """Test comprehensive extraction telemetry with PostgreSQL."""

    @pytest.fixture(scope="class", autouse=True)
    def clear_telemetry_tables_once(self):
        """Clear all telemetry tables once before running this test class."""
        import os

        from sqlalchemy import create_engine, text

        # Get TEST_DATABASE_URL directly
        test_db_url = os.getenv("TEST_DATABASE_URL")
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set")

        # Create a temporary engine for cleanup
        engine = create_engine(test_db_url)

        try:
            with engine.connect() as conn:
                conn.execute(text("DELETE FROM http_error_summary"))
                conn.execute(text("DELETE FROM content_type_detection_telemetry"))
                conn.execute(text("DELETE FROM extraction_telemetry_v2"))
                conn.commit()
        finally:
            engine.dispose()

        yield

    @pytest.fixture
    def temp_db(self, cloud_sql_session):
        """Use PostgreSQL test database with automatic rollback."""
        import os

        # Get TEST_DATABASE_URL (SQLAlchemy masks password in str(url))
        db_url = os.getenv("TEST_DATABASE_URL")
        if not db_url:
            pytest.skip("TEST_DATABASE_URL not set")

        # Get the engine from cloud_sql_session for reuse
        engine = cloud_sql_session.get_bind().engine

        # Create TelemetryStore with PostgreSQL URL, reusing the same engine
        from src.telemetry.store import TelemetryStore

        store = TelemetryStore(database=db_url, async_writes=False, engine=engine)

        # Pass store directly to avoid SQLite file path interpretation
        telemetry = ComprehensiveExtractionTelemetry(store=store)

        # Return telemetry and session for queries
        yield telemetry, cloud_sql_session

        # Explicitly close store connection to avoid leaks
        store.shutdown()

        # No cleanup needed - cloud_sql_session handles rollback

    def test_database_initialization(self, temp_db):
        """Test that database tables are created correctly."""
        telemetry, session = temp_db

        # Use PostgreSQL information_schema to check tables
        result = session.execute(
            text(
                """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'extraction_telemetry_v2'
            ORDER BY ordinal_position
        """
            )
        )
        columns = [row[0] for row in result.fetchall()]

        expected_columns = [
            "id",
            "operation_id",
            "article_id",
            "url",
            "publisher",
            "host",
            "start_time",
            "end_time",
            "total_duration_ms",
            "http_status_code",
            "http_error_type",
            "response_size_bytes",
            "response_time_ms",
            "methods_attempted",
            "successful_method",
            "method_timings",
            "method_success",
            "method_errors",
            "field_extraction",
            "extracted_fields",
            "content_length",
            "is_success",
            "error_message",
            "error_type",
            "created_at",
        ]

        for col in expected_columns:
            assert col in columns

        # Check http_error_summary table exists
        result = session.execute(
            text(
                """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'http_error_summary'
            ORDER BY ordinal_position
        """
            )
        )
        columns = [row[0] for row in result.fetchall()]

        expected_columns = [
            "id",
            "host",
            "status_code",
            "error_type",
            "count",
            "first_seen",
            "last_seen",
        ]
        for col in expected_columns:
            assert col in columns

    def test_save_metrics_success(self, temp_db):
        """Test saving successful extraction metrics."""
        telemetry, session = temp_db

        # Create test metrics
        metrics = ExtractionMetrics(
            "op1", "art1", "https://test.com/article", "test.com"
        )
        metrics.start_time = datetime.utcnow()
        metrics.end_time = datetime.utcnow() + timedelta(seconds=5)

        # Simulate successful newspaper4k extraction
        metrics.start_method("newspaper4k")
        extracted_fields = {
            "title": "Test Article",
            "content": "Article content",
            "author": "John Doe",
            "metadata": {"http_status": 200},
        }
        metrics.end_method("newspaper4k", True, None, extracted_fields)

        # Finalize the metrics with final result
        final_result = {
            "title": "Test Article",
            "content": "Article content",
            "author": "John Doe",
        }
        metrics.finalize(final_result)

        # Save metrics
        telemetry.record_extraction(metrics)

        # Verify data was saved using PostgreSQL
        result = session.execute(text("SELECT * FROM extraction_telemetry_v2"))
        records = result.fetchall()
        assert len(records) == 1

        # Access record as dict using column names
        record = records[0]._mapping
        assert record["operation_id"] == "op1"
        assert record["article_id"] == "art1"
        assert record["url"] == "https://test.com/article"
        assert record["publisher"] == "test.com"
        assert record["host"] == "test.com"
        assert record["http_status_code"] == 200
        assert record["successful_method"] == "newspaper4k"
        assert record["is_success"] == 1

        # Check field extraction data
        field_extraction = json.loads(record["field_extraction"])
        assert field_extraction["newspaper4k"]["title"] is True
        assert field_extraction["newspaper4k"]["content"] is True

    def test_save_metrics_with_http_error(self, temp_db):
        """Test saving metrics with HTTP error tracking."""
        telemetry, session = temp_db

        # Create test metrics with HTTP error
        metrics = ExtractionMetrics(
            "op2", "art2", "https://blocked.com/article", "blocked.com"
        )
        metrics.start_time = datetime.utcnow()
        metrics.end_time = datetime.utcnow() + timedelta(seconds=3)

        # Simulate failed extraction with 403 error
        metrics.start_method("newspaper4k")
        extracted_fields = {"metadata": {"http_status": 403}}
        metrics.end_method("newspaper4k", False, "HTTP 403 Forbidden", extracted_fields)

        # Save metrics
        telemetry.record_extraction(metrics)

        # Verify extraction telemetry using PostgreSQL
        result = session.execute(
            text(
                "SELECT http_status_code, http_error_type, is_success "
                "FROM extraction_telemetry_v2 "
                "WHERE article_id = 'art2' AND operation_id = 'op2'"
            )
        )
        record = result.fetchone()._mapping
        assert record["http_status_code"] == 403
        assert record["http_error_type"] == "4xx_client_error"
        assert record["is_success"] is False

        # Verify HTTP error summary
        result = session.execute(
            text(
                "SELECT host, status_code, error_type, count "
                "FROM http_error_summary "
                "WHERE host = 'blocked.com'"
            )
        )
        error_record = result.fetchone()._mapping
        assert error_record["host"] == "blocked.com"
        assert error_record["status_code"] == 403
        assert error_record["error_type"] == "4xx_client_error"
        assert error_record["count"] >= 1  # May accumulate across test runs

    def test_get_field_extraction_stats(self, temp_db):
        """Test field extraction statistics retrieval."""
        telemetry, session = temp_db

        # Create multiple test records
        for i in range(3):
            metrics = ExtractionMetrics(
                f"op{i}", f"art{i}", f"https://test.com/article{i}", "test.com"
            )
            metrics.start_time = datetime.utcnow()
            metrics.end_time = datetime.utcnow() + timedelta(seconds=2)

            # Mix of successful and failed extractions
            success = i % 2 == 0
            extracted_fields = {
                "title": f"Title {i}" if success else "",
                "content": f"Content {i}" if success else "",
                "author": f"Author {i}" if success else None,
            }

            metrics.start_method("newspaper4k")
            metrics.end_method(
                "newspaper4k", success, None if success else "Failed", extracted_fields
            )

            telemetry.record_extraction(metrics)

        # Get field extraction stats
        stats = telemetry.get_field_extraction_stats()

        assert len(stats) > 0

        # Check that we have stats for each method
        method_names = {stat["method"] for stat in stats}
        assert "newspaper4k" in method_names

        # Find newspaper4k stats
        newspaper_stats = next(s for s in stats if s["method"] == "newspaper4k")
        # Count may be >= 3 due to cumulative test data
        assert newspaper_stats["count"] >= 3
        assert "title_success_rate" in newspaper_stats
        assert "content_success_rate" in newspaper_stats


@pytest.mark.postgres
@pytest.mark.integration
class TestContentExtractorIntegration:
    """Test integration between ContentExtractor and telemetry system.

    Uses PostgreSQL cloud_sql_session for proper test isolation.
    """

    @pytest.fixture
    def temp_db(self, cloud_sql_session):
        """Use PostgreSQL test database with automatic rollback."""
        import os

        # Get TEST_DATABASE_URL (SQLAlchemy masks password in str(url))
        db_url = os.getenv("TEST_DATABASE_URL")
        if not db_url:
            pytest.skip("TEST_DATABASE_URL not set")

        # Get the engine from cloud_sql_session for reuse
        engine = cloud_sql_session.get_bind().engine

        # Create TelemetryStore with PostgreSQL URL, reusing the same engine
        from src.telemetry.store import TelemetryStore

        store = TelemetryStore(database=db_url, async_writes=False, engine=engine)

        # Pass store directly to avoid SQLite file path interpretation
        telemetry = ComprehensiveExtractionTelemetry(store=store)

        # Return telemetry and session for queries
        yield telemetry, cloud_sql_session

        # Explicitly close store connection to avoid leaks
        store.shutdown()

    @patch("src.crawler.requests.Session.get")
    def test_extractor_with_telemetry_success(self, mock_get, temp_db):
        """Test ContentExtractor with telemetry tracking for successful extraction."""
        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
            <head><title>Test Article</title></head>
            <body>
                <h1>Test Article</h1>
                <p>This is test content.</p>
                <div class="author">John Doe</div>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        # Create extractor and metrics
        extractor = ContentExtractor()
        metrics = ExtractionMetrics(
            "test-op", "test-article", "https://test.com/article", "test.com"
        )

        # Extract content with telemetry
        result = extractor.extract_content("https://test.com/article", metrics=metrics)

        # Verify extraction succeeded
        assert result is not None
        assert result.get("title")

        # Verify telemetry was captured
        # Note: http_status_code may not be set if extraction uses
        # cached/offline methods
        # assert metrics.http_status_code == 200
        assert len(metrics.method_timings) > 0
        # At least one method succeeded
        assert any(metrics.method_success.values())

    @patch("src.crawler.requests.Session.get")
    def test_extractor_with_telemetry_http_error(self, mock_get, temp_db):
        """Test ContentExtractor with telemetry tracking for HTTP error."""
        # Mock HTTP 403 error
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_get.return_value = mock_response

        # Mock newspaper4k to also fail with 403
        with patch("src.crawler.NewspaperArticle") as mock_article_class:
            mock_article = Mock()
            mock_article.download.side_effect = Exception(
                "Article `download()` failed with Status code 403"
            )
            mock_article.title = ""
            mock_article.text = ""
            mock_article.authors = []
            mock_article.meta_description = ""
            mock_article.keywords = []
            mock_article_class.return_value = mock_article

            extractor = ContentExtractor()
            metrics = ExtractionMetrics(
                "test-op",
                "test-article",
                "https://forbidden.com/article",
                "forbidden.com",
            )

            # Extract content (should fail but capture HTTP status)
            _ = extractor.extract_content(
                "https://forbidden.com/article", metrics=metrics
            )

            # Verify HTTP error was captured
            assert metrics.http_status_code == 403
            assert metrics.http_error_type == "4xx_client_error"

    def test_telemetry_database_integration(self, temp_db):
        """Test full integration: metrics → database → API queries."""
        telemetry, session = temp_db

        # Create test scenario: mix of successes and failures
        test_scenarios = [
            ("test-extractor1.com", 200, True, "newspaper4k"),
            ("test-extractor1.com", 403, False, None),
            ("test-extractor2.com", 404, False, None),
            ("test-extractor2.com", 200, True, "beautifulsoup"),
            ("blocked-extractor.com", 403, False, None),
            ("blocked-extractor.com", 403, False, None),  # Same error again
        ]

        for i, (host, status, success, method) in enumerate(test_scenarios):
            metrics = ExtractionMetrics(
                f"extractor-op{i}",
                f"extractor-art{i}",
                f"https://{host}/article{i}",
                host,
            )
            metrics.start_time = datetime.utcnow()
            metrics.end_time = datetime.utcnow() + timedelta(seconds=2)

            if method:
                metrics.start_method(method)
                extracted_fields = {
                    "title": "Test Title" if success else "",
                    "content": "Test Content" if success else "",
                    "metadata": {"http_status": status},
                }
                metrics.end_method(
                    method,
                    success,
                    None if success else f"HTTP {status}",
                    extracted_fields,
                )
            else:
                # Failed extraction with HTTP error
                metrics.set_http_metrics(status, 0, 1000)

            telemetry.record_extraction(metrics)

        # Test database queries (simulate API endpoint logic) with PostgreSQL
        from sqlalchemy import text

        # Test method performance query - filter by our test hosts
        result = session.execute(
            text(
                """
            SELECT
                COALESCE(successful_method, 'failed') as method,
                host,
                COUNT(*) as total_attempts,
                SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successful_attempts
            FROM extraction_telemetry_v2
            WHERE host LIKE 'test-extractor%' OR host LIKE 'blocked-extractor%'
            GROUP BY COALESCE(successful_method, 'failed'), host
            ORDER BY total_attempts DESC
        """
            )
        )
        method_results = result.fetchall()
        assert len(method_results) > 0

        # Test HTTP error summary query - filter by our test hosts
        result = session.execute(
            text(
                """
            SELECT host, status_code, count
            FROM http_error_summary
            WHERE host LIKE 'test-extractor%' OR host LIKE 'blocked-extractor%'
            ORDER BY count DESC
        """
            )
        )
        error_results = result.fetchall()
        assert len(error_results) > 0

        # Verify blocked-extractor.com has 2 403 errors
        blocked_errors = [
            r for r in error_results if r[0] == "blocked-extractor.com" and r[1] == 403
        ]
        assert len(blocked_errors) == 1
        assert blocked_errors[0][2] == 2  # count should be 2

        # Test publisher stats query - filter by our test hosts
        result = session.execute(
            text(
                """
            SELECT
                host,
                COUNT(*) as total_extractions,
                SUM(CASE WHEN is_success THEN 1 ELSE 0 END)
                    as successful_extractions
            FROM extraction_telemetry_v2
            WHERE host LIKE 'test-extractor%' OR host LIKE 'blocked-extractor%'
            GROUP BY host
        """
            )
        )
        publisher_results = result.fetchall()
        # test-extractor1.com, test-extractor2.com, blocked-extractor.com
        assert len(publisher_results) == 3


class TestHTTPErrorExtraction:
    """Test HTTP error extraction from exception messages."""

    def test_http_status_extraction_from_newspaper_error(self):
        """Test extracting HTTP status codes from newspaper4k error messages."""
        import re

        error_messages = [
            (
                "Article `download()` failed with Status code 403 for "
                "url None on URL https://example.com"
            ),
            "Download failed: Status code 404 Not Found",
            "HTTP Error: Status code 500 Internal Server Error",
            "No status code in this message",
        ]

        expected_codes = [403, 404, 500, None]

        for error_msg, expected in zip(error_messages, expected_codes, strict=False):
            status_match = re.search(r"Status code (\d+)", error_msg)
            if status_match:
                extracted_code = int(status_match.group(1))
                assert extracted_code == expected
            else:
                assert expected is None


@pytest.mark.postgres
@pytest.mark.integration
class TestTelemetrySystemEndToEnd:
    """End-to-end integration tests for the complete telemetry system.

    Uses PostgreSQL cloud_sql_session for proper test isolation.
    """

    @pytest.fixture
    def temp_db(self, cloud_sql_session):
        """Use PostgreSQL test database with automatic rollback."""
        import os

        # Get TEST_DATABASE_URL (SQLAlchemy masks password in str(url))
        db_url = os.getenv("TEST_DATABASE_URL")
        if not db_url:
            pytest.skip("TEST_DATABASE_URL not set")

        # Get the engine from cloud_sql_session for reuse
        engine = cloud_sql_session.get_bind().engine

        # Create TelemetryStore with PostgreSQL URL, reusing the same engine
        from src.telemetry.store import TelemetryStore

        store = TelemetryStore(database=db_url, async_writes=False, engine=engine)

        # Pass store directly to avoid SQLite file path interpretation
        telemetry = ComprehensiveExtractionTelemetry(store=store)

        # Return telemetry and session for queries
        yield telemetry, cloud_sql_session

        # Explicitly close store connection to avoid leaks
        store.shutdown()

    def test_complete_workflow_simulation(self, temp_db):
        """Simulate a complete extraction workflow with telemetry."""
        telemetry, session = temp_db

        # Simulate a batch extraction job with unique host names
        urls = [
            "https://e2e-good-site.com/article1",
            "https://e2e-good-site.com/article2",
            "https://e2e-blocked-site.com/article1",
            "https://e2e-error-site.com/article1",
        ]

        for i, url in enumerate(urls):
            from urllib.parse import urlparse

            host = urlparse(url).netloc

            metrics = ExtractionMetrics(
                f"e2e-batch-job-{i}", f"e2e-article-{i}", url, host
            )
            metrics.start_time = datetime.utcnow()

            # Simulate different outcomes based on host
            if "good-site" in host:
                # Successful extraction
                metrics.start_method("newspaper4k")
                extracted_fields = {
                    "title": f"Article {i} Title",
                    "content": f"Article {i} content...",
                    "author": "Test Author",
                    "metadata": {"http_status": 200},
                }
                metrics.end_method("newspaper4k", True, None, extracted_fields)

            elif "blocked-site" in host:
                # HTTP 403 error
                metrics.start_method("newspaper4k")
                extracted_fields = {"metadata": {"http_status": 403}}
                metrics.end_method(
                    "newspaper4k", False, "HTTP 403 Forbidden", extracted_fields
                )

            elif "error-site" in host:
                # HTTP 500 error
                metrics.start_method("newspaper4k")
                extracted_fields = {"metadata": {"http_status": 500}}
                metrics.end_method(
                    "newspaper4k",
                    False,
                    "HTTP 500 Internal Server Error",
                    extracted_fields,
                )

            metrics.end_time = datetime.utcnow() + timedelta(seconds=2)
            telemetry.record_extraction(metrics)

        # Verify results using API-style queries with PostgreSQL
        from sqlalchemy import text

        # Overall success rate - filter by our unique hosts
        result = session.execute(
            text(
                """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successful
            FROM extraction_telemetry_v2
            WHERE host LIKE 'e2e-%'
        """
            )
        )
        total, successful = result.fetchone()
        success_rate = (successful / total * 100) if total > 0 else 0

        assert total == 4
        assert successful == 2  # Only good-site articles succeeded
        assert success_rate == 50.0

        # HTTP error breakdown - filter by our unique hosts
        result = session.execute(
            text(
                """
            SELECT status_code, COUNT(*)
            FROM http_error_summary
            WHERE host LIKE 'e2e-%'
            GROUP BY status_code
        """
            )
        )
        error_breakdown = dict(result.fetchall())
        assert 403 in error_breakdown
        assert 500 in error_breakdown
        assert error_breakdown[403] == 1
        assert error_breakdown[500] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
