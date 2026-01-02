import os
from datetime import datetime

import pytest

from src.telemetry.store import TelemetryStore
from src.utils import comprehensive_telemetry as ct


def test_extraction_metrics_tracks_methods(monkeypatch):
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="article-7",
        url="https://example.com/story",
        publisher="Example News",
    )

    times = [100.0, 100.2]

    def fake_time():
        return times.pop(0)

    monkeypatch.setattr(ct.time, "time", fake_time)

    metrics.start_method("primary")
    metrics.end_method(
        "primary",
        True,
        extracted_fields={
            "title": "Headline",
            "content": "Body",
            "metadata": {"http_status": 404},
        },
    )

    metrics.record_alternative_extraction(
        "fallback",
        "title",
        alternative_value="Alt Headline",
        current_value="Headline",
    )

    metrics.set_http_metrics(404, response_size=512, response_time_ms=120.5)

    metrics.finalize(
        {
            "title": "Headline",
            "content": "Body",
            "metadata": {"extraction_methods": {"title": "primary"}},
        }
    )

    assert metrics.method_success["primary"] is True
    assert metrics.field_extraction["primary"]["title"] is True
    assert metrics.http_error_type == "4xx_client_error"
    assert metrics.alternative_extractions["fallback"]["title"]["values_differ"] is True
    assert metrics.final_field_attribution["title"] == "primary"
    assert metrics.is_success is True
    assert metrics.content_length == len("Body")
    assert metrics.field_extraction["primary"]["metadata"] is True


def test_set_driver_metrics_sanitizes_payload():
    metrics = ct.ExtractionMetrics(
        operation_id="op-driver",
        article_id="article-driver",
        url="https://example.com/story",
        publisher="Example News",
    )

    captured = datetime(2026, 1, 1, 3, 4, 5)
    payload = {
        "captured_at": captured,
        "driver": {"driver_reuse_count": 2, "driver_reuse_limit": 5},
    }

    metrics.set_driver_metrics(payload)

    assert metrics.driver_metrics["captured_at"] == str(captured)
    assert metrics.driver_metrics["driver"]["driver_reuse_count"] == 2


def test_set_driver_metrics_handles_unserializable_payload():
    metrics = ct.ExtractionMetrics(
        operation_id="op-driver-raw",
        article_id="article-driver-raw",
        url="https://example.com/story",
        publisher="Example News",
    )

    class CustomObject:
        pass

    metrics.set_driver_metrics({"unexpected": CustomObject()})

    assert "raw" in metrics.driver_metrics
    assert "unexpected" in metrics.driver_metrics["raw"]


@pytest.mark.postgres
@pytest.mark.integration
def test_record_extraction_emits_content_type_detection(cloud_sql_session):
    # Clean up any leftover test data before and after test
    import os

    from sqlalchemy import text

    def cleanup():
        try:
            cloud_sql_session.execute(
                text(
                    "DELETE FROM content_type_detection_telemetry "
                    "WHERE article_id = 'article-detect'"
                )
            )
            cloud_sql_session.commit()
        except Exception:
            cloud_sql_session.rollback()

    cleanup()  # Clean before test

    # Get TEST_DATABASE_URL (SQLAlchemy masks password in str(url))
    db_url = os.getenv("TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TEST_DATABASE_URL not set")

    telemetry_store = TelemetryStore(database=db_url, async_writes=False)
    telemetry = ct.ComprehensiveExtractionTelemetry(store=telemetry_store)

    metrics = ct.ExtractionMetrics(
        operation_id="op-detect",
        article_id="article-detect",
        url="https://example.com/opinion/piece",
        publisher="Example",
    )

    detection_payload = {
        "status": "opinion",
        "confidence": "high",
        "confidence_score": 0.83,
        "reason": "matched_opinion_signals",
        "evidence": {"title": ["opinion"]},
        "version": "test-version",
        "detected_at": "2025-09-26T12:00:00",
    }

    metrics.set_content_type_detection(detection_payload)
    metrics.finalize({"title": "Opinion: View", "content": "Body"})

    telemetry.record_extraction(metrics)

    detections = telemetry.get_content_type_detections(statuses=["opinion"])

    try:
        assert len(detections) == 1
        detection = detections[0]
        assert detection["status"] == "opinion"
        # confidence column stores the string label ("high", "medium", "low")
        assert detection["confidence"] == "high"
        assert detection["confidence_score"] == 0.83
        assert detection["evidence"]["title"] == ["opinion"]
    finally:
        cleanup()  # Clean after test


