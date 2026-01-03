"""SQLAlchemy database models for MizzouNewsCrawler-Scripts."""

import uuid
from datetime import datetime
from typing import Any

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
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import (
    Mapped,
    declarative_base,
    mapped_column,
    relationship,
    sessionmaker,
)

Base: Any = declarative_base()

# Import API backend models after Base declaration. These are imported here to
# ensure they're registered with Base.metadata (side-effect imports).
import src.models.api_backend  # noqa: E402,F401  # type: ignore
import src.models.telemetry  # noqa: E402,F401  # type: ignore
import src.models.verification  # noqa: E402,F401  # type: ignore

# Backwards-compatibility: expose commonly-imported model names at package level
from .verification import (  # noqa: E402,F401
    URLVerification,
    VerificationJob,
    VerificationPattern,
    VerificationTelemetry,
)


class SourceMetadata(Base):
    """Metadata about news sources including bot sensitivity."""

    __tablename__ = "source_metadata"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    host = Column(String, unique=True, nullable=False, index=True)
    bot_sensitivity = Column(Integer, default=1)  # 1-10 scale
    last_sensitivity_update = Column(DateTime)
    last_crawl_attempt = Column(DateTime)
    last_successful_crawl = Column(DateTime)
    consecutive_failures = Column(Integer, default=0)
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


class CandidateLink(Base):
    """Links discovered during crawling with fetch status tracking."""

    __tablename__ = "candidate_links"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    url = Column(String, nullable=False, unique=True, index=True)
    source = Column(String, nullable=False)  # Site/publisher name
    discovered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    crawl_depth = Column(Integer, default=0)
    discovered_by = Column(String)  # Job/process that found this URL

    # Fetch status tracking
    status = Column(String, nullable=False, default="new", index=True)
    fetched_at = Column(DateTime)
    http_status = Column(Integer)
    content_hash = Column(String, index=True)  # SHA256 of raw content

    # Flexible metadata storage (avoid reserved name 'metadata')
    meta: Mapped[dict | None] = mapped_column(JSON)  # Headers, redirect chain, etc.
    # First-class publish date for candidate links (nullable)
    publish_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    # Fields expected by the CLI and bulk loaders
    source_host_id = Column(String, index=True)
    source_name = Column(String, index=True)
    source_city = Column(String, index=True)
    source_county = Column(String, index=True)
    source_type = Column(String)
    frequency = Column(String)
    owner = Column(String)
    address = Column(String)
    zip_code = Column(String)
    cached_geographic_entities = Column(String)
    cached_institutions = Column(String)
    cached_schools = Column(String)
    cached_government = Column(String)
    cached_healthcare = Column(String)
    cached_businesses = Column(String)
    cached_landmarks = Column(String)
    priority = Column(Integer, default=1, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    articles_found = Column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String)
    # Allow raw SQL INSERTs to omit created_at by using a server default
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    # Link to dataset and normalized source
    dataset_id: Mapped[str | None] = mapped_column(String, index=True)
    source_id: Mapped[str | None] = mapped_column(String, index=True)

    # Relationships
    articles = relationship("Article", back_populates="candidate_link")

    __table_args__ = (UniqueConstraint("url", name="uq_candidate_links_url"),)


