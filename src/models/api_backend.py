"""SQLAlchemy models for API backend tables.

These models represent the tables currently stored in SQLite (backend/reviews.db)
that need to be migrated to Cloud SQL/PostgreSQL.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from . import Base


class Review(Base):
    """Article review data from human reviewers."""

    __tablename__ = "reviews"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_idx = Column(Integer, index=True)
    article_uid = Column(String, index=True)
    reviewer = Column(String, nullable=False, index=True)
    rating = Column(Integer)
    secondary_rating = Column(Integer)
    tags = Column(Text)  # JSON string array
    notes = Column(Text)
    mentioned_locations = Column(Text)  # JSON string array
    missing_locations = Column(Text)  # JSON string array
    incorrect_locations = Column(Text)  # JSON string array
    inferred_tags = Column(Text)  # JSON string array
    missing_tags = Column(Text)  # JSON string array
    incorrect_tags = Column(Text)  # JSON string array
    body_errors = Column(Text)  # JSON string array
    headline_errors = Column(Text)  # JSON string array
    author_errors = Column(Text)  # JSON string array
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = Column(DateTime)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "article_idx": self.article_idx,
            "article_uid": self.article_uid,
            "reviewer": self.reviewer,
            "rating": self.rating,
            "secondary_rating": self.secondary_rating,
            "tags": self.tags,
            "notes": self.notes,
            "mentioned_locations": self.mentioned_locations,
            "missing_locations": self.missing_locations,
            "incorrect_locations": self.incorrect_locations,
            "inferred_tags": self.inferred_tags,
            "missing_tags": self.missing_tags,
            "incorrect_tags": self.incorrect_tags,
            "body_errors": self.body_errors,
            "headline_errors": self.headline_errors,
            "author_errors": self.author_errors,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


class DomainFeedback(Base):
    """Domain/host-level feedback and notes from reviewers."""

    __tablename__ = "domain_feedback"

    host = Column(String, primary_key=True)
    notes = Column(Text)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "host": self.host,
            "notes": self.notes,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Snapshot(Base):
    """HTML snapshots captured during extraction for review."""

    __tablename__ = "snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    host = Column(String, index=True)
    url = Column(String, nullable=False)
    path = Column(String)  # File path to stored HTML
    pipeline_run_id = Column(String, index=True)
    failure_reason = Column(Text)
    parsed_fields = Column(Text)  # JSON string
    model_confidence = Column(Float)
    status = Column(String, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = Column(DateTime)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "host": self.host,
            "url": self.url,
            "path": self.path,
            "pipeline_run_id": self.pipeline_run_id,
            "failure_reason": self.failure_reason,
            "parsed_fields": self.parsed_fields,
            "model_confidence": self.model_confidence,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


class Candidate(Base):
    """Candidate selectors for field extraction."""

    __tablename__ = "candidates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_id = Column(String, index=True)
    selector = Column(String, nullable=False)
    field = Column(String)  # Which field this selector extracts
    score = Column(Float)
    words = Column(Integer)
    snippet = Column(Text)
    alts = Column(Text)  # JSON string array of alternative selectors
    accepted = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "snapshot_id": self.snapshot_id,
            "selector": self.selector,
            "field": self.field,
            "score": self.score,
            "words": self.words,
            "snippet": self.snippet,
            "alts": self.alts,
            "accepted": self.accepted,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ReextractionJob(Base):
    """Jobs for re-extracting content with updated rules."""

    __tablename__ = "reextract_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    host = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    result_json = Column(Text)  # JSON string with results
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "host": self.host,
            "status": self.status,
            "result_json": self.result_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DedupeAudit(Base):
    """Deduplication audit trail for article similarity."""

    __tablename__ = "dedupe_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_uid = Column(String, index=True)
    neighbor_uid = Column(String)
    host = Column(String, index=True)
    similarity = Column(Float)
    dedupe_flag = Column(Boolean)
    category = Column(Integer)
    stage = Column(String)
    details = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "article_uid": self.article_uid,
            "neighbor_uid": self.neighbor_uid,
            "host": self.host,
            "similarity": self.similarity,
            "dedupe_flag": self.dedupe_flag,
            "category": self.category,
            "stage": self.stage,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BylineCleaningTelemetry(Base):
    """Telemetry data for byline cleaning operations."""

    __tablename__ = "byline_cleaning_telemetry"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id = Column(String, index=True)
    candidate_link_id = Column(String, index=True)
    source_id = Column(String, index=True)
    source_name = Column(String, index=True)
    raw_byline = Column(Text)
    raw_byline_length = Column(Integer)
    raw_byline_words = Column(Integer)
    extraction_timestamp = Column(DateTime, nullable=False, index=True)
    cleaning_method = Column(String)
    source_canonical_name = Column(String)
    final_authors_json = Column(Text)  # JSON string
    final_authors_count = Column(Integer)
    final_authors_display = Column(String)
    confidence_score = Column(Float)
    processing_time_ms = Column(Float)
    has_wire_service = Column(Boolean)
    has_email = Column(Boolean)
    has_title = Column(Boolean)
    has_organization = Column(Boolean)
    source_name_removed = Column(Boolean)
    duplicates_removed_count = Column(Integer)
    likely_valid_authors = Column(Boolean)
    likely_noise = Column(Boolean)
    requires_manual_review = Column(Boolean)
    cleaning_errors = Column(Text)
    parsing_warnings = Column(Text)

    # Human feedback fields
    human_label = Column(String)  # "correct", "incorrect", "partial"
    human_notes = Column(Text)
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "article_id": self.article_id,
            "candidate_link_id": self.candidate_link_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "raw_byline": self.raw_byline,
            "raw_byline_length": self.raw_byline_length,
            "raw_byline_words": self.raw_byline_words,
            "extraction_timestamp": (
                self.extraction_timestamp.isoformat()
                if self.extraction_timestamp
                else None
            ),
            "cleaning_method": self.cleaning_method,
            "source_canonical_name": self.source_canonical_name,
            "final_authors_json": self.final_authors_json,
            "final_authors_count": self.final_authors_count,
            "final_authors_display": self.final_authors_display,
            "confidence_score": self.confidence_score,
            "processing_time_ms": self.processing_time_ms,
            "has_wire_service": self.has_wire_service,
            "has_email": self.has_email,
            "has_title": self.has_title,
            "has_organization": self.has_organization,
            "source_name_removed": self.source_name_removed,
            "duplicates_removed_count": self.duplicates_removed_count,
            "likely_valid_authors": self.likely_valid_authors,
            "likely_noise": self.likely_noise,
            "requires_manual_review": self.requires_manual_review,
            "cleaning_errors": self.cleaning_errors,
            "parsing_warnings": self.parsing_warnings,
            "human_label": self.human_label,
            "human_notes": self.human_notes,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BylineTransformationStep(Base):
    """Individual transformation steps in byline cleaning."""

    __tablename__ = "byline_transformation_steps"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telemetry_id = Column(String, nullable=False, index=True)
    step_number = Column(Integer)
    step_name = Column(String)
    input_text = Column(Text)
    output_text = Column(Text)
    transformation_type = Column(String)
    removed_content = Column(Text)
    added_content = Column(Text)
    confidence_delta = Column(Float)
    processing_time_ms = Column(Float)
    notes = Column(Text)
    timestamp = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "telemetry_id": self.telemetry_id,
            "step_number": self.step_number,
            "step_name": self.step_name,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "transformation_type": self.transformation_type,
            "removed_content": self.removed_content,
            "added_content": self.added_content,
            "confidence_delta": self.confidence_delta,
            "processing_time_ms": self.processing_time_ms,
            "notes": self.notes,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CodeReviewTelemetry(Base):
    """Telemetry for code review items and feedback."""

    __tablename__ = "code_review_telemetry"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    review_id = Column(String, unique=True, nullable=False, index=True)
    file_path = Column(String, nullable=False)
    line_number = Column(Integer)
    code_snippet = Column(Text)
    issue_type = Column(String)  # "bug", "style", "performance", etc.
    severity = Column(String)  # "low", "medium", "high", "critical"
    description = Column(Text)
    suggested_fix = Column(Text)
    reviewer = Column(String)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Human feedback fields
    human_label = Column(String)  # "valid", "invalid", "fixed"
    human_notes = Column(Text)
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime)

    def to_dict(self):
        """Serialize model to dictionary for API responses."""
        return {
            "id": self.id,
            "review_id": self.review_id,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "suggested_fix": self.suggested_fix,
            "reviewer": self.reviewer,
            "human_label": self.human_label,
            "human_notes": self.human_notes,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