def test_set_http_metrics_categorizes_errors():
    metrics = ct.ExtractionMetrics(
        operation_id="op-2",
        article_id="article-9",
        url="https://example.com/alt",
        publisher="Example",
    )

    metrics.set_http_metrics(503, response_size=0, response_time_ms=50.0)
    assert metrics.http_error_type == "5xx_server_error"

    metrics.set_http_metrics(302, response_size=0, response_time_ms=10.0)
    assert metrics.http_error_type == "3xx_redirect"

    metrics.set_http_metrics(200, response_size=0, response_time_ms=5.0)
    assert metrics.http_error_type == "3xx_redirect"


@pytest.mark.postgres
@pytest.mark.integration
def test_comprehensive_telemetry_aggregates():
    """Test comprehensive telemetry aggregation with PostgreSQL.

    Note: This test doesn't use cloud_sql_session to avoid connection pool conflicts.
    TelemetryStore needs its own isolated connection for async telemetry writes.
    """
    # Use PostgreSQL test database from environment (respects CI configuration)
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mizzou_test"
        ),
    )
    telemetry_store = TelemetryStore(database=db_url, async_writes=False)

    # Clean up any previous test data
    with telemetry_store.connection() as conn:
        conn.execute(
            "DELETE FROM content_type_detection_telemetry "
            "WHERE article_id LIKE 'article-agg-%'"
        )
        conn.execute("DELETE FROM http_error_summary WHERE host LIKE '%.example'")
        conn.execute(
            "DELETE FROM extraction_telemetry_v2 "
            "WHERE article_id LIKE 'article-agg-%'"
        )
        conn.commit()

    telemetry = ct.ComprehensiveExtractionTelemetry(store=telemetry_store)

    metrics_primary = ct.ExtractionMetrics(
        operation_id="agg-1",
        article_id="article-agg-1",
        url="https://publisher-a.example/story",
        publisher="Publisher A",
    )
    metrics_primary.start_method("primary")
    metrics_primary.end_method(
        "primary",
        success=True,
        extracted_fields={
            "title": "Headline",
            "author": "Reporter",
            "content": "Body",
            "publish_date": "2025-09-26",
            "metadata": {"http_status": 502},
        },
    )
    metrics_primary.start_method("fallback")
    metrics_primary.end_method(
        "fallback",
        success=False,
        error="timeout",
        extracted_fields={
            "title": "",
            "content": "",
            "metadata": {},
        },
    )
    metrics_primary.method_timings["primary"] = 50.0
    metrics_primary.method_timings["fallback"] = 80.0
    metrics_primary.set_http_metrics(
        502,
        response_size=2048,
        response_time_ms=140.0,
    )
    metrics_primary.error_message = "server error"
    metrics_primary.error_type = "http"
    metrics_primary.set_content_type_detection(
        {
            "status": "news",
            "confidence": "high",
            "reason": "matched",
            "evidence": {"signals": ["news"]},
            "version": "v1",
            "confidence_score": 0.91,
        }
    )
    metrics_primary.finalize(
        {
            "title": "Headline",
            "content": "Body",
            "metadata": {
                "extraction_methods": {
                    "title": "primary",
                    "content": "primary",
                }
            },
        }
    )

    metrics_secondary = ct.ExtractionMetrics(
        operation_id="agg-2",
        article_id="article-agg-2",
        url="https://publisher-b.example/feature",
        publisher="Publisher B",
    )
    metrics_secondary.start_method("primary")
    metrics_secondary.end_method(
        "primary",
        success=True,
        extracted_fields={
            "title": "Feature",
            "author": "Columnist",
            "content": "Body",
            "publish_date": "2025-09-27",
        },
    )
    metrics_secondary.method_timings["primary"] = 30.0
    metrics_secondary.set_http_metrics(
        200,
        response_size=1024,
        response_time_ms=95.0,
    )
    metrics_secondary.finalize(
        {
            "title": "Feature",
            "content": "Body",
            "metadata": {
                "extraction_methods": {
                    "title": "primary",
                    "content": "primary",
                }
            },
        }
    )

    telemetry.record_extraction(metrics_primary)
    telemetry.record_extraction(metrics_secondary)

    summary = telemetry.get_error_summary(days=30)
    assert any(item["status_code"] == 502 for item in summary)

    detections = telemetry.get_content_type_detections(
        statuses=["news"],
        days=30,
    )
    assert len(detections) == 1
    assert detections[0]["status"] == "news"
    # Evidence is stored as JSON, not malformed string
    assert detections[0]["evidence"] == {"signals": ["news"]}

    method_stats = telemetry.get_method_effectiveness()
    primary_stats = next(
        item for item in method_stats if item["method_type"] == "primary"
    )
    assert primary_stats["count"] == 2
    assert 0 < primary_stats["avg_duration"] < 60
    assert primary_stats["success_rate"] > 0.5

    filtered_methods = telemetry.get_method_effectiveness(publisher="Publisher A")
    assert len(filtered_methods) == 2

    publisher_stats = telemetry.get_publisher_stats()
    assert {item["publisher"] for item in publisher_stats} >= {
        "Publisher A",
        "Publisher B",
    }

    field_stats = telemetry.get_field_extraction_stats()
    primary_field = next(item for item in field_stats if item["method"] == "primary")
    assert primary_field["title_success_rate"] > 0
    assert "metadata_success_rate" in primary_field

    filtered_field_stats = telemetry.get_field_extraction_stats(
        publisher="Publisher A",
        method="primary",
    )
    assert len(filtered_field_stats) == 1


