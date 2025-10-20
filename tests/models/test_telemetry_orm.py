"""Tests for telemetry ORM models."""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.models.telemetry_orm import (
    Base,
    BylineCleaningTelemetry,
    ExtractionTelemetryV2,
)


@pytest.fixture
def sqlite_engine(tmp_path):
    """Create a SQLite engine for testing."""
    db_path = tmp_path / "test_telemetry_orm.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(sqlite_engine):
    """Create a database session."""
    session = Session(sqlite_engine)
    yield session
    session.close()


class TestBylineCleaningTelemetryORM:
    """Test BylineCleaningTelemetry ORM model."""

    def test_create_and_query(self, db_session):
        """Test creating and querying a telemetry record."""
        telemetry = BylineCleaningTelemetry(
            id="test-123",
            article_id="article-456",
            candidate_link_id="cl-789",
            source_id="source-1",
            source_name="Test News",
            raw_byline="By John Doe, Test News",
            raw_byline_length=25,
            raw_byline_words=5,
            extraction_timestamp=datetime(2025, 10, 20, 12, 0, 0),
            cleaning_method="ml",
            final_authors_json='["John Doe"]',
            final_authors_count=1,
            confidence_score=0.92,
            has_wire_service=False,
            has_email=False,
            has_title=False,
            has_organization=False,
            source_name_removed=True,
            duplicates_removed_count=0,
            likely_valid_authors=True,
            likely_noise=False,
            created_at=datetime.utcnow(),
        )

        db_session.add(telemetry)
        db_session.commit()

        # Query back
        result = (
            db_session.query(BylineCleaningTelemetry).filter_by(id="test-123").first()
        )

        assert result is not None
        assert result.article_id == "article-456"
        assert result.raw_byline == "By John Doe, Test News"
        assert result.confidence_score == 0.92
        assert result.has_wire_service is False
        assert result.likely_valid_authors is True

    def test_all_columns_present(self, db_session):
        """Test that all expected columns are present."""
        # Create a minimal record with only required fields
        telemetry = BylineCleaningTelemetry(
            id="test-minimal",
            extraction_timestamp=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )

        db_session.add(telemetry)
        db_session.commit()

        result = (
            db_session.query(BylineCleaningTelemetry)
            .filter_by(id="test-minimal")
            .first()
        )

        # Verify all columns exist (nullable ones will be None)
        assert result is not None
        assert result.id == "test-minimal"
        assert result.article_id is None
        assert result.raw_byline is None
        assert result.confidence_score is None

    def test_human_review_columns(self, db_session):
        """Test human review columns that were missing in raw SQL."""
        telemetry = BylineCleaningTelemetry(
            id="test-review",
            extraction_timestamp=datetime.utcnow(),
            created_at=datetime.utcnow(),
            human_label="valid",
            human_notes="Good extraction",
            reviewed_by="reviewer@example.com",
            reviewed_at=datetime.utcnow(),
        )

        db_session.add(telemetry)
        db_session.commit()

        result = (
            db_session.query(BylineCleaningTelemetry)
            .filter_by(id="test-review")
            .first()
        )

        assert result.human_label == "valid"
        assert result.human_notes == "Good extraction"
        assert result.reviewed_by == "reviewer@example.com"
        assert result.reviewed_at is not None


class TestExtractionTelemetryV2ORM:
    """Test ExtractionTelemetryV2 ORM model."""

    def test_create_and_query(self, db_session):
        """Test creating and querying an extraction telemetry record."""
        now = datetime.utcnow()
        telemetry = ExtractionTelemetryV2(
            operation_id="op-123",
            article_id=456,
            url="https://example.com/article",
            outcome="success",
            extraction_time_ms=125.5,
            start_time=now,
            end_time=now,
            http_status_code=200,
            response_size_bytes=15000,
            has_title=True,
            has_content=True,
            has_author=True,
            has_publish_date=True,
            content_length=1200,
            title_length=50,
            author_count=1,
            content_quality_score=0.85,
            is_success=True,
            is_content_success=True,
            is_technical_failure=False,
            is_bot_protection=False,
            timestamp=now,
        )

        db_session.add(telemetry)
        db_session.commit()

        # Query back
        result = (
            db_session.query(ExtractionTelemetryV2)
            .filter_by(operation_id="op-123")
            .first()
        )

        assert result is not None
        assert result.article_id == 456
        assert result.outcome == "success"
        assert result.extraction_time_ms == 125.5
        assert result.http_status_code == 200
        assert result.is_success is True

    def test_error_tracking(self, db_session):
        """Test error tracking fields."""
        now = datetime.utcnow()
        telemetry = ExtractionTelemetryV2(
            operation_id="op-error",
            article_id=789,
            url="https://example.com/error",
            outcome="error",
            extraction_time_ms=50.0,
            start_time=now,
            end_time=now,
            error_message="Connection timeout",
            error_type="timeout",
            is_success=False,
            is_technical_failure=True,
        )

        db_session.add(telemetry)
        db_session.commit()

        result = (
            db_session.query(ExtractionTelemetryV2)
            .filter_by(operation_id="op-error")
            .first()
        )

        assert result.error_message == "Connection timeout"
        assert result.error_type == "timeout"
        assert result.is_technical_failure is True


class TestBulkInserts:
    """Test bulk insert operations for performance."""

    def test_bulk_insert_mappings(self, db_session, sqlite_engine):
        """Test bulk insert of multiple records."""
        records = [
            {
                "id": f"bulk-{i}",
                "raw_byline": f"By Author {i}",
                "extraction_timestamp": datetime.utcnow(),
                "confidence_score": 0.9 + (i * 0.01),
                "created_at": datetime.utcnow(),
            }
            for i in range(10)
        ]

        db_session.bulk_insert_mappings(BylineCleaningTelemetry, records)
        db_session.commit()

        # Query count
        count = db_session.query(BylineCleaningTelemetry).count()
        assert count == 10

        # Verify a sample record
        result = (
            db_session.query(BylineCleaningTelemetry).filter_by(id="bulk-5").first()
        )
        assert result.raw_byline == "By Author 5"
        assert result.confidence_score == pytest.approx(0.95)
