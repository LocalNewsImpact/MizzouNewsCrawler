"""SQLAlchemy models for extraction telemetry and site management."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from src.models import Base


class ExtractionTelemetryV2(Base):
    """Comprehensive extraction telemetry tracking."""

    __tablename__ = "extraction_telemetry_v2"

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation_id = Column(String, nullable=False, index=True)
    article_id = Column(String, nullable=False, index=True)
    url = Column(String, nullable=False, index=True)
    publisher = Column(String, index=True)
    host = Column(String, index=True)

    # Timing metrics
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    total_duration_ms = Column(Float)

    # HTTP metrics
    http_status_code = Column(Integer)
    http_error_type = Column(String)
    response_size_bytes = Column(Integer)
    response_time_ms = Column(Float)

    # Method tracking (stored as JSON text)
    methods_attempted = Column(Text)
    successful_method = Column(String, index=True)
    method_timings = Column(Text)
    method_success = Column(Text)
    method_errors = Column(Text)

    # Field extraction tracking (stored as JSON text)
    field_extraction = Column(Text)
    extracted_fields = Column(Text)
    final_field_attribution = Column(Text)
    alternative_extractions = Column(Text)

    # Results
    content_length = Column(Integer)
    is_success = Column(Boolean, index=True)
    error_message = Column(Text)
    error_type = Column(String)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class HttpErrorSummary(Base):
    """HTTP error tracking by host and status code."""

    __tablename__ = "http_error_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String, nullable=False, index=True)
    status_code = Column(Integer, nullable=False, index=True)
    error_type = Column(String, nullable=False)
    count = Column(Integer, nullable=False, default=1)
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