class Article(Base):
    """Parsed article content and metadata."""

    __tablename__ = "articles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Use the name expected by the CLI and SQL queries
    candidate_link_id = Column(
        String,
        ForeignKey("candidate_links.id"),
        nullable=False,
    )

    # Core content
    url = Column(String, index=True, unique=True)  # Unique to prevent duplicates
    title = Column(Text)
    author: Mapped[str | None] = mapped_column(String)
    publish_date: Mapped[datetime | None] = mapped_column(DateTime)
    content = Column(Text)
    # Keep older 'text' fields for compatibility
    text = Column(Text)
    text_hash = Column(String, index=True)  # SHA256 of normalized text
    text_excerpt = Column(String(500))  # First 500 chars for preview

    # Status and metadata used by CLI workflows
    status = Column(String, nullable=False, default="discovered", index=True)
    # `metadata` is a reserved attribute name on Declarative classes; expose
    # it on the DB row as the column name but use the attribute `meta` here.
    meta: Mapped[dict | None] = mapped_column("metadata", JSON)
    # Wire service attribution payload stored as JSON for downstream reports
    wire: Mapped[dict | None] = mapped_column(JSON)
    wire_check_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )
    wire_check_attempted_at: Mapped[datetime | None] = mapped_column(DateTime)
    wire_check_error: Mapped[str | None] = mapped_column(String)
    wire_check_metadata: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    # Storage references
    raw_gcs_path = Column(String)  # Future: GCS path for raw HTML

    # Processing metadata
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    extraction_version = Column(String)  # Version of parsing logic
    # Classification outputs
    primary_label = Column(String)
    primary_label_confidence = Column(Float)
    alternate_label = Column(String)
    alternate_label_confidence = Column(Float)
    label_version = Column(String, index=True)
    label_model_version = Column(String)
    labels_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    candidate_link = relationship("CandidateLink", back_populates="articles")
    ml_results = relationship("MLResult", back_populates="article")
    locations = relationship("Location", back_populates="article")
    entities = relationship(
        "ArticleEntity",
        back_populates="article",
        cascade="all, delete-orphan",
    )
    labels = relationship(
        "ArticleLabel",
        back_populates="article",
        cascade="all, delete-orphan",
    )


class ArticleLabel(Base):
    """Versioned article labels with primary and alternate predictions."""

    __tablename__ = "article_labels"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id = Column(
        String,
        ForeignKey("articles.id"),
        nullable=False,
        index=True,
    )
    label_version = Column(String, nullable=False, index=True)
    model_version = Column(String, nullable=False)
    model_path = Column(String)
    primary_label: Mapped[str] = mapped_column(String, nullable=False)
    primary_label_confidence = Column(Float)
    alternate_label = Column(String)
    alternate_label_confidence = Column(Float)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    meta: Mapped[dict | None] = mapped_column(JSON)

    article = relationship("Article", back_populates="labels")

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "label_version",
            name="uq_article_label_version",
        ),
    )


class MLResult(Base):
    """Machine learning classification and labeling results."""

    __tablename__ = "ml_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id = Column(String, ForeignKey("articles.id"), nullable=False)

    # Model information
    model_version = Column(String, nullable=False)
    model_type = Column(String, nullable=False)  # 'classifier', 'ner', etc.

    # Results
    label: Mapped[str | None] = mapped_column(String)
    score = Column(Float)
    confidence = Column(Float)

    # Processing metadata
    run_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    job_id = Column(String, ForeignKey("jobs.id"))

    # Detailed results
    details: Mapped[dict | None] = mapped_column(
        JSON
    )  # Full model output, features, etc.

    # Relationships
    article = relationship("Article", back_populates="ml_results")
    job = relationship("Job", back_populates="ml_results")


class Location(Base):
    """Named entity recognition and geocoding results."""

    __tablename__ = "locations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id = Column(String, ForeignKey("articles.id"), nullable=False)

    # Entity information
    entity_text = Column(String, nullable=False)
    entity_type = Column(String)  # PERSON, ORG, GPE, etc.
    confidence = Column(Float)

    # Geocoding results
    geocoded_lat = Column(Float)
    geocoded_lon = Column(Float)
    geocoded_place = Column(String)  # Resolved place name
    geocoding_source = Column(String)  # Which geocoder was used

    # Processing metadata
    extracted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ner_model_version = Column(String)
    geocoding_version = Column(String)

    # Relationships
    article = relationship("Article", back_populates="locations")


