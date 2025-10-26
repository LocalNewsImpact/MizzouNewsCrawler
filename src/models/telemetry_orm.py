"""
SQLAlchemy ORM models for telemetry tables.

This module provides type-safe ORM models for complex telemetry tables (>20 columns)
to reduce errors from raw SQL INSERT statements.

Benefits of ORM approach:
- Type safety and IDE autocomplete
- Automatic column count validation
- Easier refactoring when schema changes
- Better integration with SQLAlchemy features (relationships, queries)
- Reduced risk of SQL injection
"""

from datetime import datetime  # noqa: F401 - used in docstring example
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base

Base: Any = declarative_base()


class BylineCleaningTelemetry(Base):
    """
    Telemetry for byline cleaning operations.

    Tracks the transformation of raw bylines to cleaned author fields,
    enabling analysis of cleaning effectiveness and generation of ML training datasets.

    Column count: 32 (>20, recommended for ORM)
    """

    __tablename__ = "byline_cleaning_telemetry"

    # Primary key
    id = Column(String, primary_key=True)

    # Article identifiers
    article_id = Column(String, nullable=True, index=True)
    candidate_link_id = Column(String, nullable=True, index=True)
    source_id = Column(String, nullable=True, index=True)
    source_name = Column(String, nullable=True, index=True)

    # Raw input data
    raw_byline = Column(Text, nullable=True)
    raw_byline_length = Column(Integer, nullable=True)
    raw_byline_words = Column(Integer, nullable=True)

    # Processing metadata
    extraction_timestamp = Column(DateTime, nullable=False, index=True)
    cleaning_method = Column(String, nullable=True)
    source_canonical_name = Column(String, nullable=True)

    # Final output
    final_authors_json = Column(Text, nullable=True)
    final_authors_count = Column(Integer, nullable=True)
    final_authors_display = Column(String, nullable=True)

    # Quality metrics
    confidence_score = Column(Float, nullable=True)
    processing_time_ms = Column(Float, nullable=True)
    has_wire_service = Column(Boolean, nullable=True)
    has_email = Column(Boolean, nullable=True)
    has_title = Column(Boolean, nullable=True)
    has_organization = Column(Boolean, nullable=True)
    source_name_removed = Column(Boolean, nullable=True)
    duplicates_removed_count = Column(Integer, nullable=True)

    # Classification flags for ML training
    likely_valid_authors = Column(Boolean, nullable=True)
    likely_noise = Column(Boolean, nullable=True)
    requires_manual_review = Column(Boolean, nullable=True)

    # Error tracking
    cleaning_errors = Column(Text, nullable=True)
    parsing_warnings = Column(Text, nullable=True)

    # Human review fields
    human_label = Column(String, nullable=True)
    human_notes = Column(Text, nullable=True)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    # Timestamp
    created_at = Column(DateTime, nullable=False)

    def __repr__(self):
        return (
            f"<BylineCleaningTelemetry(id={self.id!r}, "
            f"article_id={self.article_id!r}, "
            f"confidence_score={self.confidence_score})>"
        )


class ExtractionTelemetryV2(Base):
    """
    Version 2 of extraction telemetry with comprehensive method-level metrics.

    Tracks detailed extraction attempts including multiple methods, proxy usage,
    field-level attribution, and alternative extractions.

    Column count: 30 (>20, recommended for ORM)
    """

    __tablename__ = "extraction_telemetry_v2"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Operation tracking
    operation_id = Column(String, nullable=False, index=True)
    article_id = Column(String, nullable=False, index=True)
    url = Column(String, nullable=False, index=True)
    publisher = Column(String, nullable=True, index=True)
    host = Column(String, nullable=True, index=True)

    # Timing
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    total_duration_ms = Column(Float, nullable=True)

    # HTTP metrics
    http_status_code = Column(Integer, nullable=True)
    http_error_type = Column(String, nullable=True)
    response_size_bytes = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)

    # Proxy metrics
    proxy_used = Column(Integer, nullable=True)  # 0 or 1
    proxy_url = Column(String, nullable=True)
    proxy_authenticated = Column(Integer, nullable=True)  # 0 or 1
    proxy_status = Column(String, nullable=True)
    proxy_error = Column(String, nullable=True)

    # Method tracking (JSON strings)
    methods_attempted = Column(Text, nullable=True)  # JSON array
    successful_method = Column(String, nullable=True, index=True)
    method_timings = Column(Text, nullable=True)  # JSON object
    method_success = Column(Text, nullable=True)  # JSON object
    method_errors = Column(Text, nullable=True)  # JSON object

    # Field extraction tracking (JSON strings)
    field_extraction = Column(Text, nullable=True)  # JSON object
    extracted_fields = Column(Text, nullable=True)  # JSON object
    final_field_attribution = Column(Text, nullable=True)  # JSON object
    alternative_extractions = Column(Text, nullable=True)  # JSON object

    # Content metrics
    content_length = Column(Integer, nullable=True)

    # Success classification
    is_success = Column(Boolean, nullable=False, default=False, index=True)

    # Error tracking
    error_message = Column(Text, nullable=True)
    error_type = Column(String, nullable=True)

    # Timestamp
    created_at = Column(
        DateTime, nullable=False, server_default="CURRENT_TIMESTAMP", index=True
    )

    def __repr__(self):
        return (
            f"<ExtractionTelemetryV2(id={self.id}, "
            f"article_id={self.article_id}, "
            f"successful_method={self.successful_method!r})>"
        )


