"""Byline cleaning telemetry API using Cloud SQL."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func

from src.models.api_backend import BylineCleaningTelemetry
from src.models.database import DatabaseManager


class BylineTelemetryItem(BaseModel):
    """Single byline cleaning result for human review."""

    telemetry_id: str
    raw_byline: str
    final_authors_display: str
    confidence_score: float
    source_name: str
    processing_time_ms: float
    extraction_timestamp: datetime
    has_wire_service: bool
    source_name_removed: bool
    cleaning_method: str

    # Human feedback fields (initially null)
    human_label: str | None = None  # "correct", "incorrect", "partial"
    human_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class BylineFeedback(BaseModel):
    """Human feedback for a byline cleaning result."""

    telemetry_id: str
    human_label: str  # "correct", "incorrect", "partial"
    human_notes: str | None = None
    reviewed_by: str


class BylineTelemetryStats(BaseModel):
    """Summary statistics for byline telemetry."""

    total_extractions: int
    pending_review: int
    reviewed_correct: int
    reviewed_incorrect: int
    reviewed_partial: int
    avg_confidence_score: float
    sources_represented: int


def get_pending_byline_reviews(limit: int = 50) -> list[BylineTelemetryItem]:
    """Get byline extractions that need human review."""
    with DatabaseManager() as db:
        query = (
            db.session.query(BylineCleaningTelemetry)
            .filter(BylineCleaningTelemetry.human_label.is_(None))
            .order_by(BylineCleaningTelemetry.extraction_timestamp.desc())
            .limit(limit)
        )

        items = []
        for telemetry in query.all():
            items.append(
                BylineTelemetryItem(
                    telemetry_id=telemetry.id,
                    raw_byline=telemetry.raw_byline or "",
                    final_authors_display=telemetry.final_authors_display or "",
                    confidence_score=telemetry.confidence_score or 0.0,
                    source_name=telemetry.source_name or "Unknown",
                    processing_time_ms=telemetry.processing_time_ms or 0.0,
                    extraction_timestamp=telemetry.extraction_timestamp,
                    has_wire_service=telemetry.has_wire_service or False,
                    source_name_removed=telemetry.source_name_removed or False,
                    cleaning_method=telemetry.cleaning_method or "unknown",
                    human_label=telemetry.human_label,
                    human_notes=telemetry.human_notes,
                    reviewed_by=telemetry.reviewed_by,
                    reviewed_at=telemetry.reviewed_at,
                )
            )

        return items


def submit_byline_feedback(feedback: BylineFeedback) -> bool:
    """Store human feedback for a byline cleaning result."""
    with DatabaseManager() as db:
        telemetry = (
            db.session.query(BylineCleaningTelemetry)
            .filter(BylineCleaningTelemetry.id == feedback.telemetry_id)
            .first()
        )

        if not telemetry:
            return False

        telemetry.human_label = feedback.human_label
        telemetry.human_notes = feedback.human_notes
        telemetry.reviewed_by = feedback.reviewed_by
        telemetry.reviewed_at = datetime.utcnow()

        db.session.commit()
        return True


def get_byline_telemetry_stats() -> BylineTelemetryStats:
    """Get summary statistics for byline telemetry."""
    with DatabaseManager() as db:
        # Total extractions
        total = (
            db.session.query(func.count(BylineCleaningTelemetry.id)).scalar() or 0
        )

        # Pending review
        pending = (
            db.session.query(func.count(BylineCleaningTelemetry.id))
            .filter(BylineCleaningTelemetry.human_label.is_(None))
            .scalar()
            or 0
        )

        # Reviewed counts
        reviewed_correct = (
            db.session.query(func.count(BylineCleaningTelemetry.id))
            .filter(BylineCleaningTelemetry.human_label == "correct")
            .scalar()
            or 0
        )

        reviewed_incorrect = (
            db.session.query(func.count(BylineCleaningTelemetry.id))
            .filter(BylineCleaningTelemetry.human_label == "incorrect")
            .scalar()
            or 0
        )

        reviewed_partial = (
            db.session.query(func.count(BylineCleaningTelemetry.id))
            .filter(BylineCleaningTelemetry.human_label == "partial")
            .scalar()
            or 0
        )

        # Average confidence score
        avg_confidence = (
            db.session.query(func.avg(BylineCleaningTelemetry.confidence_score))
            .filter(BylineCleaningTelemetry.confidence_score.isnot(None))
            .scalar()
            or 0.0
        )

        # Unique sources
        sources_count = (
            db.session.query(func.count(func.distinct(BylineCleaningTelemetry.source_name)))
            .filter(BylineCleaningTelemetry.source_name.isnot(None))
            .scalar()
            or 0
        )

        return BylineTelemetryStats(
            total_extractions=total,
            pending_review=pending,
            reviewed_correct=reviewed_correct,
            reviewed_incorrect=reviewed_incorrect,
            reviewed_partial=reviewed_partial,
            avg_confidence_score=float(avg_confidence),
            sources_represented=sources_count,
        )


def get_labeled_training_data(
    min_confidence: float = 0.0, format: str = "json"
) -> list[dict] | str:
    """Export labeled training data for ML."""
    with DatabaseManager() as db:
        query = (
            db.session.query(BylineCleaningTelemetry)
            .filter(BylineCleaningTelemetry.human_label.isnot(None))
            .filter(
                (BylineCleaningTelemetry.confidence_score >= min_confidence)
                | (BylineCleaningTelemetry.confidence_score.is_(None))
            )
        )

        data = []
        for t in query.all():
            data.append(
                {
                    "raw_byline": t.raw_byline,
                    "final_authors_display": t.final_authors_display,
                    "confidence_score": t.confidence_score,
                    "human_label": t.human_label,
                    "cleaning_method": t.cleaning_method,
                    "has_wire_service": t.has_wire_service,
                    "source_name_removed": t.source_name_removed,
                }
            )

        if format == "csv":
            # Would need to implement CSV conversion
            return str(data)

        return data