class LocalBroadcasterCallsign(Base):
    """Local broadcaster callsigns to prevent false wire detection.

    This table tracks TV/radio station callsigns that are local to
    a dataset's coverage area. Used by ContentTypeDetector to avoid
    misclassifying local station datelines (e.g., 'COLUMBIA, Mo. (KMIZ)')
    as wire service content.
    """

    __tablename__ = "local_broadcaster_callsigns"

    id = Column(Integer, primary_key=True)
    callsign = Column(
        String(10),
        nullable=False,
        index=True,
        comment="FCC callsign (e.g., KMIZ, KOMU)",
    )
    source_id = Column(
        String,
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Foreign key to sources table (UUID string)",
    )
    dataset = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Dataset identifier (e.g., missouri, lehigh)",
    )
    market_name = Column(
        String(100),
        nullable=True,
        comment="Market name (e.g., Columbia-Jefferson City)",
    )
    station_type = Column(
        String(20),
        nullable=True,
        comment="TV, Radio, or Digital",
    )
    notes = Column(Text, nullable=True, comment="Additional context")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("callsign", "dataset", name="uix_callsign_dataset"),
        {"comment": "Local broadcaster callsigns to prevent false wire detection"},
    )

    # Relationship to sources
    source = relationship("Source", back_populates="broadcaster_callsigns")


class WireService(Base):
    """Wire service detection patterns.

    Stores regex patterns for identifying wire service content in articles.
    Replaces hardcoded patterns with database-driven configuration.
    """

    __tablename__ = "wire_services"

    id = Column(Integer, primary_key=True)
    service_name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Canonical service name (e.g., Associated Press)",
    )
    pattern = Column(
        String(500),
        nullable=False,
        comment="Regex pattern to match service in content",
    )
    pattern_type = Column(
        String(20),
        nullable=False,
        index=True,
        comment="dateline, byline, or attribution",
    )
    case_sensitive = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether pattern matching is case-sensitive",
    )
    priority = Column(
        Integer,
        nullable=False,
        default=100,
        comment="Detection priority (lower = higher priority)",
    )
    active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether this pattern is active",
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = ({"comment": "Wire service detection patterns"},)


class UrlPathFilter(Base):
    """URL path patterns to exclude from article verification.

    Stores URL path prefixes that indicate non-article content (videos,
    galleries, tags, etc.) to filter before StorySniffer verification.
    """

    __tablename__ = "url_path_filters"

    id = Column(Integer, primary_key=True)
    path_pattern = Column(
        String(200),
        nullable=False,
        unique=True,
        index=True,
        comment="URL path pattern to filter (e.g., /video/, /gallery/)",
    )
    filter_type = Column(
        String(50),
        nullable=False,
        default="prefix",
        comment="Match type: prefix, suffix, contains, regex",
    )
    reason = Column(
        String(200),
        nullable=True,
        comment="Why this pattern is filtered (e.g., 'video content')",
    )
    active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether this filter is active",
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = ({"comment": "URL path filters for non-article content"},)


class ArticleEntity(Base):
    """Structured entity extraction aligned with gazetteer categories."""

    __tablename__ = "article_entities"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id = Column(
        String,
        ForeignKey("articles.id"),
        nullable=False,
        index=True,
    )
    article_text_hash = Column(String, index=True)

    entity_text = Column(String, nullable=False)
    entity_norm = Column(String, index=True)
    entity_label = Column(String, index=True)
    osm_category = Column(String, index=True)
    osm_subcategory = Column(String)

    extractor_version = Column(String, index=True)
    confidence = Column(Float)
    matched_gazetteer_id = Column(
        String,
        ForeignKey("gazetteer.id"),
        index=True,
    )
    match_score = Column(Float)
    match_name = Column(String)
    meta = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    article = relationship("Article", back_populates="entities")
    gazetteer_entry = relationship("Gazetteer")

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "entity_norm",
            "entity_label",
            "extractor_version",
            name="uq_article_entity",
        ),
    )