# ===== Additional Coverage Tests =====


def test_proxy_status_to_int():
    """Test proxy status conversion to integer."""
    assert ct.proxy_status_to_int("disabled") == ct.PROXY_STATUS_DISABLED
    assert ct.proxy_status_to_int("success") == ct.PROXY_STATUS_SUCCESS
    assert ct.proxy_status_to_int("failed") == ct.PROXY_STATUS_FAILED
    assert ct.proxy_status_to_int("bypassed") == ct.PROXY_STATUS_BYPASSED
    assert (
        ct.proxy_status_to_int("DISABLED") == ct.PROXY_STATUS_DISABLED
    )  # Case insensitive
    assert ct.proxy_status_to_int("unknown") is None  # Unknown status
    assert ct.proxy_status_to_int(None) is None  # None input


def test_extraction_metrics_initialization():
    """Test ExtractionMetrics initialization."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-123",
        article_id="art-456",
        url="https://news.example.com/story/123",
        publisher="Example Publisher",
    )

    assert metrics.operation_id == "op-123"
    assert metrics.article_id == "art-456"
    assert metrics.url == "https://news.example.com/story/123"
    assert metrics.publisher == "Example Publisher"
    assert metrics.host == "news.example.com"
    assert isinstance(metrics.start_time, datetime)
    assert metrics.end_time is None
    assert metrics.total_duration_ms == 0.0
    assert metrics.http_status_code is None
    assert metrics.methods_attempted == []
    assert metrics.is_success is False


def test_extraction_metrics_proxy_metrics():
    """Test proxy metrics tracking."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    # Test setting proxy metrics
    metrics.set_proxy_metrics(
        proxy_used=True,
        proxy_url="http://proxy.example.com:8080",
        proxy_authenticated=True,
        proxy_status="success",
        proxy_error=None,
    )

    assert metrics.proxy_used is True
    assert metrics.proxy_url == "http://proxy.example.com:8080"
    assert metrics.proxy_authenticated is True
    assert metrics.proxy_status == ct.PROXY_STATUS_SUCCESS
    assert metrics.proxy_error is None

    # Test with error
    metrics.set_proxy_metrics(
        proxy_used=True,
        proxy_url="http://proxy.example.com:8080",
        proxy_authenticated=False,
        proxy_status="failed",
        # Create a long error message to test truncation (500 char limit in production)
        proxy_error="Connection timeout" * 50,
    )

    assert metrics.proxy_status == ct.PROXY_STATUS_FAILED
    assert len(metrics.proxy_error) <= 500  # Truncated


def test_extraction_metrics_end_method_without_start():
    """Test ending a method without starting it."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    # End method without starting - should not crash
    metrics.end_method("never_started", success=False, error="Not found")

    assert metrics.method_success["never_started"] is False
    assert metrics.method_errors["never_started"] == "Not found"
    assert "never_started" not in metrics.method_timings  # No timing recorded


def test_extraction_metrics_successful_method_tracking():
    """Test that successful_method is set only once."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    metrics.end_method("method1", success=True)
    assert metrics.successful_method == "method1"

    # Second successful method should not override
    metrics.end_method("method2", success=True)
    assert metrics.successful_method == "method1"  # Still the first one


