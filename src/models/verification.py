"""Database models for URL verification and telemetry tracking."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from . import Base


class VerificationJob(Base):
    """Tracks verification job executions and telemetry."""

    __tablename__ = "verification_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # e.g., "storysniffer_verification_batch_1"
    job_name = Column(String, nullable=False)
    # Links to the original discovery job
    discovery_job_id = Column(String, index=True)

    # Job execution details
    # running, completed, failed
    status = Column(String, nullable=False, default="running")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime)

    # Processing metrics
    total_urls = Column(Integer, default=0)
    processed_urls = Column(Integer, default=0)
    verified_articles = Column(Integer, default=0)
    verified_non_articles = Column(Integer, default=0)
    verification_errors = Column(Integer, default=0)

    # Performance metrics
    avg_verification_time_ms = Column(Float)
    total_processing_time_seconds = Column(Float)

    # Configuration used
    config = Column(JSON)  # Settings, filters, etc.
    error_message = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    verifications = relationship("URLVerification", back_populates="job")


class URLVerification(Base):
    """Individual URL verification results with StorySniffer."""

    __tablename__ = "url_verifications"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_link_id = Column(
        String,
        ForeignKey("candidate_links.id"),
        nullable=False,
        index=True
    )
    verification_job_id = Column(
        String,
        ForeignKey("verification_jobs.id"),
        nullable=False,
        index=True
    )

    # Verification results
    url = Column(String, nullable=False, index=True)
    # True = article, False = not article
    storysniffer_result = Column(Boolean)
    # If StorySniffer provides confidence scores
    verification_confidence = Column(Float)

    # Timing and metadata
    verified_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    verification_time_ms = Column(Float)  # Time taken for this verification

    # Status tracking
    previous_status = Column(String)  # Status before verification
    # Status after verification (article/not_article)
    new_status = Column(String)

    # Error handling
    verification_error = Column(String)  # Error message if verification failed
    retry_count = Column(Integer, default=0)

    # Additional metadata
    meta = Column(JSON)  # Any additional verification metadata

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    job = relationship("VerificationJob", back_populates="verifications")


class VerificationTelemetry(Base):
    """Aggregated telemetry data for verification jobs."""

    __tablename__ = "verification_telemetry"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    verification_job_id = Column(
        String,
        ForeignKey("verification_jobs.id"),
        nullable=False,
        index=True
    )

    # Source-level breakdown
    source_name = Column(String, index=True)
    source_county = Column(String, index=True)

    # Metrics for this source in this job
    total_urls = Column(Integer, default=0)
    verified_articles = Column(Integer, default=0)
    verified_non_articles = Column(Integer, default=0)
    verification_errors = Column(Integer, default=0)

    # Quality metrics
    article_rate = Column(Float)  # Percentage of URLs that are articles
    avg_verification_time_ms = Column(Float)

    # Pattern analysis
    # Most common non-article URL patterns
    top_non_article_patterns = Column(JSON)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class VerificationPattern(Base):
    """Tracks common URL patterns and their verification results."""

    __tablename__ = "verification_patterns"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Pattern details
    # e.g., "calendar", "category", "file"
    pattern_type = Column(String, nullable=False, index=True)
    pattern_regex = Column(String)  # Regex pattern for matching
    pattern_description = Column(String)  # Human-readable description

    # Verification statistics
    total_matches = Column(Integer, default=0)
    article_matches = Column(Integer, default=0)
    non_article_matches = Column(Integer, default=0)

    # Performance metrics
    article_rate = Column(Float)  # Percentage that are articles
    confidence_score = Column(Float)  # How reliable this pattern is

    # Pattern examples
    example_urls = Column(JSON)  # Sample URLs that match this pattern

    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)  # Whether to use for filtering
