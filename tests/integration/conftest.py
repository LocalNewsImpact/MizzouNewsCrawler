"""Fixtures for PostgreSQL integration tests."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="function")
def cloud_sql_engine():
    """Create engine for Cloud SQL / PostgreSQL integration tests.

    Requires TEST_DATABASE_URL environment variable.
    Only used for integration tests marked with @pytest.mark.integration
    """
    test_db_url = os.getenv("TEST_DATABASE_URL")
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping PostgreSQL tests")

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
    """Create session for Cloud SQL / PostgreSQL integration tests.

    Uses transactions to ensure test isolation and cleanup.
    All changes made in the test are automatically rolled back.
    """
    connection = cloud_sql_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
