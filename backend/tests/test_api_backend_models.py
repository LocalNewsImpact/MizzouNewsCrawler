"""Test suite for API backend model serialization (to_dict methods).

Tests the model serialization for PR #33 for Cloud SQL migration.
All models now have to_dict() methods for clean JSON API responses.
"""

import sys
from datetime import datetime
from pathlib import Path


# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.models.api_backend import (  # noqa: E402
    BylineCleaningTelemetry,
    BylineTransformationStep,
    Candidate,
    CodeReviewTelemetry,
    DedupeAudit,
    DomainFeedback,
    ReextractionJob,
    Review,
    Snapshot,
)


class TestReviewSerialization:
    """Test Review model to_dict() serialization."""

    def test_review_to_dict_all_fields(self):
        """Test Review serialization with all fields populated."""
        now = datetime(2025, 10, 4, 12, 30, 0)
        review = Review(
            id="test-123",
            article_idx=42,
            article_uid="uid-789",
            reviewer="test_user",
            rating=5,
            secondary_rating=4,
            tags='["politics", "local"]',
            notes="Great article",
            mentioned_locations='["Columbia, MO"]',
            missing_locations='["Jefferson City"]',
            incorrect_locations="[]",
            inferred_tags='["government"]',
            missing_tags='["election"]',
            incorrect_tags="[]",
            body_errors="[]",
            headline_errors='["Missing location"]',
            author_errors="[]",
            created_at=now,
            reviewed_at=now,
        )

        result = review.to_dict()

        assert result["id"] == "test-123"
        assert result["article_idx"] == 42
        assert result["article_uid"] == "uid-789"
        assert result["reviewer"] == "test_user"
        assert result["rating"] == 5
        assert result["secondary_rating"] == 4
        assert result["tags"] == '["politics", "local"]'
        assert result["notes"] == "Great article"
        assert result["created_at"] == "2025-10-04T12:30:00"
        assert result["reviewed_at"] == "2025-10-04T12:30:00"

    def test_review_to_dict_minimal_fields(self):
        """Test Review serialization with minimal required fields."""
        review = Review(
            id="test-456",
            reviewer="minimal_user",
        )

        result = review.to_dict()

        assert result["id"] == "test-456"
        assert result["reviewer"] == "minimal_user"
        assert result["article_idx"] is None
        assert result["rating"] is None
        assert result["reviewed_at"] is None
        # created_at has a default, should be present
        assert "created_at" in result

    def test_review_to_dict_handles_none_datetime(self):
        """Test that None datetime fields are handled correctly."""
        review = Review(id="test-789", reviewer="user", reviewed_at=None)

        result = review.to_dict()

        assert result["reviewed_at"] is None


class TestDomainFeedbackSerialization:
    """Test DomainFeedback model to_dict() serialization."""

    def test_domain_feedback_to_dict(self):
        """Test DomainFeedback serialization."""
        now = datetime(2025, 10, 4, 14, 0, 0)
        feedback = DomainFeedback(
            host="example.com",
            notes="Hard paywall detected",
        )
        feedback.updated_at = now

        result = feedback.to_dict()

        assert result["host"] == "example.com"
        assert result["notes"] == "Hard paywall detected"
        assert result["updated_at"] == now.isoformat()


class TestSnapshotSerialization:
    """Test Snapshot model to_dict() serialization."""

    def test_snapshot_to_dict_complete(self):
        """Test Snapshot serialization with all fields."""
        now = datetime(2025, 10, 4, 15, 0, 0)
        snapshot = Snapshot(
            url="https://example.com/article",
            host="example.com",
            path="/tmp/snap-123.html",
            pipeline_run_id="run-456",
            parsed_fields='{"headline": "Test"}',
            model_confidence=0.87,
            failure_reason=None,
            status="pending",
        )
        snapshot.id = "snap-123"
        snapshot.created_at = now

        result = snapshot.to_dict()

        assert result["id"] == "snap-123"
        assert result["url"] == "https://example.com/article"
        assert result["host"] == "example.com"
        assert result["pipeline_run_id"] == "run-456"
        assert result["model_confidence"] == 0.87
        assert result["status"] == "pending"
        assert result["created_at"] == now.isoformat()


class TestCandidateSerialization:
    """Test Candidate model to_dict() serialization."""

    def test_candidate_to_dict(self):
        """Test Candidate serialization."""
        now = datetime(2025, 10, 4, 16, 0, 0)
        candidate = Candidate(
            id="cand-123",
            snapshot_id="snap-456",
            selector="article > p",
            field="body",
            score=95.5,
            words=250,
            snippet="Article content preview...",
            created_at=now,
        )

        result = candidate.to_dict()

        assert result["id"] == "cand-123"
        assert result["snapshot_id"] == "snap-456"
        assert result["selector"] == "article > p"
        assert result["field"] == "body"
        assert result["score"] == 95.5
        assert result["words"] == 250
        assert result["snippet"] == "Article content preview..."
        assert result["created_at"] == "2025-10-04T16:00:00"


class TestReextractionJobSerialization:
    """Test ReextractionJob model to_dict() serialization."""

    def test_reextraction_job_to_dict(self):
        """Test ReextractionJob serialization."""
        now = datetime(2025, 10, 4, 17, 0, 0)
        job = ReextractionJob(
            host="example.com",
            status="completed",
            result_json='{"success": true}',
        )
        job.id = "job-123"
        job.created_at = now
        job.updated_at = now

        result = job.to_dict()

        assert result["id"] == "job-123"
        assert result["host"] == "example.com"
        assert result["status"] == "completed"
        assert result["result_json"] == '{"success": true}'
        assert result["created_at"] == "2025-10-04T17:00:00"
        assert result["updated_at"] == "2025-10-04T17:00:00"


