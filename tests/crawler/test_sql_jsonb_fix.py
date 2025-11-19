"""Tests for SQL ::jsonb cast fix in source_processing.

This module tests the fix for the SQL syntax error caused by using ::jsonb
cast with bound parameters in SQLAlchemy with pg8000 driver.

Error: 'syntax error at or near ":"' at position 103
Fix: Remove ::jsonb cast since PostgreSQL automatically handles JSON string
to JSONB conversion when the column type is JSONB.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import text

from src.crawler.source_processing import SourceProcessor


class TestJsonbCastFix:
    """Test that JSONB updates work without ::jsonb cast syntax."""

    def test_rss_transient_failures_update_without_jsonb_cast(self):
        """Verify rss_transient_failures update doesn't use ::jsonb cast."""
        # Check that the source code doesn't contain problematic ::jsonb cast
        import inspect

        source = inspect.getsource(SourceProcessor)

        # The fix removed this line:
        # "rss_transient_failures = :val::jsonb, "
        # And replaced with:
        # "rss_transient_failures = :val, "
        # Check for the specific problematic pattern (not in comments)
        lines = source.split("\n")
        for line in lines:
            # Skip comments
            if line.strip().startswith("#"):
                continue
            # Check for the problematic SQL pattern
            if "::jsonb" in line and ":val" in line:
                pytest.fail(
                    f"Found problematic ::jsonb cast with bound parameter: "
                    f"{line.strip()}\n"
                    f"This causes SQL syntax errors with pg8000 driver."
                )

    def test_section_storage_uses_json_dumps_directly(self):
        """Verify section storage passes JSON string directly to JSONB column."""
        import inspect

        source = inspect.getsource(SourceProcessor)

        # Check that discovered_sections update uses json.dumps directly
        # without ::jsonb cast
        assert (
            "discovered_sections = :sections" in source
        ), "Section storage should use direct parameter binding"
        assert (
            "json.dumps(section_data)" in source
        ), "Should serialize section data with json.dumps"