def test_extraction_metrics_metadata_proxy_extraction():
    """Test extracting proxy info from metadata."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    # Proxy info in metadata should be captured
    metrics.end_method(
        "method1",
        success=True,
        extracted_fields={
            "title": "Test",
            "metadata": {
                "proxy_used": True,
                "proxy_url": "http://proxy.test:8080",
                "proxy_authenticated": True,
                "proxy_status": "success",
                "proxy_error": None,
            },
        },
    )

    assert metrics.proxy_used is True
    assert metrics.proxy_url == "http://proxy.test:8080"
    assert metrics.proxy_authenticated is True
    assert metrics.proxy_status == ct.PROXY_STATUS_SUCCESS
    assert metrics.field_extraction["method1"]["metadata"] is True


def test_extraction_metrics_finalize_empty_result():
    """Test finalizing with empty result."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    metrics.finalize({})

    assert metrics.end_time is not None
    assert metrics.total_duration_ms > 0
    assert metrics.extracted_fields["title"] is False
    assert metrics.extracted_fields["content"] is False
    assert metrics.is_success is False
    assert metrics.extracted_fields["metadata"] is False


def test_extraction_metrics_finalize_with_content():
    """Test finalizing with actual content."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    content = "This is the article content." * 10
    metrics.finalize(
        {
            "title": "Article Title",
            "content": content,
            "author": "John Doe",
            "publish_date": "2025-01-01",
            "metadata": {
                "extraction_methods": {
                    "title": "newspaper",
                    "content": "newspaper",
                    "author": "custom",
                }
            },
        }
    )

    assert metrics.is_success is True
    assert metrics.content_length == len(content)
    assert metrics.extracted_fields["title"] is True
    assert metrics.extracted_fields["content"] is True
    assert metrics.extracted_fields["author"] is True
    assert metrics.extracted_fields["publish_date"] is True
    assert metrics.final_field_attribution["title"] == "newspaper"
    assert metrics.final_field_attribution["author"] == "custom"
    assert metrics.extracted_fields["metadata"] is True


def test_extraction_metrics_record_alternative_extraction():
    """Test recording alternative extractions."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    # Record alternative extraction with long values to test 200-char truncation limit
    long_value = "A" * 300  # Exceeds the 200 character limit
    metrics.record_alternative_extraction(
        method_name="fallback",
        field_name="title",
        alternative_value=long_value,
        current_value="Original Title",
    )

    assert "fallback" in metrics.alternative_extractions
    assert "title" in metrics.alternative_extractions["fallback"]
    alt_data = metrics.alternative_extractions["fallback"]["title"]
    assert alt_data["values_differ"] is True
    # Production code truncates alternative/current values to 200 chars (line 173-174 in comprehensive_telemetry.py)
    assert len(alt_data["alternative_value"]) == 200
    assert len(alt_data["current_value"]) <= 200


def test_extraction_metrics_content_type_detection():
    """Test setting content type detection."""
    metrics = ct.ExtractionMetrics(
        operation_id="op-1",
        article_id="art-1",
        url="https://example.com/test",
        publisher="Test",
    )

    detection = {
        "status": "news",
        "confidence": "high",
        "confidence_score": 0.95,
        "reason": "matched_signals",
        "evidence": {"signals": ["news", "article"]},
        "version": "v1.0",
    }

    metrics.set_content_type_detection(detection)
    assert metrics.content_type_detection == detection


def test_comprehensive_telemetry_init_with_db_path(tmp_path):
    """Test initializing telemetry with a database path."""
    db_path = tmp_path / "telemetry.db"

    telemetry = ct.ComprehensiveExtractionTelemetry(db_path=str(db_path))

    assert telemetry._database_url.startswith("sqlite:///")
    assert db_path.parent.exists()  # Directory should be created


def test_comprehensive_telemetry_resolve_numeric_confidence():
    """Test _resolve_numeric_confidence static method."""
    # Test numeric score
    assert (
        ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence(
            {"confidence_score": 0.85}
        )
        == 0.85
    )

    # Test confidence label
    assert (
        ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence(
            {"confidence": "very_high"}
        )
        == 0.95
    )

    assert (
        ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence(
            {"confidence": "high"}
        )
        == 0.85
    )

    assert (
        ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence(
            {"confidence": "medium"}
        )
        == 0.5
    )

    assert (
        ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence(
            {"confidence": "low"}
        )
        == 0.25
    )

    # Test unknown label
    assert (
        ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence(
            {"confidence": "unknown"}
        )
        is None
    )

    # Test invalid types
    assert (
        ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence(
            {"confidence_score": "not_a_number"}
        )
        is None
    )