class ContentTypeDetectionTelemetry(Base):
    """
    Telemetry for content type detection (news vs opinion vs other).

    Tracks automatic content classification to help identify and filter
    non-news content like opinion pieces and editorials.

    Column count: 14
    """

    __tablename__ = "content_type_detection_telemetry"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Article identifiers
    article_id = Column(String, nullable=False, index=True)
    operation_id = Column(String, nullable=False)
    url = Column(String, nullable=False)
    publisher = Column(String, nullable=True)
    host = Column(String, nullable=True)

    # Detection results
    status = Column(String, nullable=True, index=True)  # e.g., 'opinion', 'news'
    confidence = Column(String, nullable=True)  # e.g., 'high', 'medium', 'low'
    confidence_score = Column(Float, nullable=True)
    reason = Column(String, nullable=True)
    evidence = Column(Text, nullable=True)  # JSON string
    version = Column(String, nullable=True)

    # Timestamps
    detected_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, nullable=False, server_default="CURRENT_TIMESTAMP", index=True
    )

    def __repr__(self):
        return (
            f"<ContentTypeDetectionTelemetry(id={self.id}, "
            f"article_id={self.article_id}, "
            f"status={self.status!r})>"
        )


class ContentCleaningSession(Base):
    """
    Telemetry for content cleaning sessions.

    Tracks domain-level cleaning operations that identify and remove
    boilerplate content, navigation elements, and other non-article text.

    Column count: 13
    """

    __tablename__ = "content_cleaning_sessions"

    # Primary key
    telemetry_id = Column(String, primary_key=True)

    # Session info
    session_id = Column(String, nullable=True)
    domain = Column(String, nullable=True, index=True)
    article_count = Column(Integer, nullable=True)

    # Configuration
    min_occurrences = Column(Integer, nullable=True)
    min_boundary_score = Column(Float, nullable=True)

    # Timing
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    processing_time_ms = Column(Float, nullable=True)

    # Results
    rough_candidates_found = Column(Integer, nullable=True)
    segments_detected = Column(Integer, nullable=True)
    total_removable_chars = Column(Integer, nullable=True)
    removal_percentage = Column(Float, nullable=True)

    # Timestamp
    created_at = Column(DateTime, server_default="CURRENT_TIMESTAMP", index=True)

    def __repr__(self):
        return (
            f"<ContentCleaningSession(telemetry_id={self.telemetry_id}, "
            f"domain={self.domain!r}, "
            f"segments_detected={self.segments_detected})>"
        )


class HttpErrorSummary(Base):
    """
    HTTP error summary table for tracking recurring errors by host and status code.
    Aggregates extraction_telemetry_v2 HTTP errors for monitoring and analysis.
    """

    __tablename__ = "http_error_summary"
    __table_args__ = (
        UniqueConstraint(
            "host", "status_code", name="uq_http_error_summary_host_status"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String, nullable=False, index=True)
    status_code = Column(Integer, nullable=False, index=True)
    # e.g., '5xx_server_error', '4xx_client_error'
    error_type = Column(String, nullable=False)
    count = Column(Integer, nullable=False)
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False, index=True)

    def __repr__(self):
        return (
            f"<HttpErrorSummary({self.host}, {self.status_code}, "
            f"count={self.count})>"
        )


# Example usage documentation
"""
Example: Using ORM models for safer INSERT operations

Instead of raw SQL:
```python
conn.execute(
    '''
    INSERT INTO byline_cleaning_telemetry (
        id, article_id, candidate_link_id, source_id,
        source_name, raw_byline, raw_byline_length,
        # ... 25 more columns ...
        created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ..., ?)
    ''',
    (id, article_id, candidate_link_id, source_id, ...)  # Easy to mismatch!
)
```

Use ORM instead:
```python
from src.models.telemetry_orm import BylineCleaningTelemetry
from sqlalchemy.orm import Session

telemetry_record = BylineCleaningTelemetry(
    id=telemetry_id,
    article_id=article_id,
    candidate_link_id=candidate_link_id,
    source_id=source_id,
    source_name=source_name,
    raw_byline=raw_byline,
    raw_byline_length=len(raw_byline),
    # ... type-safe attributes with IDE autocomplete ...
    created_at=datetime.utcnow()
)

session = Session(engine)
session.add(telemetry_record)
session.commit()
```

Benefits:
- Type checking catches errors at development time
- IDE autocomplete prevents typos
- Automatic handling of column ordering
- Easy to add/remove columns (just update the model)
- Better testability (can mock ORM objects)
"""