class Job(Base):
    """Job execution metadata and audit trail."""

    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Job identification
    job_type = Column(
        String,
        nullable=False,
    )
    job_name = Column(String)

    # Execution tracking
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    exit_status = Column(String)  # 'success', 'failed', 'cancelled'

    # Parameters and context
    params: Mapped[dict | None] = mapped_column(JSON)  # Input parameters
    commit_sha = Column(String)  # Git commit for reproducibility
    environment: Mapped[dict | None] = mapped_column(
        JSON
    )  # Python version, dependencies, etc.

    # Artifacts and outputs
    artifact_paths: Mapped[dict | None] = mapped_column(JSON)  # Snapshot file paths
    logs_path = Column(String)

    # Metrics
    records_processed = Column(Integer)
    records_created = Column(Integer)
    records_updated = Column(Integer)
    errors_count = Column(Integer)

    # Relationships
    ml_results = relationship("MLResult", back_populates="job")


class Dataset(Base):
    """Represents an ingested source dataset (CSV, export, etc.)."""

    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = Column(String, unique=True, index=True, nullable=False)
    # Human-visible unique label for UI/search convenience
    label = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    description = Column(Text)
    # Use a server_default so raw SQL INSERTs (e.g. in SQLite tests) that
    # omit `ingested_at` receive a timestamp. Keep Python-side default for
    # ORM-created objects as well.
    ingested_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    ingested_by = Column(String)
    # `metadata` is a reserved attribute on Declarative classes; store JSON
    # in the DB column named 'metadata' but expose it as `meta` on the model.
    meta = Column("metadata", JSON)
    is_public = Column(Boolean, default=False)
    # Control whether this dataset should be included in automated cron jobs
    # False = manual processing only (e.g., custom source lists)
    # True = include in automated discovery/extraction jobs
    # Ensure database-level default so raw INSERTs (used in tests) that
    # omit this column will still succeed. Use server_default '1' which
    # works for SQLite and PostgreSQL (interpreted as true-ish).
    cron_enabled = Column(
        Boolean,
        default=True,
        nullable=False,
        server_default=text("TRUE"),
    )
    # Timestamp for dataset creation (present in older SQLite test schema)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Source(Base):
    """Normalized publisher / site record."""

    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    host = Column(String, index=True, nullable=False)
    # Normalized lowercased host for uniqueness/deduplication
    host_norm = Column(
        String,
        index=True,
        unique=True,
        nullable=False,
    )
    canonical_name = Column(String, index=True)
    city = Column(String, index=True)
    county = Column(String, index=True)
    owner = Column(String)
    type = Column(String)
    # Stored in DB as `metadata` column; attribute named `meta` to avoid
    # conflict with SQLAlchemy's class-level `metadata` attribute.
    meta = Column("metadata", JSON)

    # Typed RSS / discovery state columns replacing JSON metadata keys
    rss_consecutive_failures = Column(Integer, nullable=False, default=0)
    rss_transient_failures = Column(JSON, nullable=False, default=list)
    rss_missing_at = Column(DateTime, nullable=True)
    rss_last_failed_at = Column(DateTime, nullable=True)
    last_successful_method = Column(String(32), nullable=True)
    no_effective_methods_consecutive = Column(Integer, nullable=False, default=0)
    no_effective_methods_last_seen = Column(DateTime, nullable=True)

    # Site management fields for pause/resume functionality
    status = Column(String, default="active", index=True)
    paused_at = Column(DateTime)
    paused_reason = Column(Text)

    # Bot sensitivity tracking for adaptive crawling behavior
    bot_sensitivity = Column(Integer, default=5, index=True)
    bot_sensitivity_updated_at = Column(DateTime)
    bot_encounters = Column(Integer, default=0)
    last_bot_detection_at = Column(DateTime, index=True)
    bot_detection_metadata = Column(JSON)

    # Bot protection detection - specific protection types require special extraction
    # Values: 'perimeterx', 'cloudflare', 'datadome', 'akamai', 'incapsula', etc.
    bot_protection_type = Column(String(64), nullable=True, index=True)
    # Extraction method for this source: 'http' (default), 'selenium', 'unblock'
    # 'unblock' routes traffic through the Squid residential proxy tier
    extraction_method = Column(
        String(32), default="http", nullable=False, server_default=text("'http'")
    )
    # Discovery proxy for sources with bot detection on homepage/RSS
    # Values: NULL (no proxy), 'squid', 'selenium_proxy' (uses SELENIUM_PROXY env var)
    # When set, discovery methods will route requests through specified proxy
    discovery_proxy = Column(String(32), nullable=True, index=True)
    # Legacy field - kept for backward compatibility, maps to extraction_method
    selenium_only = Column(
        Boolean, default=False, nullable=False, server_default=text("0")
    )
    bot_protection_detected_at = Column(DateTime, nullable=True)

    # Section discovery for enhanced news coverage
    # Stores discovered section URLs with performance metrics
    discovered_sections = Column(JSON, nullable=True)
    section_discovery_enabled = Column(
        Boolean, default=True, nullable=False, server_default=text("1")
    )
    section_last_updated = Column(DateTime, nullable=True)

    # Relationships
    broadcaster_callsigns = relationship(
        "LocalBroadcasterCallsign",
        back_populates="source",
        cascade="all, delete-orphan",
    )

    # Backref to candidate links
    # candidate_links = relationship('CandidateLink', backref='source')


