import os
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


@pytest.mark.postgres
@pytest.mark.integration
def test_record_extraction_emits_content_type_detection(cloud_sql_session):
    # Clean up any leftover test data before and after test
    from sqlalchemy import text
    import os
    
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
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/mizzou_test"
        )
    )
    telemetry_store = TelemetryStore(database=db_url, async_writes=False)
    
    # Clean up any previous test data
    with telemetry_store.connection() as conn:
        conn.execute(
            "DELETE FROM content_type_detection_telemetry "
            "WHERE article_id LIKE 'article-agg-%'"
        )
        conn.execute(
            "DELETE FROM http_error_summary WHERE host LIKE '%.example'"
        )
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

    filtered_field_stats = telemetry.get_field_extraction_stats(
        publisher="Publisher A",
        method="primary",
    )
    assert len(filtered_field_stats) == 1
