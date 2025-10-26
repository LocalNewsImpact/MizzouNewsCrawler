"""Code review telemetry API using Cloud SQL."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func

from src.models.api_backend import CodeReviewTelemetry
from src.models.database import DatabaseManager


class CodeReviewItem(BaseModel):
    """Single code review item."""

    review_id: str
    file_path: str
    line_number: int | None = None
    code_snippet: str | None = None
    issue_type: str
    severity: str
    description: str
    suggested_fix: str | None = None
    reviewer: str | None = None


class CodeReviewFeedback(BaseModel):
    """Human feedback for a code review item."""

    review_id: str
    human_label: str  # "valid", "invalid", "fixed"
    human_notes: str | None = None
    reviewed_by: str


class CodeReviewStats(BaseModel):
    """Summary statistics for code review telemetry."""

    total_reviews: int
    pending_review: int
    reviewed_valid: int
    reviewed_invalid: int
    reviewed_fixed: int


def init_code_review_tables():
    """Initialize code review tables (no-op for SQLAlchemy - tables created via migration)."""
    pass


def get_pending_code_reviews(limit: int = 50) -> list[dict]:
    """Get code review items that need human review."""
    with DatabaseManager() as db:
        query = (
            db.session.query(CodeReviewTelemetry)
            .filter(CodeReviewTelemetry.human_label.is_(None))
            .order_by(CodeReviewTelemetry.created_at.desc())
            .limit(limit)
        )

        items = []
        for review in query.all():
            items.append(
                {
                    "review_id": review.review_id,
                    "file_path": review.file_path,
                    "line_number": review.line_number,
                    "code_snippet": review.code_snippet,
                    "issue_type": review.issue_type,
                    "severity": review.severity,
                    "description": review.description,
                    "suggested_fix": review.suggested_fix,
                    "reviewer": review.reviewer,
                    "human_label": review.human_label,
                    "human_notes": review.human_notes,
                    "reviewed_by": review.reviewed_by,
                    "reviewed_at": review.reviewed_at,
                }
            )

        return items


def submit_code_review_feedback(feedback: CodeReviewFeedback) -> bool:
    """Store human feedback for a code review item."""
    with DatabaseManager() as db:
        review = (
            db.session.query(CodeReviewTelemetry)
            .filter(CodeReviewTelemetry.review_id == feedback.review_id)
            .first()
        )

        if not review:
            return False

        review.human_label = feedback.human_label
        review.human_notes = feedback.human_notes
        review.reviewed_by = feedback.reviewed_by
        review.reviewed_at = datetime.utcnow()

        db.session.commit()
        return True


def get_code_review_stats() -> CodeReviewStats:
    """Get summary statistics for code review telemetry."""
    with DatabaseManager() as db:
        # Total reviews
        total = db.session.query(func.count(CodeReviewTelemetry.id)).scalar() or 0

        # Pending review
        pending = (
            db.session.query(func.count(CodeReviewTelemetry.id))
            .filter(CodeReviewTelemetry.human_label.is_(None))
            .scalar()
            or 0
        )

        # Reviewed counts
        reviewed_valid = (
            db.session.query(func.count(CodeReviewTelemetry.id))
            .filter(CodeReviewTelemetry.human_label == "valid")
            .scalar()
            or 0
        )

        reviewed_invalid = (
            db.session.query(func.count(CodeReviewTelemetry.id))
            .filter(CodeReviewTelemetry.human_label == "invalid")
            .scalar()
            or 0
        )

        reviewed_fixed = (
            db.session.query(func.count(CodeReviewTelemetry.id))
            .filter(CodeReviewTelemetry.human_label == "fixed")
            .scalar()
            or 0
        )

        return CodeReviewStats(
            total_reviews=total,
            pending_review=pending,
            reviewed_valid=reviewed_valid,
            reviewed_invalid=reviewed_invalid,
            reviewed_fixed=reviewed_fixed,
        )


def add_code_review_item(item: CodeReviewItem) -> bool:
    """Add a new code review item."""
    with DatabaseManager() as db:
        review = CodeReviewTelemetry(
            review_id=item.review_id,
            file_path=item.file_path,
            line_number=item.line_number,
            code_snippet=item.code_snippet,
            issue_type=item.issue_type,
            severity=item.severity,
            description=item.description,
            suggested_fix=item.suggested_fix,
            reviewer=item.reviewer,
            created_at=datetime.utcnow(),
        )

        db.session.add(review)
        db.session.commit()
        return True
