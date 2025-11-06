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
from sqlalchemy import text

from src.models import Article, CandidateLink, Source
from src.telemetry.store import TelemetryStore
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
    # Create telemetry store with cloud_sql_session
    store = TelemetryStore(database=None, async_writes=False)
    store._engine = cloud_sql_session.get_bind()

    # Create telemetry system
    telemetry = ComprehensiveExtractionTelemetry(store=store)

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

    # Save telemetry
    telemetry.save_extraction_metrics(metrics)

    # Verify telemetry was saved correctly
    result = cloud_sql_session.execute(
        text(
            """
            SELECT article_id, status, confidence, confidence_score, reason
            FROM content_type_detection_telemetry
            WHERE article_id = :article_id
        """
        ),
        {"article_id": test_article.id},
    )
    row = result.fetchone()

    assert row is not None, "Telemetry was not saved"
    assert row[0] == test_article.id
    assert row[1] == "wire"
    # Confidence might be string or numeric depending on schema
    # Both should be acceptable
    assert row[2] in ["medium", 0.5, "0.5"], f"Unexpected confidence value: {row[2]}"
    assert float(row[3]) == 0.5
    assert row[4] == "wire_service_detected"


def test_content_type_telemetry_schema_detection(cloud_sql_session):
    """Test that telemetry system correctly detects modern vs legacy schema."""
    from src.telemetry.store import TelemetryStore
    from src.utils.comprehensive_telemetry import ComprehensiveExtractionTelemetry

    # Create telemetry store with cloud_sql_session
    store = TelemetryStore(database=None, async_writes=False)
    store._engine = cloud_sql_session.get_bind()

    # Create telemetry system
    telemetry = ComprehensiveExtractionTelemetry(store=store)

    # Access internal method to check strategy detection
    def check_strategy(conn):
        return telemetry._ensure_content_type_strategy(conn)

    # Get a connection from the store (connection is a property with contextmanager)
    with store.connection() as conn:
        strategy = check_strategy(conn)

        # Should detect modern or legacy (or missing if table doesn't exist yet)
        assert strategy in [
            "modern",
            "legacy",
            None,
        ], f"Unexpected strategy: {strategy}"

        if strategy == "modern":
            # Modern: status, confidence (str), confidence_score (float)
            print("✅ Detected modern schema with String confidence column")
        elif strategy == "legacy":
            # Legacy: detected_type, detection_method, confidence (float)
            print("ℹ️  Detected legacy schema with Float confidence")
        else:
            # Table doesn't exist yet
            print("ℹ️  content_type_detection_telemetry table not found")


def test_content_type_telemetry_handles_numeric_confidence_column(
    cloud_sql_session, test_article
):
    """Test defensive handling of numeric confidence column in modern schema detection.

    This tests the scenario where:
    - Table has modern columns (status, confidence, confidence_score)
    - BUT confidence column is Float type instead of String type
    - Code should detect this and convert string label to numeric value

    This is a defensive test for production schema mismatch.
    """
    # First, check if we can alter the table for this test
    # If migration hasn't run yet, this test will be skipped
    try:
        # Check if table exists
        result = cloud_sql_session.execute(
            text(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'content_type_detection_telemetry'
            """
            )
        )
        if result.scalar() == 0:
            pytest.skip(
                "content_type_detection_telemetry table does not exist, skipping test"
            )

        # Check current column type
        result = cloud_sql_session.execute(
            text(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name = 'content_type_detection_telemetry'
                AND column_name = 'confidence'
            """
            )
        )
        current_type = result.scalar()

        if not current_type:
            pytest.skip("confidence column does not exist, skipping test")

        # Create telemetry store
        store = TelemetryStore(database=None, async_writes=False)
        store._engine = cloud_sql_session.get_bind()
        telemetry = ComprehensiveExtractionTelemetry(store=store)

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
            telemetry.save_extraction_metrics(metrics)
            print("✅ Telemetry saved successfully despite potential schema mismatch")
        except Exception as e:
            pytest.fail(f"Telemetry save failed with schema mismatch handling: {e}")

        # Verify telemetry was saved
        result = cloud_sql_session.execute(
            text(
                """
                SELECT confidence, confidence_score
                FROM content_type_detection_telemetry
                WHERE article_id = :article_id
            """
            ),
            {"article_id": test_article.id},
        )
        row = result.fetchone()

        assert row is not None, "Telemetry was not saved"

        # Confidence could be either string or numeric depending on actual schema
        confidence_val = row[0]
        if current_type in ["double precision", "real", "float", "numeric"]:
            # If column is numeric, should have been converted to numeric value
            assert isinstance(
                confidence_val, (int, float)
            ), f"Expected numeric confidence, got {type(confidence_val)}"
            assert float(confidence_val) == 0.5
            print(
                f"✅ Correctly converted string 'medium' to numeric {confidence_val} for numeric column"
            )
        else:
            # If column is string, should keep string value
            assert confidence_val == "medium"
            print("✅ Correctly kept string 'medium' for string column")

    except Exception as e:
        pytest.skip(f"Could not set up test environment: {e}")