class DatasetSource(Base):
    """Mapping between a Dataset and a Source preserving legacy_host_id."""

    __tablename__ = "dataset_sources"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        # Note: server_default removed for SQLite test compatibility
        # Python-side default works for both PostgreSQL and SQLite
    )
    dataset_id = Column(
        String,
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    source_id = Column(
        String,
        ForeignKey("sources.id"),
        nullable=False,
        index=True,
    )
    legacy_host_id = Column(String, nullable=True, index=True)
    legacy_meta = Column(JSON)

    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "legacy_host_id",
            name="uq_dataset_legacy_host",
        ),
        UniqueConstraint("dataset_id", "source_id", name="uq_dataset_source"),
    )


class Gazetteer(Base):
    """OSM-derived gazetteer entries scoped to dataset + source.

    Stores places (businesses, landmarks, institutions) discovered via
    the OSM Overpass/Nominatim APIs and links them to a dataset and the
    canonical `Source` record. This is used by publisher-specific
    geographic helpers to seed local entity lists.
    """

    __tablename__ = "gazetteer"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id = Column(
        String,
        ForeignKey("datasets.id"),
        nullable=True,
        index=True,
    )
    dataset_label = Column(String, index=True)
    source_id = Column(
        String,
        ForeignKey("sources.id"),
        nullable=True,
        index=True,
    )
    # Additional keys linking back to original ingest/data model
    data_id = Column(String, nullable=True, index=True)
    host_id = Column(String, nullable=True, index=True)

    # OSM identifiers
    osm_type = Column(String, index=True)  # node/way/relation
    osm_id = Column(String, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_norm: Mapped[str | None] = mapped_column(String, index=True)
    category = Column(
        String,
        index=True,
    )  # high-level type (e.g., school, hospital)

    # Geolocation
    lat = Column(Float, index=True)
    lon = Column(Float, index=True)

    # Raw tags and metadata from OSM for later inspection
    tags: Mapped[dict | None] = mapped_column(JSON)

    # Distance from publisher centroid (miles) if computed
    distance_miles = Column(Float)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "dataset_id",
            "osm_type",
            "osm_id",
            name="uq_gazetteer_source_dataset_osm",
        ),
    )


class GeocodeCache(Base):
    """Cache geocode lookups to avoid repeated external calls.

    Keyed by provider + normalized_input. Implements simple status and
    attempt bookkeeping for safe concurrent use via INSERT-then-UPDATE
    claim semantics from the application.
    """

    __tablename__ = "geocode_cache"

    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False, index=True)
    input = Column(Text, nullable=False)
    normalized_input = Column(String, nullable=False, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    precision = Column(String, nullable=True)
    raw_response = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="in_progress")
    error = Column(Text, nullable=True)
    attempt_count = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "normalized_input",
            name="uq_geocode_provider_norm",
        ),
    )


