"""SQLAlchemy database models for MizzouNewsCrawler-Scripts."""

import uuid
from datetime import datetime
from typing import Optional, cast

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
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class CandidateLink(Base):
    """Links discovered during crawling with fetch status tracking."""

    __tablename__ = "candidate_links"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
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
    meta = Column(JSON)  # Headers, redirect chain, etc.
    # First-class publish date for candidate links (nullable)
    publish_date = Column(DateTime, nullable=True, index=True)
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
    processed_at = Column(DateTime)
    articles_found = Column(Integer, default=0)
    error_message = Column(String)
    # Allow raw SQL INSERTs to omit created_at by using a server default
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    # Link to dataset and normalized source
    dataset_id = Column(String, index=True)
    source_id = Column(String, index=True)

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
    url = Column(String, index=True)
    title = Column(Text)
    author = Column(String)
    publish_date = Column(DateTime)
    content = Column(Text)
    # Keep older 'text' fields for compatibility
    text = Column(Text)
    text_hash = Column(String, index=True)  # SHA256 of normalized text
    text_excerpt = Column(String(500))  # First 500 chars for preview

    # Status and metadata used by CLI workflows
    status = Column(String, nullable=False, default="discovered", index=True)
    # `metadata` is a reserved attribute name on Declarative classes; expose
    # it on the DB row as the column name but use the attribute `meta` here.
    meta = Column("metadata", JSON)
    # Wire service attribution payload stored as JSON for downstream reports
    wire = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Storage references
    raw_gcs_path = Column(String)  # Future: GCS path for raw HTML

    # Processing metadata
    extracted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    extraction_version = Column(String)  # Version of parsing logic
    # Classification outputs
    primary_label = Column(String)
    primary_label_confidence = Column(Float)
    alternate_label = Column(String)
    alternate_label_confidence = Column(Float)
    label_version = Column(String, index=True)
    label_model_version = Column(String)
    labels_updated_at = Column(DateTime)

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
    primary_label = Column(String, nullable=False)
    primary_label_confidence = Column(Float)
    alternate_label = Column(String)
    alternate_label_confidence = Column(Float)
    applied_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    meta = Column(JSON)

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
    label = Column(String)
    score = Column(Float)
    confidence = Column(Float)

    # Processing metadata
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    job_id = Column(String, ForeignKey("jobs.id"))

    # Detailed results
    details = Column(JSON)  # Full model output, features, etc.

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
    params = Column(JSON)  # Input parameters
    commit_sha = Column(String)  # Git commit for reproducibility
    environment = Column(JSON)  # Python version, dependencies, etc.

    # Artifacts and outputs
    artifact_paths = Column(JSON)  # Snapshot file paths
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
    ingested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ingested_by = Column(String)
    # `metadata` is a reserved attribute on Declarative classes; store JSON
    # in the DB column named 'metadata' but expose it as `meta` on the model.
    meta = Column("metadata", JSON)
    is_public = Column(Boolean, default=False)


class Source(Base):
    """Normalized publisher / site record."""

    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    host = Column(String, index=True, nullable=False)
    # Normalized lowercased host for uniqueness/deduplication
    host_norm = Column(String, index=True, unique=True, nullable=False)
    canonical_name = Column(String, index=True)
    city = Column(String, index=True)
    county = Column(String, index=True)
    owner = Column(String)
    type = Column(String)
    # Stored in DB as `metadata` column; attribute named `meta` to avoid
    # conflict with SQLAlchemy's class-level `metadata` attribute.
    meta = Column("metadata", JSON)

    # Backref to candidate links
    # candidate_links = relationship('CandidateLink', backref='source')


class DatasetSource(Base):
    """Mapping between a Dataset and a Source preserving legacy_host_id."""

    __tablename__ = "dataset_sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
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
    name = Column(String, nullable=False)
    name_norm = Column(String, index=True)
    category = Column(
        String,
        index=True,
    )  # high-level type (e.g., school, hospital)

    # Geolocation
    lat = Column(Float, index=True)
    lon = Column(Float, index=True)

    # Raw tags and metadata from OSM for later inspection
    tags = Column(JSON)

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

    # Status tracking
    status = Column(String, nullable=False, default="started", index=True)
    progress_current = Column(Integer, default=0)  # Current progress count
    progress_total = Column(Integer, nullable=True)  # Total expected items
    progress_message = Column(String, nullable=True)  # Human-readable status

    # Timing
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    completed_at = Column(DateTime, nullable=True)

    # Results and metrics
    result_summary = Column(JSON, nullable=True)  # Final results/statistics
    error_message = Column(Text, nullable=True)

    # Metadata for filtering/grouping
    dataset_id = Column(String, nullable=True, index=True)
    source_id = Column(String, nullable=True, index=True)
    process_metadata = Column(JSON, nullable=True)  # Additional context

    # Parent process tracking (for spawned sub-processes)
    parent_process_id = Column(
        String, ForeignKey("background_processes.id"), nullable=True
    )

    @property
    def progress_percentage(self):
        """Calculate progress as percentage (0-100)."""
        total = cast(int | None, self.progress_total)
        if total is None or total == 0:
            return None
        current = cast(int, self.progress_current or 0)
        return min(100, (current / total) * 100)

    @property
    def duration_seconds(self):
        """Calculate duration in seconds."""
        end_time = self.completed_at or datetime.utcnow()
        return (end_time - self.started_at).total_seconds()

    @property
    def is_active(self):
        """Check if process is still active."""
        status_value = cast(str | None, self.status)
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
        status_value = cast(str | None, self.status)
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


def create_tables(engine):
    """Create all tables in the database."""
    Base.metadata.create_all(engine)


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
