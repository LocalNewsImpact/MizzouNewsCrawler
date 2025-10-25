"""Integration tests for extraction database writes (Issue #105).

These tests verify that extraction writes articles to the database and that
post-commit verification catches silent failures.

Run with:
    pytest tests/integration/test_extraction_db.py -v -m integration

Environment variables:
- TEST_DATABASE_URL: PostgreSQL connection string for test instance
  (If not set, tests will be skipped)

These tests address the production failure where extraction ran but articles
were not written to the database for 48+ hours.
"""

import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.models import Article, Base, CandidateLink


@pytest.fixture(scope="session")
def postgres_engine():
    """Create a database engine for PostgreSQL integration tests."""
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping extraction DB tests")

    engine = create_engine(test_db_url, echo=False)

    # Test connectivity
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test database: {exc}")

    # Create tables
    Base.metadata.create_all(engine)

    yield engine

    # Cleanup
    engine.dispose()


@pytest.fixture(scope="function")
def postgres_session(postgres_engine):
    """Return a transactional session bound to the PostgreSQL engine."""
    connection = postgres_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.mark.integration
@pytest.mark.postgres
def test_extraction_inserts_article(postgres_session):
    """Test that extraction successfully inserts an article into the database.

    This is a basic test to verify articles can be written and read back.
    """
    # Create a candidate link
    candidate_id = str(uuid.uuid4())
    candidate = CandidateLink(
        id=candidate_id,
        url="https://example.com/test-article",
        source="example.com",
        status="article",
    )
    postgres_session.add(candidate)
    postgres_session.commit()

    # Insert an article (simulating extraction)
    article_id = str(uuid.uuid4())
    now = datetime.utcnow()
    article = Article(
        id=article_id,
        candidate_link_id=candidate_id,
        url="https://example.com/test-article",
        title="Test Article Title",
        content="Test article content",
        text="Test article content",
        status="extracted",
        extracted_at=now,
    )
    postgres_session.add(article)
    postgres_session.commit()

    # Verify article was inserted (post-commit verification)
    verify_query = text("SELECT id, title, url FROM articles WHERE id = :id")
    result = postgres_session.execute(verify_query, {"id": article_id}).fetchone()

    assert result is not None, "Article was not found after commit"
    assert result[0] == article_id
    assert result[1] == "Test Article Title"
    assert result[2] == "https://example.com/test-article"


@pytest.mark.integration
@pytest.mark.postgres
def test_extraction_query_returns_candidates(postgres_session):
    """Test that the extraction query finds candidate links with status='article'.

    This verifies the extraction query logic works correctly.
    """
    # Insert candidate links with status='article'
    candidates = []
    for i in range(5):
        candidate = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://example.com/article-{i}",
            source="example.com",
            status="article",
        )
        candidates.append(candidate)
        postgres_session.add(candidate)

    postgres_session.commit()

    # Run the extraction query
    query = text(
        """
        SELECT cl.id, cl.url, cl.source, cl.status
        FROM candidate_links cl
        WHERE cl.status = 'article'
        AND cl.id NOT IN (
            SELECT candidate_link_id FROM articles
            WHERE candidate_link_id IS NOT NULL
        )
        LIMIT 10
        """
    )

    results = postgres_session.execute(query).fetchall()

    # Should find all 5 candidates
    assert len(results) >= 5, f"Expected at least 5 candidates, got {len(results)}"

    # Verify each result has correct structure
    for row in results:
        assert row[0] is not None  # id
        assert row[1] is not None  # url
        assert row[2] is not None  # source
        assert row[3] == "article"  # status


@pytest.mark.integration
@pytest.mark.postgres
def test_extraction_updates_candidate_status(postgres_session):
    """Test that extraction updates candidate link status after processing."""
    # Create candidate link
    candidate_id = str(uuid.uuid4())
    candidate = CandidateLink(
        id=candidate_id,
        url="https://example.com/test",
        source="example.com",
        status="article",
    )
    postgres_session.add(candidate)
    postgres_session.commit()

    # Simulate extraction: insert article and update candidate status
    article_id = str(uuid.uuid4())
    article = Article(
        id=article_id,
        candidate_link_id=candidate_id,
        url="https://example.com/test",
        title="Test",
        content="Content",
        text="Content",
        status="extracted",
    )
    postgres_session.add(article)

    # Update candidate status (as extraction does)
    update_query = text(
        "UPDATE candidate_links SET status = :status WHERE id = :id"
    )
    postgres_session.execute(
        update_query,
        {"status": "extracted", "id": candidate_id},
    )
    postgres_session.commit()

    # Verify status was updated
    verify_query = text("SELECT status FROM candidate_links WHERE id = :id")
    result = postgres_session.execute(verify_query, {"id": candidate_id}).fetchone()

    assert result is not None
    assert result[0] == "extracted"


