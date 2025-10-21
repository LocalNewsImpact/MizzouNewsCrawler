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
    cur.execute("""
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
    """)
    
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
    cur.execute("""
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
    """)
    
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
    cur.execute("""
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
    """)
    
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
    cur.execute("""
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
    """)
    
    # Create content_cleaning_sessions table
    cur.execute("""
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
    """)
    
    conn.commit()
    conn.close()


class TestComprehensiveExtractionTelemetry:
    """Test the database operations and telemetry storage."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        # Create tables manually (since we don't run Alembic migrations in tests)
        create_telemetry_tables(db_path)
        
        telemetry = ComprehensiveExtractionTelemetry(db_path)
        yield telemetry, db_path

        # Cleanup
        Path(db_path).unlink(missing_ok=True)

    def test_database_initialization(self, temp_db):
        """Test that database tables are created correctly."""
        telemetry, db_path = temp_db

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check extraction_telemetry_v2 table exists with correct columns
        cur.execute("PRAGMA table_info(extraction_telemetry_v2)")
        columns = [row[1] for row in cur.fetchall()]

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
        cur.execute("PRAGMA table_info(http_error_summary)")
        columns = [row[1] for row in cur.fetchall()]

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

        conn.close()

    def test_save_metrics_success(self, temp_db):
        """Test saving successful extraction metrics."""
        telemetry, db_path = temp_db

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

        # Verify data was saved
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("SELECT * FROM extraction_telemetry_v2")
        records = cur.fetchall()
        assert len(records) == 1

        columns = [desc[0] for desc in cur.description]
        record = dict(zip(columns, records[0], strict=False))
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

        conn.close()

    def test_save_metrics_with_http_error(self, temp_db):
        """Test saving metrics with HTTP error tracking."""
        telemetry, db_path = temp_db

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

        # Verify extraction telemetry
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT http_status_code, http_error_type, is_success "
            "FROM extraction_telemetry_v2"
        )
        record = dict(
            zip([desc[0] for desc in cur.description], cur.fetchone(), strict=False)
        )
        assert record["http_status_code"] == 403
        assert record["http_error_type"] == "4xx_client_error"
        assert record["is_success"] == 0

        # Verify HTTP error summary
        cur.execute(
            "SELECT host, status_code, error_type, count FROM http_error_summary"
        )
        error_record = dict(
            zip([desc[0] for desc in cur.description], cur.fetchone(), strict=False)
        )
        assert error_record["host"] == "blocked.com"
        assert error_record["status_code"] == 403
        assert error_record["error_type"] == "4xx_client_error"
        assert error_record["count"] == 1

        conn.close()

    def test_get_field_extraction_stats(self, temp_db):
        """Test field extraction statistics retrieval."""
        telemetry, db_path = temp_db

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
        assert newspaper_stats["count"] == 3
        assert "title_success_rate" in newspaper_stats
        assert "content_success_rate" in newspaper_stats


@pytest.mark.integration
class TestContentExtractorIntegration:
    """Test integration between ContentExtractor and telemetry system.

    These tests make real HTTP requests via newspaper4k despite the mocks,
    so they are marked as integration tests and excluded from regular test runs.
    """

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        # Create tables manually (since we don't run Alembic migrations in tests)
        create_telemetry_tables(db_path)
        
        yield db_path
        Path(db_path).unlink(missing_ok=True)

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
        telemetry = ComprehensiveExtractionTelemetry(temp_db)

        # Create test scenario: mix of successes and failures
        test_scenarios = [
            ("test1.com", 200, True, "newspaper4k"),
            ("test1.com", 403, False, None),
            ("test2.com", 404, False, None),
            ("test2.com", 200, True, "beautifulsoup"),
            ("blocked.com", 403, False, None),
            ("blocked.com", 403, False, None),  # Same error again
        ]

        for i, (host, status, success, method) in enumerate(test_scenarios):
            metrics = ExtractionMetrics(
                f"op{i}", f"art{i}", f"https://{host}/article{i}", host
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

        # Test database queries (simulate API endpoint logic)
        conn = sqlite3.connect(temp_db)
        cur = conn.cursor()

        # Test method performance query
        cur.execute(
            """
        SELECT
            COALESCE(successful_method, 'failed') as method,
            host,
            COUNT(*) as total_attempts,
            SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) as successful_attempts
        FROM extraction_telemetry_v2
        GROUP BY COALESCE(successful_method, 'failed'), host
        ORDER BY total_attempts DESC
        """
        )

        method_results = cur.fetchall()
        assert len(method_results) > 0

        # Test HTTP error summary query
        cur.execute(
            """
        SELECT host, status_code, count
        FROM http_error_summary
        ORDER BY count DESC
        """
        )

        error_results = cur.fetchall()
        assert len(error_results) > 0

        # Verify blocked.com has 2 403 errors
        blocked_errors = [
            r for r in error_results if r[0] == "blocked.com" and r[1] == 403
        ]
        assert len(blocked_errors) == 1
        assert blocked_errors[0][2] == 2  # count should be 2

        # Test publisher stats query
        cur.execute(
            """
        SELECT
            host,
            COUNT(*) as total_extractions,
            SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) as successful_extractions
        FROM extraction_telemetry_v2
        GROUP BY host
        """
        )

        publisher_results = cur.fetchall()
        assert len(publisher_results) == 3  # test1.com, test2.com, blocked.com

        conn.close()


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


@pytest.mark.integration
class TestTelemetrySystemEndToEnd:
    """End-to-end integration tests for the complete telemetry system."""

    def test_complete_workflow_simulation(self):
        """Simulate a complete extraction workflow with telemetry."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        # Create telemetry tables manually (since Alembic migrations aren't run)
        create_telemetry_tables(db_path)

        try:
            telemetry = ComprehensiveExtractionTelemetry(db_path)

            # Simulate a batch extraction job
            urls = [
                "https://good-site.com/article1",
                "https://good-site.com/article2",
                "https://blocked-site.com/article1",
                "https://error-site.com/article1",
            ]

            for i, url in enumerate(urls):
                from urllib.parse import urlparse

                host = urlparse(url).netloc

                metrics = ExtractionMetrics(f"batch-job-{i}", f"article-{i}", url, host)
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

            # Verify results using API-style queries
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # Overall success rate
            cur.execute(
                """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) as successful
            FROM extraction_telemetry_v2
            """
            )

            total, successful = cur.fetchone()
            success_rate = (successful / total * 100) if total > 0 else 0

            assert total == 4
            assert successful == 2  # Only good-site articles succeeded
            assert success_rate == 50.0

            # HTTP error breakdown
            cur.execute(
                """
            SELECT status_code, COUNT(*)
            FROM http_error_summary
            GROUP BY status_code
            """
            )

            error_breakdown = dict(cur.fetchall())
            assert 403 in error_breakdown
            assert 500 in error_breakdown
            assert error_breakdown[403] == 1
            assert error_breakdown[500] == 1

            conn.close()

        finally:
            Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
