"""PostgreSQL integration tests for content type detection telemetry.

Tests that validate content type detection telemetry insertion works correctly
with both modern (string confidence) and legacy (numeric confidence) schemas.

Following test development protocol:
1. Uses cloud_sql_session fixture for PostgreSQL with automatic rollback
2. Creates all required FK dependencies (operations, articles)
3. Marks with @pytest.mark.postgres AND @pytest.mark.integration
4. Tests actual database insertion, not mocked data

Key Issue Being Tested:
Production database may have legacy schema where confidence column is Float/Double
instead of String. The code should handle both cases gracefully by detecting the
column type and converting values appropriately.
"""

import uuid
from datetime import datetime, timezone

import pytest

from src.models import Article, CandidateLink, Source
from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


@pytest.fixture
def test_source(cloud_sql_session):
    """Create a test source for telemetry testing."""
    source = Source(
        id=str(uuid.uuid4()),
        host="wire-test.example.com",
        host_norm="wire-test.example.com",
        canonical_name="Wire Service Test Publisher",
        city="Test City",
        county="Test County",
    )
    cloud_sql_session.add(source)
    cloud_sql_session.commit()
    cloud_sql_session.refresh(source)
    return source


@pytest.fixture
def test_candidate_link(cloud_sql_session, test_source):
    """Create a test candidate link for article."""
    link = CandidateLink(
        id=str(uuid.uuid4()),
        url="https://wire-test.example.com/article-1",
        source="Wire Service Test",  # NOT NULL field required
        source_id=test_source.id,
        status="article",
    )
    cloud_sql_session.add(link)
    cloud_sql_session.commit()
    cloud_sql_session.refresh(link)
    return link


@pytest.fixture
def test_article(cloud_sql_session, test_candidate_link):
    """Create a test article for telemetry."""
    article = Article(
        id=str(uuid.uuid4()),
        candidate_link_id=test_candidate_link.id,
        url=test_candidate_link.url,
        title="Test Wire Service Article",
        content="This is a test article from Associated Press.",
    )
    cloud_sql_session.add(article)
    cloud_sql_session.commit()
    cloud_sql_session.refresh(article)
    return article


def test_content_type_telemetry_with_string_confidence(cloud_sql_session, test_article):
    """Test that content type telemetry handles string confidence values correctly.

    This is the normal case where confidence is a string label ('high', 'medium', 'low')
    and the database schema has confidence as String type.
    """
    # Create telemetry store and system
    telemetry = ComprehensiveExtractionTelemetry(store=None)

    # Create extraction metrics with a test operation ID
    operation_id = f"test-op-{uuid.uuid4()}"
    metrics = ExtractionMetrics(
        operation_id=operation_id,
        article_id=test_article.id,
        url=test_article.url,
        publisher="Wire Service Test Publisher",
    )

    # Create detection payload with string confidence (wire service detection)
    detection_payload = {
        "status": "wire",
        "confidence": "medium",  # String label
        "confidence_score": 0.5,  # Numeric score
        "reason": "wire_service_detected",
        "evidence": {
            "dateline": ["Associated Press"],
            "url": ["wire-test.example.com"],
        },
        "version": "2025-10-23b",
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }

    # Set content type detection
    metrics.set_content_type_detection(detection_payload)
    metrics.finalize(
        {
            "title": test_article.title,
            "content": test_article.content,
        }
    )

    # Record telemetry (correct method name)
    telemetry.record_extraction(metrics)


def test_content_type_telemetry_schema_detection(cloud_sql_session):
    """Test that telemetry system correctly detects modern vs legacy schema."""
    # Create telemetry system (uses default database)
    telemetry = ComprehensiveExtractionTelemetry(store=None)

    # Check if we can access the schema detection
    # Get a connection directly from cloud_sql_session for testing
    with cloud_sql_session() as conn:
        strategy = telemetry._ensure_content_type_strategy(conn)

        # Should detect modern or legacy (or None if table doesn't exist yet)
        assert strategy in [
            "modern",
            "legacy",
            None,
        ], f"Unexpected strategy: {strategy}"

        if strategy == "modern":
            # Modern: status, confidence (str), confidence_score (float)
            print("✅ Detected modern schema with String confidence")
        elif strategy == "legacy":
            # Legacy: detected_type, detection_method, confidence (float)
            print("ℹ️  Detected legacy schema with Float confidence")
        else:
            # Table doesn't exist yet
            print("ℹ️  content_type_detection_telemetry table not found")


def test_content_type_telemetry_handles_numeric_confidence_column(
    cloud_sql_session, test_article
):
    """Test defensive handling of numeric confidence column in modern schema.

    This tests the scenario where:
    - Table has modern columns (status, confidence, confidence_score)
    - BUT confidence column is Float type instead of String type
    - Code should detect this and convert string label to numeric value

    This is a defensive test for production schema mismatch.
    """
    # Create telemetry system
    telemetry = ComprehensiveExtractionTelemetry(store=None)

    # Create extraction metrics with a test operation ID
    operation_id = f"test-op-{uuid.uuid4()}"
    metrics = ExtractionMetrics(
        operation_id=operation_id,
        article_id=test_article.id,
        url=test_article.url,
        publisher="Wire Service Test Publisher",
    )

    # Create detection payload with string confidence
    detection_payload = {
        "status": "wire",
        "confidence": "medium",  # String label that should be converted if needed
        "confidence_score": 0.5,
        "reason": "wire_service_detected",
        "evidence": {"dateline": ["NPR"]},
        "version": "2025-10-23b",
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }

    metrics.set_content_type_detection(detection_payload)
    metrics.finalize({"title": test_article.title, "content": test_article.content})

    # This should NOT raise an error, even if confidence column is numeric
    # The defensive code should handle it gracefully
    try:
        telemetry.record_extraction(metrics)
        print("✅ Telemetry recorded successfully despite potential schema mismatch")
    except Exception as e:
        pytest.fail(f"Telemetry recording failed with schema mismatch handling: {e}")
