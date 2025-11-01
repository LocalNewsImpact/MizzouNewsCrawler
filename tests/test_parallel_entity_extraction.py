"""Tests for parallel entity extraction with row-level locking."""

import inspect

import pytest


@pytest.mark.integration
def test_entity_extraction_query_has_skip_locked():
    """Test entity extraction query includes FOR UPDATE SKIP LOCKED."""
    from src.cli.commands.entity_extraction import (
        handle_entity_extraction_command,
    )

    # Read the source to verify SKIP LOCKED is present
    source = inspect.getsource(handle_entity_extraction_command)

    assert "FOR UPDATE" in source, "Query must include FOR UPDATE"
    assert "SKIP LOCKED" in source, "Query must include SKIP LOCKED"
    assert (
        "FOR UPDATE OF a SKIP LOCKED" in source
    ), "Query must lock articles table with SKIP LOCKED"


@pytest.mark.postgres
@pytest.mark.integration
def test_skip_locked_syntax_is_valid_postgres(cloud_sql_session):
    """Test the SKIP LOCKED query syntax works with PostgreSQL."""
    from sqlalchemy import text as sql_text

    # This is the actual query from entity_extraction.py
    query = sql_text("""
        SELECT a.id
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.content IS NOT NULL
        AND a.text IS NOT NULL
        AND a.status != 'error'
        ORDER BY cl.source_id, cl.dataset_id
        LIMIT 10
        FOR UPDATE OF a SKIP LOCKED
    """)

    # Should execute without syntax error
    result = cloud_sql_session.execute(query)
    rows = result.fetchall()
    assert isinstance(rows, list)
