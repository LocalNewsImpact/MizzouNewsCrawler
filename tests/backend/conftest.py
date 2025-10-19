"""Pytest fixtures for backend API testing (Issue #44).

This module provides test fixtures for testing the migrated API endpoints
that now query Cloud SQL instead of reading CSV files.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.main import app  # noqa: E402
from src.models import Article, Source  # noqa: E402
from src.models.api_backend import Candidate, Review, Snapshot  # noqa: E402
from src.models.database import Base  # noqa: E402


@pytest.fixture(scope="function")
def db_engine():
    """Create in-memory SQLite database for testing.
    
    Creates a fresh database for each test function to ensure isolation.
    All tables are created from SQLAlchemy models.
    Uses check_same_thread=False to allow multi-threaded access.
    Uses StaticPool to ensure all connections share the same in-memory db.
    """
    from sqlalchemy.pool import StaticPool
    
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Share the same connection across threads
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Session:
    """Create database session for tests.
    
    Provides a session for fixture setup that shares the same
    in-memory database with the test client.
    """
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_client(db_engine, monkeypatch):
    """Create FastAPI test client with mocked database engine.
    
    This client uses the test database engine instead of production.
    By mocking at the engine level and using StaticPool, we ensure
    all sessions (both fixture and endpoint) see the same data.
    """
    from contextlib import contextmanager

    from backend.app import main

    # Mock the DatabaseManager's engine with our test engine
    monkeypatch.setattr(main.db_manager, "engine", db_engine)
    
    # Mock get_session to use the test engine
    @contextmanager
    def mock_get_session_context():
        SessionLocal = sessionmaker(bind=db_engine)
        session = SessionLocal()
        try:
            yield session
            session.commit()  # Commit so changes are visible
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def mock_get_session():
        return mock_get_session_context()
    
    monkeypatch.setattr(main.db_manager, "get_session", mock_get_session)
    
    client = TestClient(app)
    return client


@pytest.fixture
def sample_sources(db_session) -> List[Source]:
    """Create sample news sources for testing.
    
    Uses actual Cloud SQL Source schema:
    - host: domain name
    - host_norm: normalized lowercase domain
    - canonical_name: display name
    - county: geographic county
    """
    sources = [
        Source(
            id="source-1",
            host="columbiatribune.com",
            host_norm="columbiatribune.com",
            canonical_name="Columbia Daily Tribune",
            county="Boone",
            status="active",
        ),
        Source(
            id="source-2",
            host="newstribune.com",
            host_norm="newstribune.com",
            canonical_name="Jefferson City News Tribune",
            county="Cole",
            status="active",
        ),
        Source(
            id="source-3",
            host="audraincountynews.com",
            host_norm="audraincountynews.com",
            canonical_name="Audrain County News",
            county="Audrain",
            status="active",
        ),
    ]
    
    for source in sources:
        db_session.add(source)
    db_session.commit()
    
    return sources


@pytest.fixture
def sample_candidate_links(db_session, sample_sources) -> List:
    """Create sample candidate links for articles.
    
    CandidateLink connects articles to sources in Cloud SQL schema.
    """
    from src.models import CandidateLink
    
    links = []
    for i, source in enumerate(sample_sources):
        link = CandidateLink(
            id=f"link-{i}",
            url=f"https://{source.host}/article-{i}",
            source=source.host,
            source_host_id=source.host,
            source_name=source.canonical_name,
            source_county=source.county,
        )
        links.append(link)
        db_session.add(link)
    
    db_session.commit()
    return links


@pytest.fixture
def sample_articles(
    db_session, sample_sources, sample_candidate_links
) -> List[Article]:
    """Create sample articles for testing.
    
    Creates 50 test articles using actual Cloud SQL schema:
    - candidate_link_id: FK to candidate_links table
    - wire: JSON array of wire service attributions
    - status: article processing status
    - No direct source_id or county (comes from candidate_link)
    """
    import json
    articles = []
    base_date = datetime.now()
    
    for i in range(50):
        # Rotate through candidate links
        link = sample_candidate_links[i % 3]
        
        # ~14% have wire service attribution
        wire_data = None
        if i % 7 == 0:
            wire_data = json.dumps([
                {"source": "AP", "confidence": 0.9}
            ])
        
        article = Article(
            id=f"article-{i:03d}",
            title=f"Test Article {i}: Local News Story",
            url=f"https://example.com/article-{i}",
            candidate_link_id=link.id,
            publish_date=base_date - timedelta(days=i),
            content=(
                f"This is test article content for article {i}. "
                f"It contains relevant local news information."
            ),
            author=f"Test Author {i % 5}",  # 5 different authors
            wire=wire_data,
            status="extracted",
        )
        articles.append(article)
        db_session.add(article)
    
    db_session.commit()
    return articles


@pytest.fixture
def sample_reviews(db_session, sample_articles) -> List[Review]:
    """Create sample reviews for testing.
    
    Creates 20 reviews across the first 20 articles.
    - Two reviewers: user1 and user2
    - Varied ratings (3-5)
    - Some with notes and tags
    - Uses article_uid (Article.id in Cloud SQL)
    """
    reviews = []
    
    for i in range(20):
        reviewer = "user1" if i % 2 == 0 else "user2"
        rating = 3 + (i % 3)  # Ratings: 3, 4, 5
        
        review = Review(
            id=f"review-{i:03d}",
            article_uid=sample_articles[i].id,  # Use Article.id
            article_idx=i,
            reviewer=reviewer,
            rating=rating,
            notes=f"Review notes for article {i}" if i % 3 == 0 else None,
            tags='["local", "politics"]' if i % 4 == 0 else '[]',
            created_at=datetime.now() - timedelta(hours=i),
            reviewed_at=datetime.now() - timedelta(hours=i, minutes=30),
        )
        reviews.append(review)
        db_session.add(review)
    
    db_session.commit()
    return reviews


@pytest.fixture
def sample_snapshots(db_session, sample_sources) -> List[Snapshot]:
    """Create sample HTML snapshots for testing.
    
    Snapshot model stores HTML snapshots captured during extraction.
    Fields: id, host, url, path, pipeline_run_id, failure_reason,
            parsed_fields, model_confidence, status, created_at, reviewed_at
    """
    snapshots = []
    
    for i in range(10):
        reviewed_time = (
            datetime.now() - timedelta(days=i, hours=12)
            if i % 3 == 0
            else None
        )
        source = sample_sources[i % len(sample_sources)]
        snapshot = Snapshot(
            id=f"snapshot-{i:03d}",
            host=source.host,
            url=f"https://{source.host}/article/{i}",
            path=f"/snapshots/{source.host}/{i}.html",
            pipeline_run_id=f"pipeline-run-{i // 3}",
            parsed_fields='{"title": "Article", "author": "John Doe"}',
            model_confidence=0.85 - (i * 0.02),
            status="reviewed" if i % 3 == 0 else "pending",
            created_at=datetime.now() - timedelta(days=i),
            reviewed_at=reviewed_time,
        )
        snapshots.append(snapshot)
        db_session.add(snapshot)
    
    db_session.commit()
    return snapshots


@pytest.fixture
def sample_candidates(db_session, sample_snapshots) -> List[Candidate]:
    """Create sample extraction candidates for testing.
    
    Candidate model is for field extraction selectors, not news issues.
    Fields: id, snapshot_id, selector, field, score, words, snippet, alts, accepted.
    """
    candidates = []
    
    for i in range(8):
        candidate = Candidate(
            id=f"candidate-{i:03d}",
            snapshot_id=sample_snapshots[i % len(sample_snapshots)].id,
            selector=f"article > div.content > p:nth-child({i+1})",
            field="content",
            score=0.85 - (i * 0.05),
            words=150 + (i * 10),
            snippet=f"Sample extracted content snippet {i}...",
            alts=None,
            accepted=(i % 3 == 0),  # Every 3rd is accepted
        )
        candidates.append(candidate)
        db_session.add(candidate)
    
    db_session.commit()
    return candidates


@pytest.fixture
def large_article_dataset(
    db_session, sample_sources, sample_candidate_links
) -> List[Article]:
    """Create large dataset for pagination and load testing.
    
    Creates 500 articles for testing pagination, load, and performance.
    """
    import json
    articles = []
    base_date = datetime.now()
    
    for i in range(500):
        link = sample_candidate_links[i % 3]
        
        # ~10% wire service
        wire_data = None
        if i % 10 == 0:
            wire_data = json.dumps([{"source": "AP", "confidence": 0.9}])
        
        article = Article(
            id=f"large-article-{i:04d}",
            title=f"Large Dataset Article {i}",
            url=f"https://example.com/large-{i}",
            candidate_link_id=link.id,
            publish_date=base_date - timedelta(days=i // 10),  # Group by date
            content=f"Content for large dataset article {i}",
            wire=wire_data,
            status="extracted",
        )
        articles.append(article)
        db_session.add(article)
        
        # Commit in batches for performance
        if (i + 1) % 100 == 0:
            db_session.commit()
    
    db_session.commit()
    return articles


# Integration test fixtures (require Cloud SQL)

@pytest.fixture(scope="session")
def cloud_sql_engine():
    """Create engine for Cloud SQL integration tests.
    
    Requires TEST_DATABASE_URL environment variable.
    Only used for integration tests marked with @pytest.mark.integration
    """
    import os
    
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping Cloud SQL tests")
    
    engine = create_engine(test_db_url, echo=False)
    
    # Verify connection
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Cannot connect to test database: {e}")
    
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def cloud_sql_session(cloud_sql_engine):
    """Create session for Cloud SQL integration tests.
    
    Uses transactions to ensure test isolation and cleanup.
    """
    connection = cloud_sql_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()