class BackgroundProcess(Base):
    """Track background processes and their execution status.

    Provides telemetry and monitoring for long-running tasks like
    gazetteer population, bulk crawling, etc.
    """

    __tablename__ = "background_processes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Process identification
    process_type = Column(String, nullable=False, index=True)
    command = Column(String, nullable=False)  # Full command line
    pid = Column(Integer, nullable=True, index=True)  # OS process ID

    # Status tracking (typed for ORM instances)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="started", index=True
    )
    progress_current: Mapped[int] = mapped_column(
        Integer, default=0
    )  # Current progress count
    progress_total: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Total expected items
    progress_message: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Human-readable status

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Results and metrics
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata for filtering/grouping
    dataset_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    process_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Parent process tracking (for spawned sub-processes)
    parent_process_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("background_processes.id"), nullable=True
    )

    @property
    def progress_percentage(self):
        """Calculate progress as percentage (0-100)."""
        total = self.progress_total
        if total is None or total == 0:
            return None
        current = int(self.progress_current or 0)
        return min(100, (current / total) * 100)

    @property
    def duration_seconds(self):
        """Calculate duration in seconds."""
        end_time = self.completed_at or datetime.utcnow()
        return (end_time - self.started_at).total_seconds()

    @property
    def is_active(self):
        """Check if process is still active."""
        status_value = self.status
        return status_value in {"started", "running"}

    def update_progress(
        self,
        current: int,
        message: str | None = None,
        total: int | None = None,
    ):
        """Update progress counters and message."""
        self.progress_current = current
        if total is not None:
            self.progress_total = total
        if message:
            self.progress_message = message
        self.updated_at = datetime.utcnow()
        status_value = self.status
        if status_value == "started":
            self.status = "running"


# Database utilities


def create_database_engine(database_url: str = "sqlite:///data/mizzou.db"):
    """Create SQLAlchemy engine with proper configuration."""
    if database_url.startswith("sqlite"):
        # SQLite-specific optimizations
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            echo=False,
        )
    else:
        # PostgreSQL configuration for production
        engine = create_engine(
            database_url,
            pool_size=20,
            max_overflow=30,
            pool_timeout=30,
            echo=False,
        )

    return engine


def create_engine_from_env():
    """Create SQLAlchemy engine from DATABASE_URL environment variable.

    This is the recommended way to create database engines in the application,
    as it respects the centralized configuration in src/config.py.

    Returns:
        Engine: Configured SQLAlchemy engine

    Example:
        >>> from src.models import create_engine_from_env, create_tables
        >>> engine = create_engine_from_env()
        >>> create_tables(engine)
    """
    from src.config import DATABASE_URL

    return create_database_engine(DATABASE_URL)


def create_tables(engine):
    """Create all tables in the database from both main and telemetry bases."""
    Base.metadata.create_all(engine)
    # Also create telemetry tables (separate Base)
    from src.models.telemetry_orm import Base as TelemetryBase

    TelemetryBase.metadata.create_all(engine)


def get_session(engine):
    """Get a database session."""
    Session = sessionmaker(bind=engine)
    return Session()


# Example usage and testing
if __name__ == "__main__":
    # Create in-memory SQLite for testing
    engine = create_database_engine("sqlite:///:memory:")
    create_tables(engine)

    session = get_session(engine)

    # Create a test candidate link
    link = CandidateLink(
        url="https://example.com/test-article",
        source="example.com",
        discovered_by="test",
    )
    session.add(link)
    session.commit()

    print(f"Created candidate link: {link.id}")

    # Create a test article
    article = Article(
        candidate_link_id=link.id,
        title="Test Article",
        text="This is a test article content.",
        text_hash="abc123",
        text_excerpt="This is a test...",
    )
    session.add(article)
    session.commit()

    print(f"Created article: {article.id}")

    session.close()
