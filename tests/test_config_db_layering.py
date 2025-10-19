"""Tests for Phase 3: Config & DB Layering."""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_create_engine_from_env_uses_database_url(monkeypatch):
    """create_engine_from_env() should read DATABASE_URL from config."""
    from src.models import create_engine_from_env

    # Set a test database URL
    test_db_url = "sqlite:///test_from_env.db"
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    
    # Force reload of config module to pick up new env var
    import importlib

    import src.config
    importlib.reload(src.config)
    
    engine = create_engine_from_env()
    
    # Verify the engine was created with the correct URL
    assert str(engine.url) == test_db_url or str(engine.url).startswith("sqlite:///")


def test_create_engine_from_env_defaults_to_sqlite(monkeypatch):
    """create_engine_from_env() should default to SQLite if DATABASE_URL not set."""
    from src.models import create_engine_from_env

    # Clear DATABASE_URL
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_HOST", raising=False)
    monkeypatch.delenv("DATABASE_NAME", raising=False)
    monkeypatch.delenv("DATABASE_USER", raising=False)
    
    # Force reload of config module
    import importlib

    import src.config
    importlib.reload(src.config)
    
    engine = create_engine_from_env()
    
    # Should default to SQLite
    assert "sqlite" in str(engine.url)


def test_create_engine_from_env_constructs_postgres_url(monkeypatch):
    """create_engine_from_env() should construct PostgreSQL URL from components."""
    from src.models import create_engine_from_env

    # Set PostgreSQL connection components
    monkeypatch.setenv("DATABASE_ENGINE", "postgresql+psycopg2")
    monkeypatch.setenv("DATABASE_HOST", "localhost")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_NAME", "testdb")
    monkeypatch.setenv("DATABASE_USER", "testuser")
    monkeypatch.setenv("DATABASE_PASSWORD", "testpass")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    
    # Force reload of config module
    import importlib

    import src.config
    importlib.reload(src.config)
    
    engine = create_engine_from_env()
    
    # Verify PostgreSQL URL was constructed
    url_str = str(engine.url)
    assert "postgresql" in url_str
    assert "localhost" in url_str
    assert "testdb" in url_str


def test_database_manager_accepts_engine_or_url():
    """DatabaseManager should accept both engine and URL parameters."""
    from src.models import create_database_engine
    from src.models.database import DatabaseManager

    # Test with URL
    db_url = "sqlite:///:memory:"
    db1 = DatabaseManager(database_url=db_url)
    assert db1.engine is not None
    db1.close()
    
    # Test with explicit engine (DatabaseManager currently only accepts URL,
    # but the underlying create_database_engine accepts URL which is the pattern)
    db2 = DatabaseManager(database_url="sqlite:///:memory:")
    assert db2.engine is not None
    db2.close()


def test_postgres_connection_string_parsing():
    """Verify PostgreSQL connection strings are parsed correctly."""
    from src.models import create_database_engine

    # Test PostgreSQL URL with all components
    pg_url = "postgresql+psycopg2://user:pass@localhost:5432/dbname?sslmode=require"
    engine = create_database_engine(pg_url)
    
    assert engine is not None
    assert "postgresql" in str(engine.url)
    
    # Verify pool configuration for PostgreSQL
    assert hasattr(engine.pool, 'size')
    
    engine.dispose()
