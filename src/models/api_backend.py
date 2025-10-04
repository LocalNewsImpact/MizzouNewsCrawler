"""SQLAlchemy models for API backend tables.

These models represent the tables currently stored in SQLite (backend/reviews.db)
that need to be migrated to Cloud SQL/PostgreSQL.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text

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


class DomainFeedback(Base):
    """Domain/host-level feedback and notes from reviewers."""

    __tablename__ = "domain_feedback"

    host = Column(String, primary_key=True)
    notes = Column(Text)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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


class ReextractionJob(Base):
    """Jobs for re-extracting content with updated rules."""

    __tablename__ = "reextract_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    host = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    result_json = Column(Text)  # JSON string with results
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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
