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
from sqlalchemy.orm import sessionmaker

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.main import app  # noqa: E402
from src.models import Article, Source  # noqa: E402
from src.models.api_backend import Candidate, Review, Snapshot  # noqa: E402


@pytest.fixture
def test_client(cloud_sql_session, monkeypatch):
    """Create FastAPI test client with mocked database engine.

    This client uses the PostgreSQL test database instead of production.
    CRITICAL: Uses the same session as fixtures to ensure data visibility.
    """
    import os
    from contextlib import contextmanager

    # Get the engine from the cloud_sql_session
    cloud_sql_engine = cloud_sql_session.get_bind().engine

    # Get TEST_DATABASE_URL (SQLAlchemy masks password in str(url))
    engine_url = os.getenv("TEST_DATABASE_URL")
    if not engine_url:
        pytest.skip("TEST_DATABASE_URL not set")

    # Mock DATABASE_URL in app_config BEFORE db_manager is initialized
    from backend.app import main

    monkeypatch.setattr(main.app_config, "DATABASE_URL", engine_url)

    # Reset _db_manager to force re-initialization with new URL
    main._db_manager = None

    # Now mock the engine to use our test engine
    # (db_manager will be created lazily with the mocked URL)
    monkeypatch.setattr(main.db_manager, "engine", cloud_sql_engine)

    # Mock get_session to use the SAME session as fixtures
    # This ensures test_client sees data committed by fixtures
    @contextmanager
    def mock_get_session_context():
        try:
            yield cloud_sql_session
            # Don't commit here - let the fixture handle transaction management
        except Exception:
            raise

    def mock_get_session():
        return mock_get_session_context()

    monkeypatch.setattr(main.db_manager, "get_session", mock_get_session)

    client = TestClient(app)
    return client


@pytest.fixture
def sample_sources(cloud_sql_session) -> list[Source]:
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
        cloud_sql_session.add(source)
    cloud_sql_session.flush()  # Flush to DB but don't commit transaction

    return sources


@pytest.fixture
def sample_candidate_links(cloud_sql_session, sample_sources) -> list:
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
        cloud_sql_session.add(link)

    cloud_sql_session.flush()  # Flush to DB without committing transaction
    return links


@pytest.fixture
def sample_articles(
    cloud_sql_session, sample_sources, sample_candidate_links
) -> list[Article]:
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
            wire_data = json.dumps([{"source": "AP", "confidence": 0.9}])

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
        cloud_sql_session.add(article)

    cloud_sql_session.flush()  # Flush to DB without committing transaction
    return articles


@pytest.fixture
def sample_reviews(cloud_sql_session, sample_articles) -> list[Review]:
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
            tags='["local", "politics"]' if i % 4 == 0 else "[]",
            created_at=datetime.now() - timedelta(hours=i),
            reviewed_at=datetime.now() - timedelta(hours=i, minutes=30),
        )
        reviews.append(review)
        cloud_sql_session.add(review)

    cloud_sql_session.flush()  # Flush to DB without committing transaction
    return reviews


@pytest.fixture
def sample_snapshots(cloud_sql_session, sample_sources) -> list[Snapshot]:
    """Create sample HTML snapshots for testing.

    Snapshot model stores HTML snapshots captured during extraction.
    Fields: id, host, url, path, pipeline_run_id, failure_reason,
            parsed_fields, model_confidence, status, created_at, reviewed_at
    """
    snapshots = []

    for i in range(10):
        reviewed_time = (
            datetime.now() - timedelta(days=i, hours=12) if i % 3 == 0 else None
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
        cloud_sql_session.add(snapshot)

    cloud_sql_session.flush()  # Flush to DB without committing transaction
    return snapshots


@pytest.fixture
def sample_candidates(cloud_sql_session, sample_snapshots) -> list[Candidate]:
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
        cloud_sql_session.add(candidate)

    cloud_sql_session.flush()  # Flush to DB without committing transaction
    return candidates


@pytest.fixture
def large_article_dataset(
    cloud_sql_session, sample_sources, sample_candidate_links
) -> list[Article]:
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
        cloud_sql_session.add(article)

        # Commit in batches for performance
        if (i + 1) % 100 == 0:
            cloud_sql_session.flush()  # Flush to DB without committing transaction

    cloud_sql_session.flush()  # Flush to DB without committing transaction
    return articles


# Integration test fixtures (require Cloud SQL)


@pytest.fixture(scope="function")
def cloud_sql_engine():
    """Create engine for Cloud SQL integration tests.

    Requires TEST_DATABASE_URL environment variable.
    Only used for integration tests marked with @pytest.mark.integration

    Changed to function scope to match tests/integration/conftest.py
    for consistency and to avoid connection pooling issues.
    """
    import os

    test_db_url = os.getenv("TEST_DATABASE_URL")
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping Cloud SQL tests")

    # Replace 'localhost' with '127.0.0.1' to avoid IPv6 resolution issues
    # psycopg2 tries IPv6 (::1) first when given 'localhost', which may have
    # different auth configuration than IPv4
    # Handle both @localhost/ and @localhost:port/ patterns
    test_db_url = test_db_url.replace("@localhost:", "@127.0.0.1:")
    test_db_url = test_db_url.replace("@localhost/", "@127.0.0.1/")

    engine = create_engine(test_db_url, echo=False)

    # Verify connection and ensure test schema is migrated to head
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

            # Check if new typed RSS columns exist; if not, run Alembic upgrade
            col_check = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'sources'
                      AND column_name = 'rss_consecutive_failures'
                    LIMIT 1
                    """
                )
            ).fetchone()

        if not col_check:
            # Point Alembic at the test database URL and upgrade to head
            import os
            from pathlib import Path

            from alembic import command
            from alembic.config import Config

            # Ensure Alembic uses the test DB URL
            alembic_ini = str(Path(__file__).resolve().parents[2] / "alembic.ini")
            cfg = Config(alembic_ini)
            script_loc = str(Path(alembic_ini).parent / "alembic")
            cfg.set_main_option("script_location", script_loc)
            cfg.set_main_option("sqlalchemy.url", test_db_url)

            # Some environments rely on DATABASE_URL in env.py; set it to the test URL
            os.environ["DATABASE_URL"] = test_db_url

            command.upgrade(cfg, "head")
    except Exception as e:
        pytest.skip(f"Cannot connect or migrate test database: {e}")

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