@pytest.mark.postgres
@pytest.mark.integration
def test_get_driver_metrics_summary():
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/mizzou_test",
        ),
    )
    if not db_url:
        pytest.skip("TEST_DATABASE_URL not set")

    telemetry_store = TelemetryStore(database=db_url, async_writes=False)

    def cleanup():
        with telemetry_store.connection() as conn:
            conn.execute(
                "DELETE FROM extraction_telemetry_v2 WHERE article_id LIKE 'article-driver-%'"
            )
            conn.commit()

    try:
        cleanup()
    except Exception as exc:  # pragma: no cover - depends on local DB availability
        pytest.skip(f"PostgreSQL telemetry store unavailable: {exc}")
    telemetry = ct.ComprehensiveExtractionTelemetry(store=telemetry_store)

    def _insert_sample(article_id: str, reuse: int, limit: int, failures: int):
        metrics = ct.ExtractionMetrics(
            operation_id=f"op-{article_id}",
            article_id=article_id,
            url=f"https://example.com/{article_id}",
            publisher="Example",
        )
        metrics.set_driver_metrics(
            {
                "captured_at": "2026-01-01T00:00:00",
                "driver": {
                    "driver_reuse_count": reuse,
                    "driver_reuse_limit": limit,
                    "driver_method": "undetected-chromedriver",
                },
                "proxy": {"active_provider": "squid"},
                "domain": {
                    "name": "example.com",
                    "selenium_failures": failures,
                    "captcha_backoff_active": failures > 0,
                },
            }
        )
        metrics.finalize({"title": "Story", "content": "body"})
        telemetry.record_extraction(metrics)

    try:
        _insert_sample("article-driver-1", reuse=2, limit=5, failures=0)
        _insert_sample("article-driver-2", reuse=6, limit=6, failures=2)

        summary = telemetry.get_driver_metrics_summary(hours=None)

        assert summary["sample_count"] == 2
        # Average reuse should reflect (2 + 6) / 2 = 4
        assert summary["avg_reuse_count"] == 4
        assert summary["max_reuse_count"] == 6
        assert summary["reuse_limit_hits"] == 1
        assert summary["captcha_backoff_events"] == 1

        providers = {
            entry["provider"]: entry["samples"]
            for entry in summary["proxy_provider_breakdown"]
        }
        assert providers["squid"] == 2

        methods = {
            entry["method"]: entry["samples"]
            for entry in summary["driver_method_breakdown"]
        }
        assert methods["undetected-chromedriver"] == 2

        top_domains = summary["top_domains_by_selenium_failures"]
        assert top_domains[0]["domain"] == "example.com"
        assert top_domains[0]["selenium_failures"] == 2

        assert (
            ct.ComprehensiveExtractionTelemetry._resolve_numeric_confidence({}) is None
        )
    finally:
        try:
            cleanup()
        except Exception:
            pass


def test_comprehensive_telemetry_coerce_detected_at():
    """Test _coerce_detected_at static method."""
    # Test datetime object
    dt = datetime(2025, 1, 1, 12, 0, 0)
    assert ct.ComprehensiveExtractionTelemetry._coerce_detected_at(dt) == dt

    # Test ISO format string
    result = ct.ComprehensiveExtractionTelemetry._coerce_detected_at(
        "2025-01-01T12:00:00"
    )
    assert isinstance(result, datetime)
    assert result.year == 2025

    # Test ISO format with Z suffix
    result = ct.ComprehensiveExtractionTelemetry._coerce_detected_at(
        "2025-01-01T12:00:00Z"
    )
    assert isinstance(result, datetime)

    # Test invalid string
    assert ct.ComprehensiveExtractionTelemetry._coerce_detected_at("not-a-date") is None

    # Test empty string
    assert ct.ComprehensiveExtractionTelemetry._coerce_detected_at("") is None

    # Test None
    assert ct.ComprehensiveExtractionTelemetry._coerce_detected_at(None) is None

    # Test other types
    assert ct.ComprehensiveExtractionTelemetry._coerce_detected_at(12345) is None