@pytest.mark.integration
@pytest.mark.postgres
class TestJsonbIntegration:
    """Integration tests for JSONB column updates with PostgreSQL."""

    def test_rss_transient_failures_update_with_postgresql(self, cloud_sql_session):
        """Test that rss_transient_failures can be updated in PostgreSQL."""
        from src.models import Source

        # Create a test source
        source = Source(
            host="test-jsonb-fix.com",
            host_norm="test-jsonb-fix.com",
            canonical_name="Test JSONB Fix",
            rss_transient_failures=[],
        )
        cloud_sql_session.add(source)
        cloud_sql_session.flush()  # Flush to DB but don't commit transaction
        source_id = source.id

        # Update rss_transient_failures using the same pattern
        # as source_processing
        failure_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "500",
        }
        existing = [failure_record]

        # This is the SQL pattern from source_processing.py after fix
        update_sql = text(
            """
            UPDATE sources SET
                rss_transient_failures = :val,
                rss_consecutive_failures = 0
            WHERE id = :id
            """
        )

        # Execute the update - should NOT cause SQL syntax error
        cloud_sql_session.execute(
            update_sql, {"val": json.dumps(existing), "id": source_id}
        )
        cloud_sql_session.flush()

        # Expire the object so SQLAlchemy reloads it from DB
        cloud_sql_session.expire(source)

        # Verify the update worked
        updated_source = cloud_sql_session.query(Source).filter_by(id=source_id).first()
        assert updated_source is not None
        assert isinstance(updated_source.rss_transient_failures, list)
        assert len(updated_source.rss_transient_failures) == 1
        assert "timestamp" in updated_source.rss_transient_failures[0]
        assert updated_source.rss_transient_failures[0]["status"] == "500"

        # No cleanup needed - fixture's automatic rollback handles it

    def test_discovered_sections_update_with_postgresql(self, cloud_sql_session):
        """Test that discovered_sections can be updated in PostgreSQL."""
        from src.models import Source

        # Create a test source
        source = Source(
            host="test-sections-fix.com",
            host_norm="test-sections-fix.com",
            canonical_name="Test Sections Fix",
            discovered_sections={},
        )
        cloud_sql_session.add(source)
        cloud_sql_session.flush()  # Flush to DB but don't commit transaction
        source_id = source.id

        # Simulate section discovery storage
        section_data = {
            "sections": [
                {
                    "name": "News",
                    "url": "https://test-sections-fix.com/news",
                    "discovered_at": datetime.utcnow().isoformat(),
                }
            ],
            "discovered_at": datetime.utcnow().isoformat(),
        }

        # This is the SQL pattern from source_processing.py
        update_sql = text(
            """
            UPDATE sources SET
                discovered_sections = :sections,
                section_last_updated = :updated_at
            WHERE id = :id
            """
        )

        # Execute the update - should NOT cause SQL syntax error
        cloud_sql_session.execute(
            update_sql,
            {
                "sections": json.dumps(section_data),
                "updated_at": datetime.utcnow(),
                "id": source_id,
            },
        )
        cloud_sql_session.flush()

        # Expire the object so SQLAlchemy reloads it from DB
        cloud_sql_session.expire(source)

        # Verify the update worked
        updated_source = cloud_sql_session.query(Source).filter_by(id=source_id).first()
        assert updated_source is not None
        assert isinstance(updated_source.discovered_sections, dict)
        assert "sections" in updated_source.discovered_sections
        assert len(updated_source.discovered_sections["sections"]) == 1
        assert updated_source.discovered_sections["sections"][0]["name"] == "News"

        # No cleanup needed - fixture's automatic rollback handles it

    def test_jsonb_update_handles_complex_nested_json(self, cloud_sql_session):
        """Test JSONB updates work with complex nested JSON structures."""
        from src.models import Source

        source = Source(
            host="test-complex-json.com",
            host_norm="test-complex-json.com",
            canonical_name="Test Complex JSON",
            rss_transient_failures=[],
        )
        cloud_sql_session.add(source)
        cloud_sql_session.flush()  # Flush to DB but don't commit transaction
        source_id = source.id

        # Create a complex nested structure
        complex_data = [
            {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "500",
                "metadata": {
                    "retries": 3,
                    "last_error": "Connection timeout",
                    "headers": {"user-agent": "test", "accept": "*/*"},
                },
            }
        ]

        update_sql = text(
            "UPDATE sources SET rss_transient_failures = :val WHERE id = :id"
        )

        # Should handle complex JSON without issues
        cloud_sql_session.execute(
            update_sql, {"val": json.dumps(complex_data), "id": source_id}
        )
        cloud_sql_session.flush()

        # Expire the object so SQLAlchemy reloads it from DB
        cloud_sql_session.expire(source)

        # Verify nested structure preserved
        updated_source = cloud_sql_session.query(Source).filter_by(id=source_id).first()
        assert updated_source.rss_transient_failures[0]["metadata"]["retries"] == 3
        assert (
            updated_source.rss_transient_failures[0]["metadata"]["last_error"]
            == "Connection timeout"
        )

        # No cleanup needed - fixture's automatic rollback handles it


class TestJsonbCastRemoval:
    """Test that the problematic ::jsonb cast has been removed."""

    def test_no_jsonb_cast_in_update_statements(self):
        """Verify no UPDATE statements use ::jsonb with bound parameters."""
        import inspect

        from src.crawler import source_processing

        source = inspect.getsource(source_processing)

        # Check for the problematic pattern
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "::jsonb" in line and ":val" in line:
                pytest.fail(
                    f"Found problematic ::jsonb cast with bound parameter "
                    f"at line {i+1}: {line.strip()}\n"
                    f"This causes SQL syntax errors with pg8000 driver."
                )

    def test_json_dumps_used_for_jsonb_columns(self):
        """Verify json.dumps() is used to serialize data for JSONB columns."""
        import inspect

        source = inspect.getsource(SourceProcessor)

        # Should use json.dumps() to serialize before passing to DB
        assert "json.dumps" in source, "Should use json.dumps() to serialize JSON data"
