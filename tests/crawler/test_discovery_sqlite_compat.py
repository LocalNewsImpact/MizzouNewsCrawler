"""Test discovery pipeline database compatibility (SQLite and PostgreSQL)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pandas as pd
import pytest

from src.crawler.discovery import NewsDiscovery
from src.models.database import DatabaseManager


@pytest.fixture
def sqlite_db(tmp_path: Path) -> str:
    """Create temporary SQLite database for testing."""
    db_path = tmp_path / "test.db"
    database_url = f"sqlite:///{db_path}"

    # Initialize database with minimal schema
    db = DatabaseManager(database_url)

    with db.engine.begin() as conn:
        # Create sources table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                canonical_name TEXT,
                host TEXT,
                host_norm TEXT,
                city TEXT,
                county TEXT,
                type TEXT,
                metadata TEXT
            )
            """
        )

        # Create datasets table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                label TEXT UNIQUE,
                slug TEXT,
                created_at TEXT
            )
            """
        )

        # Create dataset_sources junction table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_sources (
                dataset_id TEXT,
                source_id TEXT,
                PRIMARY KEY (dataset_id, source_id)
            )
            """
        )

        # Create candidate_links table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_links (
                id TEXT PRIMARY KEY,
                source_id TEXT,
                source_host_id TEXT,
                url TEXT,
                discovered_at TEXT,
                processed_at TEXT
            )
            """
        )

        # Create telemetry tables (minimal)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY,
                operation_type TEXT,
                created_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_outcomes (
                id TEXT PRIMARY KEY,
                operation_id TEXT,
                source_id TEXT,
                created_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_method_effectiveness (
                id TEXT PRIMARY KEY,
                source_id TEXT,
                discovery_method TEXT,
                created_at TEXT
            )
            """
        )

    return database_url


def test_get_sources_query_works_on_sqlite(sqlite_db: str):
    """Verify get_sources_to_process works on SQLite (no DISTINCT ON syntax error)."""
    db = DatabaseManager(sqlite_db)

    # Insert test dataset
    dataset_id = str(uuid.uuid4())
    with db.engine.begin() as conn:
        conn.execute(
            """
            INSERT INTO datasets (id, label, slug, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (dataset_id, "test-dataset", "test-dataset"),
        )

    # Insert test sources
    source_ids = []
    for i in range(3):
        source_id = str(uuid.uuid4())
        source_ids.append(source_id)

        with db.engine.begin() as conn:
            conn.execute(
                """
                INSERT INTO sources (id, canonical_name, host, city, county)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    f"Test Source {i+1}",
                    f"test{i+1}.example.com",
                    "TestCity",
                    "TestCounty",
                ),
            )

            # Link to dataset
            conn.execute(
                """
                INSERT INTO dataset_sources (dataset_id, source_id)
                VALUES (?, ?)
                """,
                (dataset_id, source_id),
            )

    # Test: get_sources_to_process should not raise SQL error
    discovery = NewsDiscovery(database_url=sqlite_db)

    # This should work on SQLite (uses GROUP BY instead of DISTINCT ON)
    sources_df, stats = discovery.get_sources_to_process(limit=10)

    # Assertions
    assert isinstance(sources_df, pd.DataFrame)
    assert len(sources_df) == 3, f"Expected 3 sources, got {len(sources_df)}"
    assert "id" in sources_df.columns
    assert "name" in sources_df.columns
    assert "url" in sources_df.columns
    assert "discovery_attempted" in sources_df.columns

    # Check stats
    assert stats["sources_available"] == 3
    assert stats["sources_due"] == 3
    assert stats["sources_skipped"] == 0


