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


from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


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
    Version 2 of extraction telemetry with enhanced metrics.
    
    Tracks detailed extraction attempts, outcomes, and performance metrics.
    
    Column count: 27 (>20, recommended for ORM)
    """

    __tablename__ = "extraction_telemetry_v2"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Operation tracking
    operation_id = Column(String, nullable=False, index=True)
    article_id = Column(Integer, nullable=False, index=True)
    url = Column(String, nullable=False, index=True)

    # Outcome
    outcome = Column(String, nullable=False, index=True)

    # Performance metrics
    extraction_time_ms = Column(Float, nullable=False, default=0.0)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)

    # HTTP metrics
    http_status_code = Column(Integer, nullable=True)
    response_size_bytes = Column(Integer, nullable=True)

    # Content flags
    has_title = Column(Boolean, nullable=False, default=False)
    has_content = Column(Boolean, nullable=False, default=False)
    has_author = Column(Boolean, nullable=False, default=False)
    has_publish_date = Column(Boolean, nullable=False, default=False)

    # Content quality
    content_length = Column(Integer, nullable=True)
    title_length = Column(Integer, nullable=True)
    author_count = Column(Integer, nullable=True)
    content_quality_score = Column(Float, nullable=True, index=True)

    # Error tracking
    error_message = Column(Text, nullable=True)
    error_type = Column(String, nullable=True)

    # Success classification
    is_success = Column(Boolean, nullable=False, default=False, index=True)
    is_content_success = Column(Boolean, nullable=False, default=False, index=True)
    is_technical_failure = Column(Boolean, nullable=False, default=False)
    is_bot_protection = Column(Boolean, nullable=False, default=False)

    # Additional metadata (renamed to avoid SQLAlchemy reserved name)
    metadata_json = Column(Text, nullable=True)

    # Timestamp
    timestamp = Column(DateTime, nullable=True, index=True)

    def __repr__(self):
        return (
            f"<ExtractionTelemetryV2(id={self.id}, "
            f"article_id={self.article_id}, "
            f"outcome={self.outcome!r})>"
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
