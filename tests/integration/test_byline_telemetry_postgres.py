"""Integration tests for byline telemetry with PostgreSQL and Alembic migrations.

These tests verify that byline telemetry INSERT statements work correctly against
PostgreSQL databases with schemas created by Alembic migrations, catching issues
that SQLite-only unit tests might miss.
"""

import json
import os
from pathlib import Path

import pytest

from src.telemetry.store import TelemetryStore
from src.utils import byline_telemetry as bt

# Check if PostgreSQL is available for testing
POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_db_uri():
    """Get PostgreSQL test database URI."""
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured (set TEST_DATABASE_URL)")
    return POSTGRES_TEST_URL


@pytest.fixture
def postgres_store_with_alembic(postgres_db_uri):
    """PostgreSQL TelemetryStore with Alembic-migrated schema.

    This fixture creates a test database with the production schema
    (created via Alembic migrations) rather than the code's CREATE TABLE,
    ensuring tests catch schema drift issues.
    """
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured")

    # Create store - this will use the Alembic-migrated schema
    # Note: In a full implementation, this would run Alembic migrations
    # For now, we assume the test database has been migrated externally
    store = TelemetryStore(database=postgres_db_uri, async_writes=False)

    # Clean up any existing test data
    with store.connection() as conn:
        # Try to clean up, but don't fail if tables don't exist
        try:
            conn.execute(
                "DELETE FROM byline_transformation_steps WHERE telemetry_id LIKE 'test-%'"
            )
            conn.execute("DELETE FROM byline_cleaning_telemetry WHERE id LIKE 'test-%'")
            conn.commit()
        except Exception:
            # Tables might not exist yet, that's ok
            pass

    yield store

    # Cleanup after test
    with store.connection() as conn:
        try:
            conn.execute(
                "DELETE FROM byline_transformation_steps WHERE telemetry_id LIKE 'test-%'"
            )
            conn.execute("DELETE FROM byline_cleaning_telemetry WHERE id LIKE 'test-%'")
            conn.commit()
        except Exception:
            pass


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestBylineTelemetryPostgreSQL:
    """Test byline telemetry against PostgreSQL with Alembic schema."""

    def test_byline_telemetry_insert_postgres(self, postgres_store_with_alembic):
        """Verify byline telemetry INSERT works against Alembic-migrated PostgreSQL.

        This test catches issues like:
        - Column count mismatches between code and Alembic migrations
        - Missing required columns in INSERT statements
        - PostgreSQL-specific data type issues
        """
        store = postgres_store_with_alembic
        telemetry = bt.BylineCleaningTelemetry(
            enable_telemetry=True,
            store=store,
        )

        # Start a cleaning session
        telemetry_id = telemetry.start_cleaning_session(
            raw_byline="By Jane Doe, Example News",
            article_id="test-art-1",
            candidate_link_id="test-cl-1",
            source_id="test-src-1",
            source_name="Example News",
            source_canonical_name="Example",
        )

        # Log some transformation steps
        telemetry.log_transformation_step(
            step_name="email_removal",
            input_text="By Jane Doe <jane@example.com>",
            output_text="By Jane Doe",
            removed_content="jane@example.com",
            confidence_delta=0.1,
        )

        telemetry.log_transformation_step(
            step_name="source_removal",
            input_text="By Jane Doe, Example News",
            output_text="By Jane Doe",
            removed_content="Example News",
            confidence_delta=0.2,
        )

        # Finalize the session
        telemetry.finalize_cleaning_session(
            final_authors=["Jane Doe"],
            cleaning_method="ml",
            likely_valid_authors=True,
            likely_noise=False,
            requires_manual_review=False,
        )

        # Ensure data is written
        telemetry.flush()

        # Verify the data was inserted correctly
        with store.connection() as conn:
            # Query the main telemetry record
            result = conn.execute(
                "SELECT raw_byline, final_authors_json, has_email, "
                "source_name_removed, likely_valid_authors, confidence_score, "
                "human_label, human_notes, reviewed_by, reviewed_at "
                "FROM byline_cleaning_telemetry WHERE id = ?",
                (telemetry_id,),
            )
            row = result.fetchone()

            assert row is not None, "Telemetry record not found in PostgreSQL"

            # Verify core fields (use column names for dict-like access)
            assert row["raw_byline"] == "By Jane Doe, Example News"

            # Parse and verify JSON field
            final_authors = json.loads(row["final_authors_json"])
            assert final_authors == ["Jane Doe"]

            # Verify boolean fields
            assert row["has_email"] or row["has_email"] == 1  # handle both formats
            assert row["source_name_removed"] or row["source_name_removed"] == 1
            assert row["likely_valid_authors"] or row["likely_valid_authors"] == 1

            # Verify numeric fields
            assert abs(row["confidence_score"] - 0.3) < 0.01

            # Verify new schema columns exist and are NULL (not inserted)
            assert row["human_label"] is None
            assert row["human_notes"] is None
            assert row["reviewed_by"] is None
            assert row["reviewed_at"] is None

            # Query transformation steps
            result = conn.execute(
                "SELECT step_number, step_name, input_text, output_text "
                "FROM byline_transformation_steps "
                "WHERE telemetry_id = ? ORDER BY step_number",
                (telemetry_id,),
            )
            steps = result.fetchall()

            assert len(steps) == 2
            assert steps[0]["step_name"] == "email_removal"
            assert steps[1]["step_name"] == "source_removal"

    def test_schema_column_count_matches(self, postgres_store_with_alembic):
        """Verify the table has the expected number of columns.

        This test detects schema drift by counting actual columns in PostgreSQL.
        """
        store = postgres_store_with_alembic

        with store.connection() as conn:
            # Query the actual table schema
            result = conn.execute(
                """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'byline_cleaning_telemetry'
                ORDER BY ordinal_position
            """
            )
            columns = [row["column_name"] for row in result.fetchall()]

            # Expected columns from Alembic migration (32 columns)
            expected_columns = [
                "id",
                "article_id",
                "candidate_link_id",
                "source_id",
                "source_name",
                "raw_byline",
                "raw_byline_length",
                "raw_byline_words",
                "extraction_timestamp",
                "cleaning_method",
                "source_canonical_name",
                "final_authors_json",
                "final_authors_count",
                "final_authors_display",
                "confidence_score",
                "processing_time_ms",
                "has_wire_service",
                "has_email",
                "has_title",
                "has_organization",
                "source_name_removed",
                "duplicates_removed_count",
                "likely_valid_authors",
                "likely_noise",
                "requires_manual_review",
                "cleaning_errors",
                "parsing_warnings",
                "human_label",
                "human_notes",
                "reviewed_by",
                "reviewed_at",
                "created_at",
            ]

            # Verify all expected columns exist
            missing_columns = set(expected_columns) - set(columns)
            assert (
                not missing_columns
            ), f"Missing columns in PostgreSQL table: {missing_columns}"

            # Verify no unexpected extra columns
            extra_columns = set(columns) - set(expected_columns)
            assert (
                not extra_columns
            ), f"Unexpected extra columns in PostgreSQL table: {extra_columns}"

            # Verify exact column count (32 in Alembic migration)
            assert (
                len(columns) == 32
            ), f"Expected 32 columns in PostgreSQL table, found {len(columns)}"

    def test_byline_telemetry_with_human_review_fields(
        self, postgres_store_with_alembic
    ):
        """Test that human review fields can be populated.

        This test verifies that the schema supports the additional fields
        added in the Alembic migration for human review/labeling.
        """
        store = postgres_store_with_alembic

        # Insert a record with human review fields populated
        with store.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO byline_cleaning_telemetry (
                    id, raw_byline, extraction_timestamp,
                    cleaning_method, final_authors_json,
                    final_authors_count, confidence_score,
                    has_wire_service, has_email, has_title,
                    has_organization, source_name_removed,
                    duplicates_removed_count, human_label,
                    human_notes, reviewed_by, reviewed_at,
                    created_at
                ) VALUES (
                    ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """,
                (
                    "test-human-review-1",
                    "By John Smith",
                    "manual",
                    '["John Smith"]',
                    1,
                    0.9,
                    False,
                    False,
                    False,
                    False,
                    False,
                    0,
                    "valid_author",
                    "Looks good to me",
                    "test_reviewer",
                ),
            )
            conn.commit()

        # Verify the record was inserted with human review data
        with store.connection() as conn:
            result = conn.execute(
                "SELECT human_label, human_notes, reviewed_by "
                "FROM byline_cleaning_telemetry WHERE id = ?",
                ("test-human-review-1",),
            )
            row = result.fetchone()

            assert row is not None
            assert row["human_label"] == "valid_author"
            assert row["human_notes"] == "Looks good to me"
            assert row["reviewed_by"] == "test_reviewer"


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestSchemaValidation:
    """Tests that validate schema consistency between code and database."""

    def test_insert_statement_has_all_required_columns(self):
        """Verify INSERT statement in code includes all required columns.

        This test parses the INSERT statement in byline_telemetry.py and
        ensures it includes all columns that have NOT NULL constraints.
        """
        # Read the INSERT statement from the code
        telemetry_file = (
            Path(__file__).parent.parent.parent
            / "src"
            / "utils"
            / "byline_telemetry.py"
        )
        with open(telemetry_file) as f:
            content = f.read()

        # Count columns in INSERT statement
        # Look for the INSERT INTO byline_cleaning_telemetry statement
        import re

        insert_match = re.search(
            r"INSERT INTO byline_cleaning_telemetry \((.*?)\) VALUES",
            content,
            re.DOTALL,
        )

        assert insert_match, "Could not find INSERT statement in byline_telemetry.py"

        columns_str = insert_match.group(1)
        insert_columns = [c.strip() for c in columns_str.split(",") if c.strip()]

        # Expected minimum columns (all 32 from Alembic migration)
        expected_columns = {
            "id",
            "article_id",
            "candidate_link_id",
            "source_id",
            "source_name",
            "raw_byline",
            "raw_byline_length",
            "raw_byline_words",
            "extraction_timestamp",
            "cleaning_method",
            "source_canonical_name",
            "final_authors_json",
            "final_authors_count",
            "final_authors_display",
            "confidence_score",
            "processing_time_ms",
            "has_wire_service",
            "has_email",
            "has_title",
            "has_organization",
            "source_name_removed",
            "duplicates_removed_count",
            "likely_valid_authors",
            "likely_noise",
            "requires_manual_review",
            "cleaning_errors",
            "parsing_warnings",
            "human_label",
            "human_notes",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        }

        actual_columns = set(insert_columns)

        # Check for missing columns
        missing = expected_columns - actual_columns
        assert not missing, (
            f"INSERT statement missing columns: {missing}\n"
            f"This indicates schema drift between code and Alembic migration."
        )

        # Verify column count is exactly 32
        assert len(insert_columns) == 32, (
            f"INSERT statement should have 32 columns, found {len(insert_columns)}\n"
            f"Columns: {insert_columns}"
        )