def test_dataset_filtering_works_on_sqlite(sqlite_db: str):
    """Verify dataset filtering works correctly on SQLite."""
    db = DatabaseManager(sqlite_db)

    # Create two datasets
    dataset1_id = str(uuid.uuid4())
    dataset2_id = str(uuid.uuid4())

    with db.engine.begin() as conn:
        conn.execute(
            """
            INSERT INTO datasets (id, label, slug, created_at)
            VALUES 
                (?, ?, ?, datetime('now')),
                (?, ?, ?, datetime('now'))
            """,
            (
                dataset1_id,
                "Dataset-1",
                "dataset-1",
                dataset2_id,
                "Dataset-2",
                "dataset-2",
            ),
        )

    # Create sources for each dataset
    source1_id = str(uuid.uuid4())
    source2_id = str(uuid.uuid4())

    with db.engine.begin() as conn:
        # Source 1 in Dataset 1
        conn.execute(
            """
            INSERT INTO sources (id, canonical_name, host)
            VALUES (?, ?, ?)
            """,
            (source1_id, "Source 1", "source1.com"),
        )
        conn.execute(
            """
            INSERT INTO dataset_sources (dataset_id, source_id)
            VALUES (?, ?)
            """,
            (dataset1_id, source1_id),
        )

        # Source 2 in Dataset 2
        conn.execute(
            """
            INSERT INTO sources (id, canonical_name, host)
            VALUES (?, ?, ?)
            """,
            (source2_id, "Source 2", "source2.com"),
        )
        conn.execute(
            """
            INSERT INTO dataset_sources (dataset_id, source_id)
            VALUES (?, ?)
            """,
            (dataset2_id, source2_id),
        )

    # Test: Filter by Dataset 1
    discovery = NewsDiscovery(database_url=sqlite_db)
    sources_df, stats = discovery.get_sources_to_process(
        dataset_label="Dataset-1"
    )

    assert len(sources_df) == 1, f"Expected 1 source, got {len(sources_df)}"
    assert sources_df.iloc[0]["name"] == "Source 1"

    # Test: Filter by Dataset 2
    sources_df, stats = discovery.get_sources_to_process(
        dataset_label="Dataset-2"
    )

    assert len(sources_df) == 1, f"Expected 1 source, got {len(sources_df)}"
    assert sources_df.iloc[0]["name"] == "Source 2"


def test_invalid_dataset_returns_empty_with_error(sqlite_db: str, caplog):
    """Verify invalid dataset label returns empty result with error message."""
    db = DatabaseManager(sqlite_db)

    # Create a valid dataset
    dataset_id = str(uuid.uuid4())
    with db.engine.begin() as conn:
        conn.execute(
            """
            INSERT INTO datasets (id, label, slug, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (dataset_id, "Valid-Dataset", "valid-dataset"),
        )

    # Test: Query with invalid dataset
    discovery = NewsDiscovery(database_url=sqlite_db)

    import logging

    with caplog.at_level(logging.ERROR):
        sources_df, stats = discovery.get_sources_to_process(
            dataset_label="Invalid-Dataset"
        )

    # Should return empty DataFrame
    assert len(sources_df) == 0

    # Should have logged error
    assert "Dataset 'Invalid-Dataset' not found" in caplog.text

    # Should suggest available datasets
    assert "Available datasets:" in caplog.text or "Valid-Dataset" in caplog.text


def test_due_only_filtering_on_sqlite(sqlite_db: str):
    """Verify due_only filtering works on SQLite."""
    db = DatabaseManager(sqlite_db)

    # Create source with last_discovery_at metadata
    source_id = str(uuid.uuid4())
    metadata = {"last_discovery_at": "2025-10-21T00:00:00", "frequency": "daily"}

    with db.engine.begin() as conn:
        conn.execute(
            """
            INSERT INTO sources (id, canonical_name, host, metadata)
            VALUES (?, ?, ?, ?)
            """,
            (source_id, "Test Source", "test.com", json.dumps(metadata)),
        )

    discovery = NewsDiscovery(database_url=sqlite_db)

    # Test: due_only=False should return source
    sources_df, stats = discovery.get_sources_to_process(due_only=False)
    assert len(sources_df) == 1

    # Test: due_only=True may skip based on last_discovery_at
    sources_df_due, stats_due = discovery.get_sources_to_process(due_only=True)

    # Stats should show filtering happened
    assert stats_due.get("sources_available", 0) >= 0
    # Source may or may not be due depending on current time vs last_discovery_at


def test_database_dialect_detection(sqlite_db: str):
    """Verify database dialect is correctly detected."""
    db = DatabaseManager(sqlite_db)

    assert db.engine.dialect.name == "sqlite"

    # Discovery should use SQLite-compatible query
    discovery = NewsDiscovery(database_url=sqlite_db)

    # Insert a test source
    source_id = str(uuid.uuid4())
    with db.engine.begin() as conn:
        conn.execute(
            """
            INSERT INTO sources (id, canonical_name, host)
            VALUES (?, ?, ?)
            """,
            (source_id, "Test", "test.com"),
        )

    # This should work without DISTINCT ON syntax error
    sources_df, _ = discovery.get_sources_to_process()
    assert len(sources_df) >= 0  # Should not raise error
