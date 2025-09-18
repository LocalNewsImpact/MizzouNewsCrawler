"""SQLAlchemy database models for MizzouNewsCrawler-Scripts."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint, create_engine
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

Base = declarative_base()


class CandidateLink(Base):
    """Links discovered during crawling with fetch status tracking."""
    
    __tablename__ = 'candidate_links'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    url = Column(String, nullable=False, unique=True, index=True)
    source = Column(String, nullable=False)  # Site/publisher name
    discovered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    crawl_depth = Column(Integer, default=0)
    discovered_by = Column(String)  # Job/process that found this URL
    
    # Fetch status tracking
    status = Column(String, nullable=False, default='new', index=True)  
    # new/in_progress/fetched/failed/skipped
    fetched_at = Column(DateTime)
    http_status = Column(Integer)
    content_hash = Column(String, index=True)  # SHA256 of raw content
    
    # Flexible metadata storage
    metadata = Column(JSON)  # Headers, redirect chain, etc.
    
    # Relationships
    articles = relationship("Article", back_populates="candidate_link")
    
    __table_args__ = (
        UniqueConstraint('url', name='uq_candidate_links_url'),
    )


class Article(Base):
    """Parsed article content and metadata."""
    
    __tablename__ = 'articles'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String, ForeignKey('candidate_links.id'), nullable=False)
    
    # Core content
    title = Column(Text)
    author = Column(String)
    published_at = Column(DateTime)
    text = Column(Text)
    text_hash = Column(String, index=True)  # SHA256 of normalized text
    text_excerpt = Column(String(500))  # First 500 chars for preview
    
    # Storage references
    raw_gcs_path = Column(String)  # Future: GCS path for raw HTML
    
    # Processing metadata
    extracted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    extraction_version = Column(String)  # Version of parsing logic
    
    # Relationships
    candidate_link = relationship("CandidateLink", back_populates="articles")
    ml_results = relationship("MLResult", back_populates="article")
    locations = relationship("Location", back_populates="article")


class MLResult(Base):
    """Machine learning classification and labeling results."""
    
    __tablename__ = 'ml_results'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id = Column(String, ForeignKey('articles.id'), nullable=False)
    
    # Model information
    model_version = Column(String, nullable=False)
    model_type = Column(String, nullable=False)  # 'classifier', 'ner', etc.
    
    # Results
    label = Column(String)
    score = Column(Float)
    confidence = Column(Float)
    
    # Processing metadata
    run_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    job_id = Column(String, ForeignKey('jobs.id'))
    
    # Detailed results
    details = Column(JSON)  # Full model output, features, etc.
    
    # Relationships
    article = relationship("Article", back_populates="ml_results")
    job = relationship("Job", back_populates="ml_results")


class Location(Base):
    """Named entity recognition and geocoding results."""
    
    __tablename__ = 'locations'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id = Column(String, ForeignKey('articles.id'), nullable=False)
    
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


class Job(Base):
    """Job execution metadata and audit trail."""
    
    __tablename__ = 'jobs'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Job identification
    job_type = Column(String, nullable=False)  # 'crawler', 'parser', 'ml', etc.
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


# Database utilities

def create_database_engine(database_url: str = "sqlite:///data/mizzou.db"):
    """Create SQLAlchemy engine with proper configuration."""
    if database_url.startswith('sqlite'):
        # SQLite-specific optimizations
        engine = create_engine(
            database_url,
            connect_args={
                "check_same_thread": False,
                "timeout": 30
            },
            echo=False
        )
    else:
        # PostgreSQL configuration for production
        engine = create_engine(
            database_url,
            pool_size=20,
            max_overflow=30,
            pool_timeout=30,
            echo=False
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
        discovered_by="test"
    )
    session.add(link)
    session.commit()
    
    print(f"Created candidate link: {link.id}")
    
    # Create a test article
    article = Article(
        candidate_id=link.id,
        title="Test Article",
        text="This is a test article content.",
        text_hash="abc123",
        text_excerpt="This is a test..."
    )
    session.add(article)
    session.commit()
    
    print(f"Created article: {article.id}")
    
    session.close()