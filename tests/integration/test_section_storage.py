"""Integration tests for section discovery storage and retrieval.

These tests verify that section discovery columns work correctly with
both SQLite and PostgreSQL databases.
"""

import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from src.models.database import DatabaseManager


@pytest.fixture
def test_source_id():
    """Generate a unique test source ID."""
    return f"test-section-{uuid.uuid4()}"


@pytest.fixture
def db_manager(request):
    """Provide a database manager for testing."""
    # Use environment variable if available, otherwise use in-memory SQLite
    import os
    database_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    
    db = DatabaseManager(database_url)
    
    # Create tables if they don't exist
    from src.models import Base
    Base.metadata.create_all(db.engine)
    
    yield db
    
    # Cleanup is handled by test functions
    db.close()


def test_section_columns_exist(db_manager):
    """Test that section discovery columns exist in sources table."""
    with db_manager.engine.connect() as conn:
        dialect = conn.dialect.name
        
        if dialect == "postgresql":
            result = conn.execute(
                text(
                    """
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'sources' 
                    AND column_name IN (
                        'discovered_sections',
                        'section_discovery_enabled',
                        'section_last_updated'
                    )
                    """
                )
            )
            columns = {row[0] for row in result.fetchall()}
        else:
            # SQLite
            result = conn.execute(text("PRAGMA table_info(sources)"))
            columns = {row[1] for row in result.fetchall()}
        
        assert "discovered_sections" in columns
        assert "section_discovery_enabled" in columns
        assert "section_last_updated" in columns