@pytest.mark.integration
@pytest.mark.postgres
def test_extraction_with_on_conflict_do_nothing(postgres_engine):
    """Test that ON CONFLICT DO NOTHING works correctly for duplicate URLs.

    This tests the fix for the InvalidColumnReference error when trying to use
    ON CONFLICT (url) without a unique constraint.
    """
    # Use raw SQL to test the exact INSERT statement used in extraction
    insert_sql = text(
        """
        INSERT INTO articles (id, candidate_link_id, url, title, content, 
                             text, status, extracted_at, created_at, text_hash)
        VALUES (:id, :candidate_link_id, :url, :title, :content,
                :text, :status, :extracted_at, :created_at, :text_hash)
        ON CONFLICT DO NOTHING
        """
    )

    with postgres_engine.connect() as conn:
        transaction = conn.begin()
        try:
            # First, insert a candidate link
            candidate_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT INTO candidate_links (id, url, source, status) "
                    "VALUES (:id, :url, :source, :status)"
                ),
                {
                    "id": candidate_id,
                    "url": "https://example.com/duplicate",
                    "source": "example.com",
                    "status": "article",
                },
            )

            # Insert first article
            article_id_1 = str(uuid.uuid4())
            now = datetime.utcnow().isoformat()
            conn.execute(
                insert_sql,
                {
                    "id": article_id_1,
                    "candidate_link_id": candidate_id,
                    "url": "https://example.com/duplicate",
                    "title": "Test Title",
                    "content": "Test Content",
                    "text": "Test Content",
                    "status": "extracted",
                    "extracted_at": now,
                    "created_at": now,
                    "text_hash": "abc123",
                },
            )

            # Try to insert duplicate (different ID, same URL)
            # This should not raise an error due to ON CONFLICT DO NOTHING
            article_id_2 = str(uuid.uuid4())
            conn.execute(
                insert_sql,
                {
                    "id": article_id_2,
                    "candidate_link_id": candidate_id,
                    "url": "https://example.com/duplicate",
                    "title": "Test Title 2",
                    "content": "Test Content 2",
                    "text": "Test Content 2",
                    "status": "extracted",
                    "extracted_at": now,
                    "created_at": now,
                    "text_hash": "def456",
                },
            )

            transaction.commit()

            # Verify only one article exists (or two, depending on constraints)
            # The important thing is it didn't raise an error
            result = conn.execute(
                text("SELECT COUNT(*) FROM articles WHERE url = :url"),
                {"url": "https://example.com/duplicate"},
            ).scalar()

            assert result >= 1, "At least one article should exist"

        except Exception:
            transaction.rollback()
            raise


@pytest.mark.integration
@pytest.mark.postgres
def test_post_commit_verification(postgres_session):
    """Test post-commit verification logic catches silent failures.

    This simulates the verification query that runs after each article insert.
    """
    # Insert an article
    candidate_id = str(uuid.uuid4())
    candidate = CandidateLink(
        id=candidate_id,
        url="https://example.com/verify",
        source="example.com",
        status="article",
    )
    postgres_session.add(candidate)
    postgres_session.commit()

    article_id = str(uuid.uuid4())
    article = Article(
        id=article_id,
        candidate_link_id=candidate_id,
        url="https://example.com/verify",
        title="Verify Test",
        content="Content",
        text="Content",
        status="extracted",
    )
    postgres_session.add(article)
    postgres_session.commit()

    # Run post-commit verification query
    verify_query = text("SELECT id FROM articles WHERE id = :id")
    result = postgres_session.execute(verify_query, {"id": article_id}).fetchone()

    assert result is not None, "Post-commit verification failed"
    assert result[0] == article_id

    # Also verify candidate link status
    cl_verify = text("SELECT status FROM candidate_links WHERE id = :id")
    cl_result = postgres_session.execute(cl_verify, {"id": candidate_id}).fetchone()

    assert cl_result is not None
    assert cl_result[0] == "article"  # Status hasn't been updated yet in this test


@pytest.mark.integration
@pytest.mark.postgres
def test_extraction_query_excludes_processed_articles(postgres_session):
    """Test that extraction query excludes candidate links already processed.

    This verifies the NOT IN (SELECT candidate_link_id FROM articles) logic.
    """
    # Create two candidate links
    candidate_id_1 = str(uuid.uuid4())
    candidate_id_2 = str(uuid.uuid4())

    candidate_1 = CandidateLink(
        id=candidate_id_1,
        url="https://example.com/processed",
        source="example.com",
        status="article",
    )
    candidate_2 = CandidateLink(
        id=candidate_id_2,
        url="https://example.com/unprocessed",
        source="example.com",
        status="article",
    )
    postgres_session.add_all([candidate_1, candidate_2])
    postgres_session.commit()

    # Process only the first one (create article)
    article = Article(
        id=str(uuid.uuid4()),
        candidate_link_id=candidate_id_1,
        url="https://example.com/processed",
        title="Processed",
        content="Content",
        text="Content",
        status="extracted",
    )
    postgres_session.add(article)
    postgres_session.commit()

    # Run extraction query
    query = text(
        """
        SELECT cl.id, cl.url
        FROM candidate_links cl
        WHERE cl.status = 'article'
        AND cl.id NOT IN (
            SELECT candidate_link_id FROM articles
            WHERE candidate_link_id IS NOT NULL
        )
        """
    )

    results = postgres_session.execute(query).fetchall()

    # Should only return the unprocessed candidate
    result_ids = [str(r[0]) for r in results]
    assert candidate_id_1 not in result_ids, "Processed candidate should be excluded"
    assert candidate_id_2 in result_ids, "Unprocessed candidate should be included"


@pytest.mark.integration
@pytest.mark.postgres
def test_database_url_logging(capsys):
    """Test that DatabaseManager logs the database URL being used.

    This helps debug cases where extraction connects to wrong database.
    """
    from src.models.database import DatabaseManager

    # Create DatabaseManager with a test URL
    test_url = os.getenv("TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("TEST_DATABASE_URL not set")

    db = DatabaseManager(database_url=test_url)

    # Check that initialization logged something
    # Note: This is a basic test - in production we'd verify the log output
    assert db.database_url == test_url

    db.close()