class TestDedupeAuditSerialization:
    """Test DedupeAudit model to_dict() serialization."""

    def test_dedupe_audit_to_dict(self):
        """Test DedupeAudit serialization."""
        now = datetime(2025, 10, 4, 18, 0, 0)
        audit = DedupeAudit(
            article_uid="uid-1",
            neighbor_uid="uid-2",
            host="example.com",
            similarity=0.92,
            dedupe_flag=True,
            details="Confirmed duplicate",
        )
        audit.created_at = now

        result = audit.to_dict()

        assert result["article_uid"] == "uid-1"
        assert result["neighbor_uid"] == "uid-2"
        assert result["similarity"] == 0.92
        assert result["dedupe_flag"] is True
        assert result["host"] == "example.com"
        assert result["details"] == "Confirmed duplicate"
        assert result["created_at"] == "2025-10-04T18:00:00"


class TestBylineCleaningTelemetrySerialization:
    """Test BylineCleaningTelemetry model to_dict() serialization."""

    def test_byline_telemetry_to_dict(self):
        """Test BylineCleaningTelemetry serialization."""
        now = datetime(2025, 10, 4, 19, 0, 0)
        telemetry = BylineCleaningTelemetry(
            article_id="uid-999",
            source_id="src-123",
            source_name="Example News",
            raw_byline="By John Doe, Staff Writer",
            extraction_timestamp=now,
            cleaning_method="standard",
            confidence_score=0.95,
            requires_manual_review=False,
        )
        telemetry.id = "telem-123"
        telemetry.created_at = now

        result = telemetry.to_dict()

        assert result["id"] == "telem-123"
        assert result["article_id"] == "uid-999"
        assert result["raw_byline"] == "By John Doe, Staff Writer"
        assert result["source_id"] == "src-123"
        assert result["source_name"] == "Example News"
        assert result["cleaning_method"] == "standard"
        assert result["confidence_score"] == 0.95
        assert result["requires_manual_review"] is False
        assert result["reviewed_by"] is None
        assert result["created_at"] == "2025-10-04T19:00:00"
        assert result["reviewed_at"] is None


class TestBylineTransformationStepSerialization:
    """Test BylineTransformationStep model to_dict() serialization."""

    def test_transformation_step_to_dict(self):
        """Test BylineTransformationStep serialization."""
        now = datetime(2025, 10, 4, 20, 0, 0)
        step = BylineTransformationStep(
            telemetry_id="telem-456",
            step_number=1,
            transformation_type="regex_replace",
            input_text="By John Doe",
            output_text="John Doe",
        )
        step.id = "step-123"
        step.created_at = now

        result = step.to_dict()

        assert result["id"] == "step-123"
        assert result["telemetry_id"] == "telem-456"
        assert result["step_number"] == 1
        assert result["transformation_type"] == "regex_replace"
        assert result["input_text"] == "By John Doe"
        assert result["output_text"] == "John Doe"
        assert result["created_at"] == "2025-10-04T20:00:00"


class TestCodeReviewTelemetrySerialization:
    """Test CodeReviewTelemetry model to_dict() serialization."""

    def test_code_review_telemetry_to_dict(self):
        """Test CodeReviewTelemetry serialization."""
        now = datetime(2025, 10, 4, 21, 0, 0)
        review = CodeReviewTelemetry(
            review_id="review-123",
            file_path="src/byline_cleaner.py",
            issue_type="style",
            severity="low",
            description="Minor style improvements suggested",
            reviewer="ci_bot",
        )
        review.id = "rev-uuid-123"
        review.created_at = now

        result = review.to_dict()

        assert result["id"] == "rev-uuid-123"
        assert result["review_id"] == "review-123"
        assert result["file_path"] == "src/byline_cleaner.py"
        assert result["issue_type"] == "style"
        assert result["severity"] == "low"
        assert result["reviewer"] == "ci_bot"
        assert result["description"] == "Minor style improvements suggested"
        assert result["created_at"] == "2025-10-04T21:00:00"
        assert result["reviewed_at"] is None


class TestDatetimeHandling:
    """Test datetime field handling across all models."""

    def test_none_datetime_returns_none(self):
        """Test that None datetime values are serialized as None."""
        review = Review(id="test", reviewer="user", reviewed_at=None)
        result = review.to_dict()
        assert result["reviewed_at"] is None

    def test_datetime_isoformat(self):
        """Test that datetime objects are converted to ISO format strings."""
        dt = datetime(2025, 10, 4, 12, 30, 45)
        review = Review(id="test", reviewer="user", created_at=dt, reviewed_at=dt)
        result = review.to_dict()
        assert result["created_at"] == "2025-10-04T12:30:45"
        assert result["reviewed_at"] == "2025-10-04T12:30:45"

    def test_datetime_with_microseconds(self):
        """Test datetime serialization with microseconds."""
        dt = datetime(2025, 10, 4, 12, 30, 45, 123456)
        review = Review(id="test", reviewer="user", created_at=dt)
        result = review.to_dict()
        assert result["created_at"] == "2025-10-04T12:30:45.123456"