def test_store_section_data(db_manager, test_source_id):
    """Test storing section discovery data in sources table."""
    # Create a test source
    with db_manager.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sources (
                    id, host, host_norm, section_discovery_enabled,
                    rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive)
                    VALUES (:id, :host, :host_norm, :enabled, 0, '[]', 0)
                """
            ),
            {
                "id": test_source_id,
                "host": "example.com",
                "host_norm": "example.com",
                "enabled": True,
            }
        )
        
        # Store section data
        sections = [
            {
                "url": "/news",
                "discovered_at": datetime.utcnow().isoformat(),
                "last_successful": datetime.utcnow().isoformat(),
                "success_count": 10,
                "failure_count": 1,
                "avg_articles_found": 15.5,
            },
            {
                "url": "/local",
                "discovered_at": datetime.utcnow().isoformat(),
                "last_successful": None,
                "success_count": 0,
                "failure_count": 3,
                "avg_articles_found": 0.0,
            },
        ]
        
        dialect = conn.dialect.name
        if dialect == "postgresql":
            # PostgreSQL uses JSONB
            conn.execute(
                text(
                    """
                    UPDATE sources 
                    SET discovered_sections = :sections::jsonb,
                        section_last_updated = :updated
                    WHERE id = :id
                    """
                ),
                {
                    "sections": json.dumps(sections),
                    "updated": datetime.utcnow(),
                    "id": test_source_id,
                }
            )
        else:
            # SQLite stores JSON as TEXT
            conn.execute(
                text(
                    """
                    UPDATE sources 
                    SET discovered_sections = :sections,
                        section_last_updated = :updated
                    WHERE id = :id
                    """
                ),
                {
                    "sections": json.dumps(sections),
                    "updated": datetime.utcnow().isoformat(),
                    "id": test_source_id,
                }
            )
        
        # Verify data was stored
        result = conn.execute(
            text(
                """
                SELECT discovered_sections, section_discovery_enabled, section_last_updated
                FROM sources WHERE id = :id
                """
            ),
            {"id": test_source_id}
        ).fetchone()
        
        assert result is not None
        
        # Parse the JSON data
        stored_sections = result[0]
        if isinstance(stored_sections, str):
            stored_sections = json.loads(stored_sections)
        
        assert len(stored_sections) == 2
        assert stored_sections[0]["url"] == "/news"
        assert stored_sections[0]["success_count"] == 10
        assert stored_sections[1]["url"] == "/local"
        assert stored_sections[1]["failure_count"] == 3
        
        # Verify enabled flag
        assert result[1] is True or result[1] == 1  # SQLite returns int
        
        # Verify timestamp was set
        assert result[2] is not None
        
        # Cleanup
        conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": test_source_id})


def test_retrieve_section_data(db_manager, test_source_id):
    """Test retrieving section discovery data from sources table."""
    sections = [
        {
            "url": "/sports",
            "discovered_at": "2023-01-01T00:00:00",
            "success_count": 5,
        }
    ]
    
    with db_manager.engine.begin() as conn:
        # Insert test source with section data
        dialect = conn.dialect.name
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    INSERT INTO sources (
                        id, host, host_norm, discovered_sections,
                        section_discovery_enabled, section_last_updated,
                        rss_consecutive_failures, no_effective_methods_consecutive
                    )
                    VALUES (
                        :id, :host, :host_norm, :sections::jsonb, :enabled, :updated, 0, 0
                    )
                    """
                ),
                {
                    "id": test_source_id,
                    "host": "example.com",
                    "host_norm": "example.com",
                    "sections": json.dumps(sections),
                    "enabled": True,
                    "updated": datetime.utcnow(),
                }
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO sources (
                        id, host, host_norm, discovered_sections,
                        section_discovery_enabled, section_last_updated,
                        rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive
                    )
                    VALUES (
                        :id, :host, :host_norm, :sections, :enabled, :updated, 0, '[]', 0
                    )
                    """
                ),
                {
                    "id": test_source_id,
                    "host": "example.com",
                    "host_norm": "example.com",
                    "sections": json.dumps(sections),
                    "enabled": 1,
                    "updated": datetime.utcnow().isoformat(),
                }
            )
        
        # Retrieve the data
        result = conn.execute(
            text("SELECT discovered_sections FROM sources WHERE id = :id"),
            {"id": test_source_id}
        ).fetchone()
        
        assert result is not None
        
        retrieved_sections = result[0]
        if isinstance(retrieved_sections, str):
            retrieved_sections = json.loads(retrieved_sections)
        
        assert len(retrieved_sections) == 1
        assert retrieved_sections[0]["url"] == "/sports"
        assert retrieved_sections[0]["success_count"] == 5
        
        # Cleanup
        conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": test_source_id})


def test_section_discovery_enabled_flag(db_manager, test_source_id):
    """Test section_discovery_enabled flag works correctly."""
    with db_manager.engine.begin() as conn:
        dialect = conn.dialect.name
        
        # Test enabled (default)
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, host, host_norm, rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive, section_discovery_enabled)
                    VALUES (:id, :host, :host_norm, 0, '[]', 0, 1)
                    """
                ),
                {
                    "id": test_source_id,
                    "host": "enabled.com",
                    "host_norm": "enabled.com",
                }
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, host, host_norm, rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive, section_discovery_enabled)
                    VALUES (:id, :host, :host_norm, 0, '[]', 0, 1)
                    """
                ),
                {
                    "id": test_source_id,
                    "host": "enabled.com",
                    "host_norm": "enabled.com",
                }
            )
        
        result = conn.execute(
            text("SELECT section_discovery_enabled FROM sources WHERE id = :id"),
            {"id": test_source_id}
        ).fetchone()
        
        # Default should be enabled
        assert result[0] is True or result[0] == 1
        
        # Test disabled
        test_source_id_2 = f"test-section-{uuid.uuid4()}"
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    INSERT INTO sources (
                        id, host, host_norm, section_discovery_enabled,
                        rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive
                    )
                    VALUES (:id, :host, :host_norm, :enabled, 0, '[]', 0)
                    """
                ),
                {
                    "id": test_source_id_2,
                    "host": "disabled.com",
                    "host_norm": "disabled.com",
                    "enabled": False,
                }
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO sources (
                        id, host, host_norm, section_discovery_enabled,
                        rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive
                    )
                    VALUES (:id, :host, :host_norm, :enabled, 0, '[]', 0)
                    """
                ),
                {
                    "id": test_source_id_2,
                    "host": "disabled.com",
                    "host_norm": "disabled.com",
                    "enabled": 0,
                }
            )
        
        result = conn.execute(
            text("SELECT section_discovery_enabled FROM sources WHERE id = :id"),
            {"id": test_source_id_2}
        ).fetchone()
        
        assert result[0] is False or result[0] == 0
        
        # Cleanup
        conn.execute(
            text("DELETE FROM sources WHERE id IN (:id1, :id2)"),
            {"id1": test_source_id, "id2": test_source_id_2}
        )


def test_null_sections(db_manager, test_source_id):
    """Test that sources with NULL sections can be queried."""
    with db_manager.engine.begin() as conn:
        # Create source with NULL sections
        conn.execute(
            text(
                """
                INSERT INTO sources (id, host, host_norm, rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive, section_discovery_enabled)
                    VALUES (:id, :host, :host_norm, 0, '[]', 0, 1)
                """
            ),
            {
                "id": test_source_id,
                "host": "null-sections.com",
                "host_norm": "null-sections.com",
            }
        )
        
        # Verify NULL is stored correctly
        result = conn.execute(
            text("SELECT discovered_sections FROM sources WHERE id = :id"),
            {"id": test_source_id}
        ).fetchone()
        
        assert result[0] is None
        
        # Cleanup
        conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": test_source_id})


def test_update_sections(db_manager, test_source_id):
    """Test updating section data over time."""
    with db_manager.engine.begin() as conn:
        # Create source with initial sections
        initial_sections = [{"url": "/news", "success_count": 1}]
        
        dialect = conn.dialect.name
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, host, host_norm, discovered_sections)
                    VALUES (:id, :host, :host_norm, :sections::jsonb)
                    """
                ),
                {
                    "id": test_source_id,
                    "host": "update-test.com",
                    "host_norm": "update-test.com",
                    "sections": json.dumps(initial_sections),
                }
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO sources (id, host, host_norm, discovered_sections, rss_consecutive_failures, rss_transient_failures, no_effective_methods_consecutive, section_discovery_enabled)
                    VALUES (:id, :host, :host_norm, :sections, 0, '[]', 0, 1)
                    """
                ),
                {
                    "id": test_source_id,
                    "host": "update-test.com",
                    "host_norm": "update-test.com",
                    "sections": json.dumps(initial_sections),
                }
            )
        
        # Update sections
        updated_sections = [
            {"url": "/news", "success_count": 2},
            {"url": "/sports", "success_count": 1},
        ]
        
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    UPDATE sources 
                    SET discovered_sections = :sections::jsonb
                    WHERE id = :id
                    """
                ),
                {
                    "sections": json.dumps(updated_sections),
                    "id": test_source_id,
                }
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE sources 
                    SET discovered_sections = :sections
                    WHERE id = :id
                    """
                ),
                {
                    "sections": json.dumps(updated_sections),
                    "id": test_source_id,
                }
            )
        
        # Verify update
        result = conn.execute(
            text("SELECT discovered_sections FROM sources WHERE id = :id"),
            {"id": test_source_id}
        ).fetchone()
        
        sections = result[0]
        if isinstance(sections, str):
            sections = json.loads(sections)
        
        assert len(sections) == 2
        assert sections[0]["success_count"] == 2
        
        # Cleanup
        conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": test_source_id})
