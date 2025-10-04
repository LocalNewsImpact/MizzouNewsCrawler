"""Verification telemetry API using Cloud SQL."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func

from src.models import URLVerification
from src.models.database import DatabaseManager


class URLVerificationItem(BaseModel):
    """Single URL verification result for human review."""

    verification_id: str
    url: str
    storysniffer_result: bool | None
    verification_confidence: float | None
    article_headline: str | None
    article_excerpt: str | None
    verification_time_ms: float | None
    verified_at: datetime
    source_name: str | None

    # Human feedback fields (initially null)
    human_label: str | None = None  # "correct", "incorrect"
    human_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class VerificationFeedback(BaseModel):
    """Human feedback for a URL verification result."""

    verification_id: str
    human_label: str  # "correct", "incorrect"
    human_notes: str | None = None
    reviewed_by: str


class VerificationTelemetryStats(BaseModel):
    """Summary statistics for verification telemetry."""

    total_verifications: int
    pending_review: int
    reviewed_correct: int
    reviewed_incorrect: int
    storysniffer_accuracy: float | None
    avg_verification_time_ms: float | None
    article_rate: float
    sources_represented: int


def get_pending_verification_reviews(limit: int = 50) -> list[URLVerificationItem]:
    """Get URL verifications that need human review."""
    with DatabaseManager() as db:
        # Get items without human feedback, ordered by verification time
        query = (
            db.session.query(URLVerification)
            .filter(URLVerification.human_label.is_(None))
            .filter(URLVerification.storysniffer_result.isnot(None))
            .order_by(URLVerification.verified_at.desc())
            .limit(limit)
        )

        items = []
        for verification in query.all():
            items.append(
                URLVerificationItem(
                    verification_id=verification.id,
                    url=verification.url,
                    storysniffer_result=verification.storysniffer_result,
                    verification_confidence=verification.verification_confidence,
                    article_headline=verification.article_headline,
                    article_excerpt=verification.article_excerpt,
                    verification_time_ms=verification.verification_time_ms,
                    verified_at=verification.verified_at,
                    source_name="Unknown",  # Would need to join with candidate_links
                    human_label=verification.human_label,
                    human_notes=verification.human_notes,
                    reviewed_by=verification.reviewed_by,
                    reviewed_at=verification.reviewed_at,
                )
            )

        return items


def submit_verification_feedback(feedback: VerificationFeedback) -> bool:
    """Store human feedback for a URL verification result."""
    with DatabaseManager() as db:
        verification = (
            db.session.query(URLVerification)
            .filter(URLVerification.id == feedback.verification_id)
            .first()
        )

        if not verification:
            return False

        verification.human_label = feedback.human_label
        verification.human_notes = feedback.human_notes
        verification.reviewed_by = feedback.reviewed_by
        verification.reviewed_at = datetime.utcnow()

        db.session.commit()
        return True


def get_verification_telemetry_stats() -> VerificationTelemetryStats:
    """Get summary statistics for verification telemetry."""
    with DatabaseManager() as db:
        # Total verifications
        total = db.session.query(func.count(URLVerification.id)).scalar() or 0

        # Pending review (no human label)
        pending = (
            db.session.query(func.count(URLVerification.id))
            .filter(URLVerification.human_label.is_(None))
            .filter(URLVerification.storysniffer_result.isnot(None))
            .scalar()
            or 0
        )

        # Reviewed correct/incorrect
        reviewed_correct = (
            db.session.query(func.count(URLVerification.id))
            .filter(URLVerification.human_label == "correct")
            .scalar()
            or 0
        )

        reviewed_incorrect = (
            db.session.query(func.count(URLVerification.id))
            .filter(URLVerification.human_label == "incorrect")
            .scalar()
            or 0
        )

        # Accuracy calculation
        total_reviewed = reviewed_correct + reviewed_incorrect
        accuracy = (
            (reviewed_correct / total_reviewed) if total_reviewed > 0 else None
        )

        # Average verification time
        avg_time = (
            db.session.query(func.avg(URLVerification.verification_time_ms))
            .filter(URLVerification.verification_time_ms.isnot(None))
            .scalar()
        )

        # Article rate (percentage that are articles)
        article_count = (
            db.session.query(func.count(URLVerification.id))
            .filter(URLVerification.storysniffer_result == True)  # noqa: E712
            .scalar()
            or 0
        )
        article_rate = (article_count / total) if total > 0 else 0.0

        # Sources represented (would need join with candidate_links)
        sources_count = 0

        return VerificationTelemetryStats(
            total_verifications=total,
            pending_review=pending,
            reviewed_correct=reviewed_correct,
            reviewed_incorrect=reviewed_incorrect,
            storysniffer_accuracy=accuracy,
            avg_verification_time_ms=avg_time,
            article_rate=article_rate,
            sources_represented=sources_count,
        )


def enhance_verification_with_content(
    verification_id: str, headline: str = "", excerpt: str = ""
) -> bool:
    """Add article content to verification for human review."""
    with DatabaseManager() as db:
        verification = (
            db.session.query(URLVerification)
            .filter(URLVerification.id == verification_id)
            .first()
        )

        if not verification:
            return False

        if headline:
            verification.article_headline = headline
        if excerpt:
            verification.article_excerpt = excerpt

        db.session.commit()
        return True


def get_labeled_verification_training_data(
    min_confidence: float = 0.0, format: str = "json"
) -> list[dict] | str:
    """Export labeled verification training data for ML."""
    with DatabaseManager() as db:
        query = (
            db.session.query(URLVerification)
            .filter(URLVerification.human_label.isnot(None))
            .filter(
                (URLVerification.verification_confidence >= min_confidence)
                | (URLVerification.verification_confidence.is_(None))
            )
        )

        data = []
        for v in query.all():
            data.append(
                {
                    "url": v.url,
                    "storysniffer_result": v.storysniffer_result,
                    "verification_confidence": v.verification_confidence,
                    "human_label": v.human_label,
                    "article_headline": v.article_headline,
                    "article_excerpt": v.article_excerpt,
                }
            )

        if format == "csv":
            # Would need to implement CSV conversion
            return str(data)

        return data
