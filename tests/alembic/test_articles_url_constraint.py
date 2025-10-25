"""Tests for articles.url unique constraint migration.

These tests verify:
1. Migration succeeds on clean database (no duplicates)
2. Migration fails when duplicates exist (safety check)
3. Unique constraint prevents duplicate inserts after migration
4. Deduplication script removes duplicates correctly
5. ON CONFLICT DO NOTHING works with the constraint
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


class TestArticlesUrlConstraint:
    """Test articles.url unique constraint migration and deduplication."""

    def test_migration_succeeds_without_duplicates(self, tmp_path):
        """Test that migration runs successfully when no duplicates exist."""
        # Create temp SQLite database
        db_path = tmp_path / "test_migration.db"
        database_url = f"sqlite:///{db_path}"

        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"

        # Run alembic upgrade to head (includes our new migration)
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Check that migration succeeded
        assert result.returncode == 0, f"Migration failed: {result.stderr}"

        # Verify database was created
        assert db_path.exists(), "Database file was not created"

        # Connect to database and verify unique index exists
        engine = create_engine(database_url)
        inspector = inspect(engine)

        # Check that articles table exists
        tables = inspector.get_table_names()
        assert "articles" in tables, "articles table not found"

        # Check that unique index exists on url column
        indexes = inspector.get_indexes("articles")
        index_names = [idx["name"] for idx in indexes]
        assert (
            "uq_articles_url" in index_names
        ), "Unique index uq_articles_url not found"

        # Verify the index is on the url column
        url_index = next(idx for idx in indexes if idx["name"] == "uq_articles_url")
        assert url_index["unique"] is True, "Index should be unique"
        assert "url" in url_index["column_names"], "Index should be on url column"

        engine.dispose()

    def test_unique_constraint_prevents_duplicates(self, tmp_path):
        """Test that unique constraint prevents duplicate article URLs."""
        # Create temp SQLite database and run migrations
        db_path = tmp_path / "test_constraint.db"
        database_url = f"sqlite:///{db_path}"

        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"

        # Run migrations
        subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Connect to database
        engine = create_engine(database_url)
        conn = engine.connect()

        try:
            # Insert a candidate link first
            candidate_id = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                INSERT INTO candidate_links (id, url, source, status)
                VALUES (:id, :url, :source, :status)
            """
                ),
                {
                    "id": candidate_id,
                    "url": "https://example.com/article1",
                    "source": "example.com",
                    "status": "article",
                },
            )
            conn.commit()

            # Insert first article
            article_id1 = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                INSERT INTO articles (id, candidate_link_id, url, title, status, text_hash, extracted_at)
                VALUES (:id, :candidate_link_id, :url, :title, :status, :text_hash, :extracted_at)
            """
                ),
                {
                    "id": article_id1,
                    "candidate_link_id": candidate_id,
                    "url": "https://example.com/article1",
                    "title": "Test Article",
                    "status": "extracted",
                    "text_hash": "hash1",
                    "extracted_at": datetime.utcnow().isoformat(),
                },
            )
            conn.commit()

            # Try to insert duplicate article with same URL - should be silently ignored
            # This tests ON CONFLICT DO NOTHING behavior
            article_id2 = str(uuid.uuid4())
            result = conn.execute(
                text(
                    """
                INSERT INTO articles (id, candidate_link_id, url, title, status, text_hash, extracted_at)
                VALUES (:id, :candidate_link_id, :url, :title, :status, :text_hash, :extracted_at)
                ON CONFLICT DO NOTHING
            """
                ),
                {
                    "id": article_id2,
                    "candidate_link_id": candidate_id,
                    "url": "https://example.com/article1",  # Duplicate URL
                    "title": "Duplicate Article",
                    "status": "extracted",
                    "text_hash": "hash2",
                    "extracted_at": datetime.utcnow().isoformat(),
                },
            )
            conn.commit()

            # Verify only one article exists
            result = conn.execute(
                text("SELECT COUNT(*) FROM articles WHERE url = :url"),
                {"url": "https://example.com/article1"},
            )
            count = result.scalar()
            assert count == 1, f"Expected 1 article, found {count}"

            # Verify it's the first article (ON CONFLICT DO NOTHING should skip the second)
            result = conn.execute(
                text("SELECT id, title FROM articles WHERE url = :url"),
                {"url": "https://example.com/article1"},
            )
            row = result.fetchone()
            assert row[0] == article_id1, "Should keep first article"
            assert row[1] == "Test Article", "Should keep first article's title"

        finally:
            conn.close()
            engine.dispose()

    def test_migration_fails_with_duplicates(self, tmp_path):
        """Test that migration fails when duplicate URLs exist (safety check)."""
        # Create temp SQLite database and run migrations up to before our migration
        db_path = tmp_path / "test_duplicates.db"
        database_url = f"sqlite:///{db_path}"

        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"

        # Run migrations up to the revision before our constraint migration
        # This is 805164cd4665 (the down_revision of our migration)
        subprocess.run(
            ["alembic", "upgrade", "805164cd4665"],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Connect and insert duplicate articles
        engine = create_engine(database_url)
        conn = engine.connect()

        try:
            # Insert a candidate link
            candidate_id = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                INSERT INTO candidate_links (id, url, source, status)
                VALUES (:id, :url, :source, :status)
            """
                ),
                {
                    "id": candidate_id,
                    "url": "https://example.com/duplicate",
                    "source": "example.com",
                    "status": "article",
                },
            )
            conn.commit()

            # Insert two articles with same URL (duplicates)
            for i in range(2):
                article_id = str(uuid.uuid4())
                conn.execute(
                    text(
                        """
                    INSERT INTO articles (id, candidate_link_id, url, title, status, text_hash, extracted_at)
                    VALUES (:id, :candidate_link_id, :url, :title, :status, :text_hash, :extracted_at)
                """
                    ),
                    {
                        "id": article_id,
                        "candidate_link_id": candidate_id,
                        "url": "https://example.com/duplicate",
                        "title": f"Duplicate Article {i+1}",
                        "status": "extracted",
                        "text_hash": f"hash{i}",
                        "extracted_at": datetime.utcnow().isoformat(),
                    },
                )
                conn.commit()

            # Verify duplicates exist
            result = conn.execute(
                text("SELECT COUNT(*) FROM articles WHERE url = :url"),
                {"url": "https://example.com/duplicate"},
            )
            count = result.scalar()
            assert count == 2, "Should have 2 duplicate articles for test setup"

        finally:
            conn.close()
            engine.dispose()

        # Now try to run our migration - should fail due to duplicates
        result = subprocess.run(
            ["alembic", "upgrade", "20251025_add_uq_articles_url"],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Migration should fail
        assert result.returncode != 0, "Migration should fail when duplicates exist"
        output = result.stdout + result.stderr
        assert (
            "duplicate" in output.lower()
            or "cannot add unique constraint" in output.lower()
        ), "Error message should mention duplicates"

    def test_on_conflict_do_nothing_works(self, tmp_path):
        """Test that ON CONFLICT DO NOTHING works correctly with the constraint."""
        # This is the exact pattern used in extraction.py
        db_path = tmp_path / "test_conflict.db"
        database_url = f"sqlite:///{db_path}"

        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"

        # Run migrations to head
        subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )

        engine = create_engine(database_url)
        conn = engine.connect()

        try:
            # Insert candidate link
            candidate_id = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                INSERT INTO candidate_links (id, url, source, status)
                VALUES (:id, :url, :source, :status)
            """
                ),
                {
                    "id": candidate_id,
                    "url": "https://example.com/test",
                    "source": "example.com",
                    "status": "article",
                },
            )
            conn.commit()

            # Simulate extraction inserting article (first time - should succeed)
            test_url = "https://example.com/test"
            for attempt in range(3):  # Try inserting same URL 3 times
                article_id = str(uuid.uuid4())
                result = conn.execute(
                    text(
                        """
                    INSERT INTO articles (id, candidate_link_id, url, title, author, 
                    publish_date, content, text, status, metadata, wire, extracted_at, 
                    created_at, text_hash) 
                    VALUES (:id, :candidate_link_id, :url, :title, :author, 
                    :publish_date, :content, :text, :status, :metadata, :wire, 
                    :extracted_at, :created_at, :text_hash) 
                    ON CONFLICT DO NOTHING
                """
                    ),
                    {
                        "id": article_id,
                        "candidate_link_id": candidate_id,
                        "url": test_url,
                        "title": f"Test Article Attempt {attempt+1}",
                        "author": "Test Author",
                        "publish_date": None,
                        "content": "Test content",
                        "text": "Test content",
                        "status": "extracted",
                        "metadata": "{}",
                        "wire": None,
                        "extracted_at": datetime.utcnow().isoformat(),
                        "created_at": datetime.utcnow().isoformat(),
                        "text_hash": f"hash_{attempt}",
                    },
                )
                conn.commit()

            # Verify only ONE article was inserted (first one)
            result = conn.execute(
                text(
                    "SELECT COUNT(*), title FROM articles WHERE url = :url GROUP BY title"
                ),
                {"url": test_url},
            )
            rows = result.fetchall()
            assert len(rows) == 1, f"Expected 1 article, found {len(rows)}"
            assert rows[0][0] == 1, "Should have exactly 1 article"
            assert "Attempt 1" in rows[0][1], "Should keep first insertion"

        finally:
            conn.close()
            engine.dispose()


class TestDeduplicationScript:
    """Test the deduplication script functionality."""

    def test_deduplication_script_dry_run(self, tmp_path, monkeypatch):
        """Test deduplication script in dry-run mode."""
        # Setup test database with duplicates
        db_path = tmp_path / "test_dedupe.db"
        database_url = f"sqlite:///{db_path}"

        # Set environment for script to use test database
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("USE_CLOUD_SQL_CONNECTOR", "false")

        # Create database and run migrations up to before constraint
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"

        subprocess.run(
            ["alembic", "upgrade", "805164cd4665"],
            capture_output=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Insert test duplicates
        engine = create_engine(database_url)
        conn = engine.connect()

        candidate_id = str(uuid.uuid4())
        conn.execute(
            text(
                """
            INSERT INTO candidate_links (id, url, source, status)
            VALUES (:id, :url, :source, :status)
        """
            ),
            {
                "id": candidate_id,
                "url": "https://example.com/dup",
                "source": "example.com",
                "status": "article",
            },
        )

        # Insert 3 duplicate articles
        for i in range(3):
            conn.execute(
                text(
                    """
                INSERT INTO articles (id, candidate_link_id, url, title, status, text_hash, extracted_at)
                VALUES (:id, :candidate_link_id, :url, :title, :status, :text_hash, :extracted_at)
            """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "candidate_link_id": candidate_id,
                    "url": "https://example.com/dup",
                    "title": f"Duplicate {i+1}",
                    "status": "extracted",
                    "text_hash": f"hash{i}",
                    "extracted_at": datetime.utcnow().isoformat(),
                },
            )
        conn.commit()
        conn.close()
        engine.dispose()

        # Run deduplication script in dry-run mode
        script_path = (
            Path(__file__).parent.parent.parent
            / "scripts"
            / "fix_article_duplicates.py"
        )
        result = subprocess.run(
            ["python", str(script_path), "--dry-run"],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        output = result.stdout

        # Verify dry-run output mentions duplicates
        assert (
            "DRY RUN" in output or "dry run" in output.lower()
        ), "Should indicate dry-run mode"
        assert (
            "2" in output or "duplicate" in output.lower()
        ), "Should report duplicates found"

        # Verify no changes were made
        engine = create_engine(database_url)
        conn = engine.connect()
        result = conn.execute(
            text("SELECT COUNT(*) FROM articles WHERE url = :url"),
            {"url": "https://example.com/dup"},
        )
        count = result.scalar()
        assert count == 3, "Dry-run should not delete any articles"
        conn.close()
        engine.dispose()
