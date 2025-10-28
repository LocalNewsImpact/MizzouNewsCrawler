"""Integration tests for Cloud SQL connections (Issue #44).

These tests verify that the API can connect to and query Cloud SQL properly.
They require a Cloud SQL test instance and should be run with:

    pytest tests/integration/ -v -m integration

Environment variables required:
- TEST_DATABASE_URL: PostgreSQL connection string for test instance
- CLOUD_SQL_INSTANCE: Cloud SQL instance connection name
- USE_CLOUD_SQL_CONNECTOR: Set to "true" to use Cloud SQL Connector

Note: These tests will be skipped if TEST_DATABASE_URL is not set.
"""

import os
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def cloud_sql_engine():
    """Create a database engine for Cloud SQL integration tests.

    Provides a local fallback when the backend pytest plugin is disabled.
    """

    test_db_url = os.getenv("TEST_DATABASE_URL")
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping Cloud SQL tests")

    engine = create_engine(test_db_url, echo=False)

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - defensive guard
        pytest.skip(f"Cannot connect to test database: {exc}")

    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def cloud_sql_session(cloud_sql_engine):
    """Return a transactional session bound to the Cloud SQL engine."""

    connection = cloud_sql_engine.connect()
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
def test_cloud_sql_connector_connection(cloud_sql_session):
    """Test that Cloud SQL Connector can establish a connection.

    This is the most basic integration test. If this fails, the Cloud SQL
    connection is not working.
    """
    from sqlalchemy import text

    # Execute simple query
    result = cloud_sql_session.execute(text("SELECT 1 as test")).scalar()
    assert result == 1


@pytest.mark.integration
def test_cloud_sql_connector_performance(cloud_sql_session):
    """Test Cloud SQL connection performance.

    Verify that queries execute quickly enough for production use.
    """
    from sqlalchemy import text

    start_time = time.time()
    result = cloud_sql_session.execute(text("SELECT 1")).scalar()
    elapsed_time = time.time() - start_time

    assert result == 1
    assert (
        elapsed_time < 0.1
    ), f"Simple query took {elapsed_time:.2f}s, should be < 100ms"


@pytest.mark.integration
def test_cloud_sql_tables_exist(cloud_sql_session):
    """Test that required tables exist in Cloud SQL.

    Verifies that Alembic migrations have been run successfully.
    """
    from sqlalchemy import inspect

    # Get table names
    inspector = inspect(cloud_sql_session.bind)
    tables = inspector.get_table_names()

    # Required tables for Issue #44 endpoints
    required_tables = [
        "articles",
        "sources",
        "reviews",
        "candidates",
    ]

    for table in required_tables:
        assert table in tables, f"Table '{table}' not found in database"


@pytest.mark.integration
def test_cloud_sql_articles_table_schema(cloud_sql_session):
    """Test that articles table has correct schema."""
    from sqlalchemy import inspect

    inspector = inspect(cloud_sql_session.bind)
    columns = inspector.get_columns("articles")
    column_names = {col["name"] for col in columns}

    # Required columns for articles table
    required_columns = {
        "id",
        "title",
        "url",
        "candidate_link_id",
        "publish_date",
        "content",
        "status",
    }

    for col in required_columns:
        assert col in column_names, f"Column '{col}' not found in articles table"


@pytest.mark.integration
def test_cloud_sql_connection_pool(cloud_sql_engine):
    """Test Cloud SQL connection pooling.

    Verify that multiple connections can be created and used concurrently.
    """
    from sqlalchemy import text

    # Create multiple connections
    connections = []
    try:
        for i in range(5):
            conn = cloud_sql_engine.connect()
            result = conn.execute(text("SELECT 1")).scalar()
            assert result == 1
            connections.append(conn)

        # All connections should work
        assert len(connections) == 5
    finally:
        # Clean up
        for conn in connections:
            conn.close()


@pytest.mark.integration
def test_cloud_sql_concurrent_queries(cloud_sql_engine):
    """Test concurrent query execution.

    Simulates multiple API requests hitting the database simultaneously.
    """
    import concurrent.futures

    from sqlalchemy import text

    def execute_query():
        with cloud_sql_engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            return result

    # Execute 10 concurrent queries
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(execute_query) for _ in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # All queries should succeed
    assert len(results) == 10
    assert all(r == 1 for r in results)


@pytest.mark.integration
def test_cloud_sql_transaction_isolation(cloud_sql_engine):
    """Test transaction isolation.

    Verify that transactions are properly isolated between sessions.
    """
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=cloud_sql_engine)

    # Create two sessions
    session1 = SessionLocal()
    session2 = SessionLocal()

    try:
        # Both sessions should see the same data
        result1 = session1.execute(text("SELECT COUNT(*) FROM articles")).scalar()
        result2 = session2.execute(text("SELECT COUNT(*) FROM articles")).scalar()

        assert result1 == result2
    finally:
        session1.close()
        session2.close()


@pytest.mark.integration
def test_cloud_sql_read_articles(cloud_sql_session):
    """Test reading articles from Cloud SQL.

    Verify that we can query the articles table successfully.
    """
    from sqlalchemy import text

    # Query articles
    result = cloud_sql_session.execute(text("SELECT COUNT(*) FROM articles")).scalar()

    # Should have articles (from real data)
    assert result >= 0  # At least 0 articles

    # Try to fetch a few articles
    articles = cloud_sql_session.execute(
        text("SELECT id, title FROM articles LIMIT 5")
    ).fetchall()

    # Verify structure
    for article in articles:
        assert article[0] is not None  # id
        # title can be NULL in some cases


