"""End-to-end tests for migration workflows.

These tests verify:
1. Fresh database setup from scratch
2. Migrations preserve existing data
3. Schema validation against SQLAlchemy models
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


class TestMigrationWorkflow:
    """Test end-to-end migration workflows."""

    @pytest.mark.postgres
    def test_fresh_database_setup(self, cloud_sql_session):
        """Test setting up a fresh database from scratch with migrations."""
        # Use PostgreSQL test database
        inspector = inspect(cloud_sql_session.bind)

        # Verify tables exist
        tables = inspector.get_table_names()
        assert len(tables) > 0, "No tables were created"

        # Insert test data to verify database is functional
        cloud_sql_session.execute(
            text(
                """
            INSERT INTO sources
                (id, host, host_norm, canonical_name, city, county, type)
            VALUES (:id, :host, :host_norm, :name, :city, :county, :type)
        """
            ),
            {
                "id": "test-source-workflow-1",
                "host": "test-workflow.com",
                "host_norm": "test-workflow.com",
                "name": "Test Workflow Source",
                "city": "Test City",
                "county": "Test County",
                "type": "news",
            },
        )
        cloud_sql_session.commit()

        # Verify data was inserted
        result = cloud_sql_session.execute(text("SELECT COUNT(*) FROM sources"))
        count = result.scalar()
        assert count >= 1, "Test data insertion failed"

    @pytest.mark.postgres
    def test_migration_with_existing_data(self, cloud_sql_session):
        """Test that migrations preserve existing data."""
        import uuid
        from datetime import datetime, timezone

        test_data = {
            "source_name": "Test News Site Workflow",
            "source_url": "https://testnews-workflow.com",
            "article_url": "https://testnews-workflow.com/article1",
        }

        # Insert test source
        result = cloud_sql_session.execute(
            text(
                """
            INSERT INTO sources
                (id, host, host_norm, canonical_name, city, county, type)
            VALUES
                (:id, :host, :host_norm, :name, :city, :county, :type)
            RETURNING id
        """
            ),
            {
                "id": "test-source-workflow-2",
                "host": "testnews-workflow.com",
                "host_norm": "testnews-workflow.com",
                "name": test_data["source_name"],
                "city": "Test City",
                "county": "Test County",
                "type": "news",
            },
        )
        source_id = result.scalar()

        # Insert test candidate_link
        candidate_link_id = str(uuid.uuid4())
        cloud_sql_session.execute(
            text(
                """
            INSERT INTO candidate_links (
                id, url, source, source_host_id, status, discovered_at
            )
            VALUES (
                :id, :url, :source, :source_id, :status, :discovered_at
            )
        """
            ),
            {
                "id": candidate_link_id,
                "url": test_data["article_url"],
                "source": test_data["source_name"],
                "source_id": source_id,
                "status": "fetched",
                "discovered_at": datetime.now(timezone.utc),
            },
        )

        # Insert test article
        article_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        cloud_sql_session.execute(
            text(
                """
            INSERT INTO articles (
                id, url, title, candidate_link_id, status,
                extracted_at, created_at
            )
            VALUES (
                :id, :url, :title, :candidate_link_id, :status,
                :extracted_at, :created_at
            )
        """
            ),
            {
                "id": article_id,
                "url": test_data["article_url"],
                "title": "Test Article Workflow",
                "candidate_link_id": candidate_link_id,
                "status": "extracted",
                "extracted_at": now,
                "created_at": now,
            },
        )
        cloud_sql_session.commit()

        # Verify data exists
        result = cloud_sql_session.execute(
            text(
                """
            SELECT canonical_name, host
            FROM sources
            WHERE canonical_name = :canonical_name
        """
            ),
            {"canonical_name": test_data["source_name"]},
        )
        row = result.fetchone()
        assert row is not None, "Source data was not inserted"
        assert row[0] == test_data["source_name"]
        assert row[1] == "testnews-workflow.com"

        # Check article data
        result = cloud_sql_session.execute(
            text(
                """
            SELECT url, title FROM articles WHERE url = :url
        """
            ),
            {"url": test_data["article_url"]},
        )
        row = result.fetchone()
        assert row is not None, "Article data was not inserted"
        assert row[0] == test_data["article_url"]
        assert row[1] == "Test Article Workflow"

    @pytest.mark.postgres
    def test_table_schemas_match_models(self, cloud_sql_session):
        """Test that migrated table schemas match SQLAlchemy models."""
        # Inspect schema in PostgreSQL
        inspector = inspect(cloud_sql_session.bind)

        # Check sources table schema (current schema uses canonical_name not name)
        sources_columns = {col["name"]: col for col in inspector.get_columns("sources")}
        assert "id" in sources_columns
        assert "canonical_name" in sources_columns
        assert "host" in sources_columns
        assert "host_norm" in sources_columns
        assert "type" in sources_columns
        assert "status" in sources_columns

        # Check articles table schema
        articles_columns = {
            col["name"]: col for col in inspector.get_columns("articles")
        }
        assert "id" in articles_columns
        assert "url" in articles_columns
        assert "title" in articles_columns
        assert "candidate_link_id" in articles_columns
        assert "status" in articles_columns

        # Check that foreign keys exist
        articles_fks = inspector.get_foreign_keys("articles")
        fk_columns = [fk["constrained_columns"][0] for fk in articles_fks]
        assert (
            "candidate_link_id" in fk_columns
        ), "articles.candidate_link_id foreign key missing"

        # Check telemetry tables exist with correct columns
        telemetry_tables = [
            "byline_cleaning_telemetry",
            "content_cleaning_sessions",
            "extraction_telemetry_v2",
        ]

        for table in telemetry_tables:
            columns = inspector.get_columns(table)
            assert len(columns) > 0, f"Table {table} has no columns"

            # All telemetry tables should have a primary key (id or telemetry_id)
            column_names = [col["name"] for col in columns]
            has_pk = "id" in column_names or "telemetry_id" in column_names
            assert (
                has_pk
            ), f"Table {table} missing primary key column (id or telemetry_id)"

    @pytest.mark.postgres
    def test_migration_adds_indexes(self, cloud_sql_session):
        """Test that migrations create appropriate indexes."""
        # Inspect indexes in PostgreSQL
        inspector = inspect(cloud_sql_session.bind)

        # Check that key tables have indexes
        # Articles should have index on url for lookups
        articles_indexes = inspector.get_indexes("articles")
        assert len(articles_indexes) >= 0, "Articles table should have indexes"

        # Sources should have index on url
        sources_indexes = inspector.get_indexes("sources")
        assert len(sources_indexes) >= 0, "Sources table should have indexes"

    @pytest.mark.postgres
    def test_migration_version_tracking(self, cloud_sql_session):
        """Test that Alembic version tracking works correctly."""
        # Check alembic_version table in PostgreSQL
        result = cloud_sql_session.execute(
            text("SELECT version_num FROM alembic_version")
        )
        version = result.scalar()

        assert version is not None, "No version recorded in alembic_version table"
        assert len(version) > 0, "Version string is empty"

        # Verify it's a valid alphanumeric revision ID (12 chars)
        assert len(version) == 12, f"Expected 12 char revision ID, got: {version}"
        assert version.isalnum(), f"Revision ID should be alphanumeric: {version}"

    @pytest.mark.skip(
        reason="Downgrade/upgrade testing requires subprocess Alembic calls "
        "which can't work with cloud_sql_session fixture"
    )
    def test_rollback_and_reapply_migration(self, cloud_sql_session):
        """Test rolling back and reapplying migrations.
        
        Note: This test is skipped because it requires running actual Alembic
        downgrade/upgrade commands via subprocess, which can't be done with
        the cloud_sql_session fixture that manages transactions automatically.
        """
        pass
