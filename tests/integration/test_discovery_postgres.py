"""Integration tests for discovery module with PostgreSQL.

These tests verify that the discovery module works correctly against
PostgreSQL databases with schemas created by Alembic migrations, ensuring:
- DISTINCT ON queries work properly
- Dataset filtering works with PostgreSQL
- Discovery scheduling and due_only filtering works
- get_sources_to_process returns correct results
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.crawler.discovery import NewsDiscovery
from src.models.database import DatabaseManager

# Check if PostgreSQL is available for testing
POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL

# Mark all tests in this module
pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _cleanup_test_data(db_engine):
    """Helper to clean up test data from the database."""
    with db_engine.begin() as conn:
        try:
            # Clean up in reverse dependency order
            conn.execute(text("DELETE FROM candidate_links WHERE source_id LIKE 'test-disc-%'"))
            conn.execute(text("DELETE FROM dataset_sources WHERE source_id LIKE 'test-disc-%'"))
            conn.execute(text("DELETE FROM sources WHERE id LIKE 'test-disc-%'"))
            conn.execute(text("DELETE FROM datasets WHERE id LIKE 'test-disc-%'"))
        except Exception:
            # Tables might not exist yet or cleanup failed, that's ok
            pass


@pytest.fixture
def postgres_db_uri():
    """Get PostgreSQL test database URI."""
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured (set TEST_DATABASE_URL)")
    return POSTGRES_TEST_URL


@pytest.fixture
def postgres_discovery_db(postgres_db_uri):
    """PostgreSQL database with Alembic-migrated schema for discovery tests.
    
    Assumes the test database has been migrated with Alembic migrations.
    Cleans up test data before and after tests.
    """
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured")
    
    db = DatabaseManager(postgres_db_uri)
    
    # Clean up any existing test data
    _cleanup_test_data(db.engine)
    
    yield postgres_db_uri
    
    # Cleanup after test
    _cleanup_test_data(db.engine)


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestDiscoveryPostgreSQL:
    """Test discovery module against PostgreSQL with Alembic schema."""

    def test_get_sources_query_uses_distinct_on(self, postgres_discovery_db):
        """Verify get_sources_to_process uses DISTINCT ON with PostgreSQL.
        
        This test ensures that the PostgreSQL-specific query syntax works
        correctly and doesn't cause SQL errors.
        """
        db = DatabaseManager(postgres_discovery_db)
        
        # Insert test sources
        source_ids = []
        for i in range(3):
            source_id = f"test-disc-{uuid.uuid4()}"
            source_ids.append(source_id)
            
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO sources (id, canonical_name, host, host_norm, city, county, type)
                        VALUES (:id, :name, :host, :host_norm, :city, :county, :type)
                        """
                    ),
                    {
                        "id": source_id,
                        "name": f"Test Source {i+1}",
                        "host": f"test{i+1}.example.com",
                        "host_norm": f"test{i+1}.example.com",
                        "city": "TestCity",
                        "county": "TestCounty",
                        "type": "news",
                    },
                )
        
        # Test: get_sources_to_process should use DISTINCT ON without errors
        discovery = NewsDiscovery(database_url=postgres_discovery_db)
        sources_df, stats = discovery.get_sources_to_process(limit=10)
        
        # Assertions
        assert len(sources_df) == 3, f"Expected 3 sources, got {len(sources_df)}"
        assert "id" in sources_df.columns
        assert "name" in sources_df.columns
        assert "url" in sources_df.columns
        assert "discovery_attempted" in sources_df.columns
        
        # Verify stats
        assert stats["sources_available"] == 3
        assert stats["sources_due"] == 3

    def test_dataset_filtering_works_on_postgres(self, postgres_discovery_db):
        """Verify dataset filtering works correctly on PostgreSQL.
        
        This test ensures the dataset JOIN clause works properly with
        PostgreSQL's DISTINCT ON syntax.
        """
        db = DatabaseManager(postgres_discovery_db)
        
        # Create two datasets
        dataset1_id = f"test-disc-{uuid.uuid4()}"
        dataset2_id = f"test-disc-{uuid.uuid4()}"
        
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO datasets (id, label, slug, ingested_at)
                    VALUES 
                        (:id1, :label1, :slug1, NOW()),
                        (:id2, :label2, :slug2, NOW())
                    """
                ),
                {
                    "id1": dataset1_id,
                    "label1": "Test-Dataset-1",
                    "slug1": "test-dataset-1",
                    "id2": dataset2_id,
                    "label2": "Test-Dataset-2",
                    "slug2": "test-dataset-2",
                },
            )
        
        # Create sources for each dataset
        source1_id = f"test-disc-{uuid.uuid4()}"
        source2_id = f"test-disc-{uuid.uuid4()}"
        
        with db.engine.begin() as conn:
            # Source 1 in Dataset 1
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, canonical_name, host, host_norm, city, county, type)
                    VALUES (:id, :name, :host, :host_norm, :city, :county, :type)
                    """
                ),
                {
                    "id": source1_id,
                    "name": "Source 1",
                    "host": "source1.com",
                    "host_norm": "source1.com",
                    "city": "City1",
                    "county": "County1",
                    "type": "news",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO dataset_sources (id, dataset_id, source_id)
                    VALUES (:id, :dataset_id, :source_id)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "dataset_id": dataset1_id,
                    "source_id": source1_id,
                },
            )
            
            # Source 2 in Dataset 2
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, canonical_name, host, host_norm, city, county, type)
                    VALUES (:id, :name, :host, :host_norm, :city, :county, :type)
                    """
                ),
                {
                    "id": source2_id,
                    "name": "Source 2",
                    "host": "source2.com",
                    "host_norm": "source2.com",
                    "city": "City2",
                    "county": "County2",
                    "type": "news",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO dataset_sources (id, dataset_id, source_id)
                    VALUES (:id, :dataset_id, :source_id)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "dataset_id": dataset2_id,
                    "source_id": source2_id,
                },
            )
        
        # Test: Filter by Dataset 1
        discovery = NewsDiscovery(database_url=postgres_discovery_db)
        sources_df, stats = discovery.get_sources_to_process(dataset_label="Test-Dataset-1")
        
        assert len(sources_df) == 1, f"Expected 1 source, got {len(sources_df)}"
        assert sources_df.iloc[0]["name"] == "Source 1"
        
        # Test: Filter by Dataset 2
        sources_df, stats = discovery.get_sources_to_process(dataset_label="Test-Dataset-2")
        
        assert len(sources_df) == 1, f"Expected 1 source, got {len(sources_df)}"
        assert sources_df.iloc[0]["name"] == "Source 2"

    def test_discovery_attempted_flag_with_postgres(self, postgres_discovery_db):
        """Verify discovery_attempted flag works correctly with PostgreSQL.
        
        This tests that the DISTINCT ON query properly identifies sources
        that have or haven't been attempted for discovery.
        """
        db = DatabaseManager(postgres_discovery_db)
        
        # Create two sources
        attempted_id = f"test-disc-{uuid.uuid4()}"
        new_id = f"test-disc-{uuid.uuid4()}"
        
        with db.engine.begin() as conn:
            # Source that has been attempted
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, canonical_name, host, host_norm, city, county, type)
                    VALUES (:id, :name, :host, :host_norm, :city, :county, :type)
                    """
                ),
                {
                    "id": attempted_id,
                    "name": "Attempted Source",
                    "host": "attempted.com",
                    "host_norm": "attempted.com",
                    "city": "TestCity",
                    "county": "TestCounty",
                    "type": "news",
                },
            )
            
            # Add a candidate link to mark as attempted
            conn.execute(
                text(
                    """
                    INSERT INTO candidate_links 
                    (id, url, source, source_id, source_host_id, dataset_id, status, discovered_at)
                    VALUES (:id, :url, :source, :source_id, :source_host_id, :dataset_id, :status, NOW())
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "url": "https://attempted.com/article-1",
                    "source": "Attempted Source",
                    "source_id": attempted_id,
                    "source_host_id": attempted_id,
                    "dataset_id": "default",
                    "status": "discovered",
                },
            )
            
            # Source that hasn't been attempted
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, canonical_name, host, host_norm, city, county, type)
                    VALUES (:id, :name, :host, :host_norm, :city, :county, :type)
                    """
                ),
                {
                    "id": new_id,
                    "name": "New Source",
                    "host": "new.com",
                    "host_norm": "new.com",
                    "city": "TestCity",
                    "county": "TestCounty",
                    "type": "news",
                },
            )
        
        # Get sources and verify ordering (new sources should come first)
        discovery = NewsDiscovery(database_url=postgres_discovery_db)
        sources_df, stats = discovery.get_sources_to_process(limit=10)
        
        assert len(sources_df) >= 2
        
        # Find our test sources in the results
        attempted_row = sources_df[sources_df["id"] == attempted_id]
        new_row = sources_df[sources_df["id"] == new_id]
        
        assert len(attempted_row) == 1
        assert len(new_row) == 1
        
        # Verify discovery_attempted flag
        assert attempted_row.iloc[0]["discovery_attempted"] == 1
        assert new_row.iloc[0]["discovery_attempted"] == 0
        
        # New source should have lower index (come first in priority)
        new_idx = sources_df.index[sources_df["id"] == new_id].tolist()[0]
        attempted_idx = sources_df.index[sources_df["id"] == attempted_id].tolist()[0]
        assert new_idx < attempted_idx, "New sources should be prioritized"

    def test_due_only_filtering_with_postgres(self, postgres_discovery_db):
        """Verify due_only filtering works correctly on PostgreSQL.
        
        This tests that sources are correctly filtered based on their
        last_discovery_at metadata and frequency.
        """
        db = DatabaseManager(postgres_discovery_db)
        
        now = datetime.utcnow()
        
        # Create source with old last_discovery_at (should be due)
        due_source_id = f"test-disc-{uuid.uuid4()}"
        old_discovery = (now - timedelta(days=10)).isoformat()
        
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, canonical_name, host, host_norm, city, county, type, metadata)
                    VALUES (:id, :name, :host, :host_norm, :city, :county, :type, :metadata)
                    """
                ),
                {
                    "id": due_source_id,
                    "name": "Due Source",
                    "host": "due.com",
                    "host_norm": "due.com",
                    "city": "TestCity",
                    "county": "TestCounty",
                    "type": "news",
                    "metadata": json.dumps({
                        "last_discovery_at": old_discovery,
                        "frequency": "daily"
                    }),
                },
            )
        
        # Test with due_only=False (should return source)
        discovery = NewsDiscovery(database_url=postgres_discovery_db)
        sources_df, stats = discovery.get_sources_to_process(due_only=False)
        
        due_sources = sources_df[sources_df["id"] == due_source_id]
        assert len(due_sources) == 1, "Source should be returned with due_only=False"
        
        # Test with due_only=True (should also return since it's overdue)
        sources_df_due, stats_due = discovery.get_sources_to_process(due_only=True)
        
        due_sources_filtered = sources_df_due[sources_df_due["id"] == due_source_id]
        assert len(due_sources_filtered) == 1, "Source should be returned when overdue"

    def test_host_and_city_filters_with_postgres(self, postgres_discovery_db):
        """Verify host and city filters work correctly with PostgreSQL.
        
        This tests that filter parameters work properly with the
        PostgreSQL DISTINCT ON query.
        """
        db = DatabaseManager(postgres_discovery_db)
        
        # Create sources with different hosts and cities
        sources = [
            {
                "id": f"test-disc-{uuid.uuid4()}",
                "name": "NYC Source",
                "host": "nyc.example.com",
                "city": "New York",
                "county": "Manhattan",
            },
            {
                "id": f"test-disc-{uuid.uuid4()}",
                "name": "LA Source",
                "host": "la.example.com",
                "city": "Los Angeles",
                "county": "Los Angeles",
            },
        ]
        
        for src in sources:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO sources (id, canonical_name, host, host_norm, city, county, type)
                        VALUES (:id, :name, :host, :host_norm, :city, :county, :type)
                        """
                    ),
                    {
                        "id": src["id"],
                        "name": src["name"],
                        "host": src["host"],
                        "host_norm": src["host"],
                        "city": src["city"],
                        "county": src["county"],
                        "type": "news",
                    },
                )
        
        discovery = NewsDiscovery(database_url=postgres_discovery_db)
        
        # Test host filter
        sources_df, _ = discovery.get_sources_to_process(host_filter="nyc.example.com")
        assert len(sources_df) >= 1
        filtered_sources = sources_df[sources_df["host"] == "nyc.example.com"]
        assert len(filtered_sources) == 1
        assert filtered_sources.iloc[0]["name"] == "NYC Source"
        
        # Test city filter
        sources_df, _ = discovery.get_sources_to_process(city_filter="Los Angeles")
        assert len(sources_df) >= 1
        filtered_sources = sources_df[sources_df["city"] == "Los Angeles"]
        assert len(filtered_sources) == 1
        assert filtered_sources.iloc[0]["name"] == "LA Source"

    def test_invalid_dataset_returns_empty_with_postgres(self, postgres_discovery_db, caplog):
        """Verify invalid dataset label returns empty result with error on PostgreSQL."""
        db = DatabaseManager(postgres_discovery_db)
        
        # Create a valid dataset
        dataset_id = f"test-disc-{uuid.uuid4()}"
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO datasets (id, label, slug, ingested_at)
                    VALUES (:id, :label, :slug, NOW())
                    """
                ),
                {
                    "id": dataset_id,
                    "label": "Valid-Dataset",
                    "slug": "valid-dataset",
                },
            )
        
        # Test: Query with invalid dataset
        discovery = NewsDiscovery(database_url=postgres_discovery_db)
        
        with caplog.at_level(logging.ERROR):
            sources_df, stats = discovery.get_sources_to_process(
                dataset_label="Invalid-Dataset-PostgreSQL"
            )
        
        # Should return empty DataFrame
        assert len(sources_df) == 0
        
        # Should have logged error
        assert "Dataset 'Invalid-Dataset-PostgreSQL' not found" in caplog.text