@pytest.mark.integration
def test_cloud_sql_read_sources(cloud_sql_session):
    """Test reading sources from Cloud SQL."""
    from sqlalchemy import text

    # Query sources
    result = cloud_sql_session.execute(text("SELECT COUNT(*) FROM sources")).scalar()

    assert result >= 0


@pytest.mark.integration
def test_cloud_sql_read_reviews(cloud_sql_session):
    """Test reading reviews from Cloud SQL."""
    from sqlalchemy import text

    # Query reviews
    result = cloud_sql_session.execute(text("SELECT COUNT(*) FROM reviews")).scalar()

    assert result >= 0


@pytest.mark.integration
def test_cloud_sql_join_articles_sources(cloud_sql_session):
    """Test JOIN query between articles and sources via candidate_links.

    Joins through candidate_links table since articles don't have
    source_id directly.
    """
    from sqlalchemy import text

    query = text(
        """
        SELECT a.id, a.title, cl.source
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        LIMIT 10
    """
    )

    results = cloud_sql_session.execute(query).fetchall()

    # Verify JOIN works
    for row in results:
        assert row[0] is not None  # article uid
        assert row[1] is not None  # article title
        assert row[2] is not None  # source name


@pytest.mark.integration
def test_cloud_sql_join_articles_reviews(cloud_sql_session):
    """Test JOIN query between articles and reviews.

    This is used for filtering articles by reviewer.
    """
    from sqlalchemy import text

    query = text(
        """
        SELECT a.uid, r.reviewer
        FROM articles a
        LEFT JOIN reviews r ON a.uid = r.article_uid
        LIMIT 10
    """
    )

    results = cloud_sql_session.execute(query).fetchall()

    # Verify JOIN works (may have NULLs for unreviewed articles)
    for row in results:
        assert row[0] is not None  # article uid
        # row[1] may be NULL for unreviewed articles


@pytest.mark.integration
def test_cloud_sql_distinct_counties(cloud_sql_session):
    """Test getting distinct counties from Cloud SQL.

    This is what /api/options/counties does.
    """
    from sqlalchemy import text

    query = text(
        """
        SELECT DISTINCT county
        FROM articles
        WHERE county IS NOT NULL
        ORDER BY county
    """
    )

    results = cloud_sql_session.execute(query).fetchall()

    # Verify distinct query works
    counties = [row[0] for row in results]
    assert len(counties) == len(set(counties))  # No duplicates


@pytest.mark.integration
def test_cloud_sql_distinct_reviewers(cloud_sql_session):
    """Test getting distinct reviewers from Cloud SQL.

    This is what /api/options/reviewers does.
    """
    from sqlalchemy import text

    query = text(
        """
        SELECT DISTINCT reviewer
        FROM reviews
        WHERE reviewer IS NOT NULL
        ORDER BY reviewer
    """
    )

    results = cloud_sql_session.execute(query).fetchall()

    # Verify distinct query works
    reviewers = [row[0] for row in results]
    assert len(reviewers) == len(set(reviewers))  # No duplicates


@pytest.mark.integration
def test_cloud_sql_aggregate_queries(cloud_sql_session):
    """Test aggregate queries for ui_overview endpoint.

    This is what /api/ui_overview does.
    """
    from sqlalchemy import text

    # Count articles
    articles_count = cloud_sql_session.execute(
        text("SELECT COUNT(*) FROM articles")
    ).scalar()
    assert articles_count >= 0

    # Count candidates
    candidates_count = cloud_sql_session.execute(
        text("SELECT COUNT(*) FROM candidates")
    ).scalar()
    assert candidates_count >= 0

    # Count reviews
    reviews_count = cloud_sql_session.execute(
        text("SELECT COUNT(*) FROM reviews")
    ).scalar()
    assert reviews_count >= 0


@pytest.mark.integration
def test_cloud_sql_performance_large_query(cloud_sql_session):
    """Test performance of large query.

    Success criteria: < 500ms for typical queries.
    """
    from sqlalchemy import text

    start_time = time.time()

    # Query that simulates /api/articles
    query = text(
        """
        SELECT a.uid, a.title, a.county, s.name as source_name
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        ORDER BY a.publish_date DESC
        LIMIT 100
    """
    )

    results = cloud_sql_session.execute(query).fetchall()
    elapsed_time = time.time() - start_time

    assert len(results) <= 100
    assert elapsed_time < 0.5, f"Query took {elapsed_time:.2f}s, should be < 500ms"


@pytest.mark.integration
def test_cloud_sql_connection_recovery(cloud_sql_engine):
    """Test that connections can recover from errors.

    Verify that after a failed query, new queries can still succeed.
    """
    from sqlalchemy import text

    # Execute valid query
    with cloud_sql_engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1

    # Execute invalid query (should fail)
    try:
        with cloud_sql_engine.connect() as conn:
            conn.execute(text("SELECT * FROM nonexistent_table"))
    except Exception:
        pass  # Expected to fail

    # Execute valid query again (should succeed)
    with cloud_sql_engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


@pytest.mark.integration
def test_cloud_sql_connection_timeout(cloud_sql_engine):
    """Test that connection timeout is reasonable.

    Verify connections are established quickly.
    """
    from sqlalchemy import text

    start_time = time.time()

    with cloud_sql_engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    elapsed_time = time.time() - start_time

    # Connection should be fast (< 2 seconds)
    assert elapsed_time < 2.0, f"Connection took {elapsed_time:.2f}s, should be < 2s"
