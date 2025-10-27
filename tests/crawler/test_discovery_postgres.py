"""PostgreSQL-specific discovery tests to catch SQL syntax issues.

These tests verify that discovery queries work correctly with PostgreSQL,
catching issues like operator precedence bugs that SQLite may not detect.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from src.crawler.discovery import NewsDiscovery
from src.models.database import DatabaseManager


@pytest.mark.postgres
def test_dataset_filtering_with_uuid(database_url: str):
    """Verify dataset filtering works with UUID and label on PostgreSQL.

    This test specifically catches SQL operator precedence bugs where
    OR clauses without parentheses can cause syntax errors in PostgreSQL.

    Regression test for bug introduced in PR #108 where:
        WHERE ... AND d.id = :dataset_id OR d.label = :dataset_label
    failed in PostgreSQL due to missing parentheses around the OR clause.
    """
    db = DatabaseManager(database_url)

    # Create two datasets
    dataset1_id = str(uuid.uuid4())
    dataset2_id = str(uuid.uuid4())

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO datasets (id, label, slug, created_at)
                VALUES
                    (:id1, :label1, :slug1, NOW()),
                    (:id2, :label2, :slug2, NOW())
                """
            ),
            {
                "id1": dataset1_id,
                "label1": "Dataset-1",
                "slug1": "dataset-1",
                "id2": dataset2_id,
                "label2": "Dataset-2",
                "slug2": "dataset-2",
            },
        )

        # Create sources
        source1_id = str(uuid.uuid4())
        source2_id = str(uuid.uuid4())
        source3_id = str(uuid.uuid4())

        conn.execute(
            text(
                """
                INSERT INTO sources (id, name, url, host, source_type, created_at)
                VALUES
                    (:id1, :name1, :url1, :host1, 'rss', NOW()),
                    (:id2, :name2, :url2, :host2, 'rss', NOW()),
                    (:id3, :name3, :url3, :host3, 'rss', NOW())
                """
            ),
            {
                "id1": source1_id,
                "name1": "Source 1",
                "url1": "https://example.com/rss1",
                "host1": "example.com",
                "id2": source2_id,
                "name2": "Source 2",
                "url2": "https://example.com/rss2",
                "host2": "example.com",
                "id3": source3_id,
                "name3": "Source 3",
                "url3": "https://other.com/rss3",
                "host3": "other.com",
            },
        )

        # Link sources to datasets
        conn.execute(
            text(
                """
                INSERT INTO dataset_sources (dataset_id, source_id)
                VALUES
                    (:dataset1, :source1),
                    (:dataset1, :source2),
                    (:dataset2, :source3)
                """
            ),
            {
                "dataset1": dataset1_id,
                "source1": source1_id,
                "source2": source2_id,
                "dataset2": dataset2_id,
                "source3": source3_id,
            },
        )

    # Test 1: Filter by dataset UUID
    discovery = NewsDiscovery(database_url=database_url)
    sources_df, stats = discovery.get_sources_to_process(
        dataset_label=dataset1_id,  # Pass UUID as string
        limit=100,
        due_only=False,
    )

    assert len(sources_df) == 2, (
        f"Expected 2 sources for dataset UUID {dataset1_id}, got {len(sources_df)}"
    )
    assert set(sources_df["name"]) == {"Source 1", "Source 2"}

    # Test 2: Filter by dataset label (fallback)
    sources_df, stats = discovery.get_sources_to_process(
        dataset_label="Dataset-2", limit=100, due_only=False
    )

    assert len(sources_df) == 1, (
        f"Expected 1 source for Dataset-2, got {len(sources_df)}"
    )
    assert sources_df.iloc[0]["name"] == "Source 3"

    # Test 3: Verify SQL is valid (no syntax errors)
    # This specifically tests the parentheses around OR clause
    # The bug would cause: psycopg2.errors.SyntaxError with error code 42601
    sources_df, stats = discovery.get_sources_to_process(
        dataset_label=dataset2_id, limit=100, due_only=False
    )

    assert len(sources_df) == 1, (
        "Should successfully execute query without SQL syntax error"
    )


@pytest.mark.postgres
def test_discovery_with_multiple_where_clauses(database_url: str):
    """Test that complex WHERE clauses with AND/OR work correctly in PostgreSQL.

    This ensures operator precedence is correct when combining multiple filters.
    """
    db = DatabaseManager(database_url)

    dataset_id = str(uuid.uuid4())

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO datasets (id, label, slug, created_at)
                VALUES (:id, :label, :slug, NOW())
                """
            ),
            {"id": dataset_id, "label": "Test-Dataset", "slug": "test-dataset"},
        )

        # Create sources with different hosts
        source1_id = str(uuid.uuid4())
        source2_id = str(uuid.uuid4())

        conn.execute(
            text(
                """
                INSERT INTO sources (id, name, url, host, source_type, created_at)
                VALUES
                    (:id1, 'Source 1', 'https://test.com/rss', 'test.com', 'rss', NOW()),
                    (:id2, 'Source 2', 'https://other.com/rss', 'other.com', 'rss', NOW())
                """
            ),
            {"id1": source1_id, "id2": source2_id},
        )

        conn.execute(
            text(
                """
                INSERT INTO dataset_sources (dataset_id, source_id)
                VALUES (:dataset, :source1), (:dataset, :source2)
                """
            ),
            {"dataset": dataset_id, "source1": source1_id, "source2": source2_id},
        )

    # Test with dataset filter + host filter (multiple AND conditions with OR)
    discovery = NewsDiscovery(database_url=database_url)
    sources_df, stats = discovery.get_sources_to_process(
        dataset_label=dataset_id, host_filter="test.com", limit=100, due_only=False
    )

    # Should only return source with test.com host
    assert len(sources_df) == 1, (
        f"Expected 1 source with host filter, got {len(sources_df)}"
    )
    assert sources_df.iloc[0]["host"] == "test.com"


@pytest.mark.postgres
def test_discovery_query_without_dataset_filter(database_url: str):
    """Verify discovery works without dataset filter (baseline test)."""
    db = DatabaseManager(database_url)

    source_id = str(uuid.uuid4())

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sources (id, name, url, host, source_type, created_at)
                VALUES (:id, 'Test Source', 'https://test.com/rss', 'test.com', 'rss', NOW())
                """
            ),
            {"id": source_id},
        )

    discovery = NewsDiscovery(database_url=database_url)
    sources_df, stats = discovery.get_sources_to_process(limit=100, due_only=False)

    assert len(sources_df) >= 1, "Should find at least the test source"
    assert "Test Source" in sources_df["name"].values
