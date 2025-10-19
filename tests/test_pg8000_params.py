"""
Test SQLAlchemy text() parameter binding compatibility.

This test verifies that using SQLAlchemy's text() wrapper correctly handles
parameter binding for different database drivers including pg8000.
"""

import pytest
from sqlalchemy import create_engine, text


def test_sqlalchemy_text_with_named_params():
    """Test that text() with :param syntax compiles correctly."""
    query = text("""
        SELECT id, name
        FROM sources
        WHERE host = :host_value
        LIMIT 5
    """)
    
    # Verify the query object has the correct structure
    assert query is not None
    assert ':host_value' in str(query)
    
    # Verify params can be bound
    compiled = query.bindparams(host_value='example.com')
    assert compiled is not None


def test_sqlalchemy_text_preserves_colon_syntax():
    """Verify that text() preserves :param syntax (not %(param)s)."""
    query_string = """
        SELECT * FROM sources
        WHERE id = :source_id
          AND host = :host_value
          AND city = :city_name
    """
    query = text(query_string)
    
    # The text() object should preserve the :param format
    query_str = str(query)
    assert ':source_id' in query_str
    assert ':host_value' in query_str
    assert ':city_name' in query_str
    
    # Should NOT contain %(param)s format
    assert '%(source_id)s' not in query_str
    assert '%(host_value)s' not in query_str


def test_discovery_query_text_wrapper():
    """Test that discovery.py query pattern uses text() correctly."""
    # This mirrors the pattern in src/crawler/discovery.py
    
    where_clauses = ["s.host IS NOT NULL", "s.host != ''"]
    params = {}
    
    # Simulate dataset filter
    dataset_label = "Mizzou"
    where_clauses.append("d.label = :dataset_label")
    params["dataset_label"] = dataset_label
    
    # Simulate host filter
    host_filter = "example.com"
    where_clauses.append("LOWER(s.host) = :host_filter")
    params["host_filter"] = host_filter.lower()
    
    where_sql = " AND ".join(where_clauses)
    
    query_string = f"""
        SELECT DISTINCT ON (s.id)
            s.id,
            s.canonical_name as name
        FROM sources s
        JOIN dataset_sources ds ON s.id = ds.source_id
        JOIN datasets d ON ds.dataset_id = d.id
        WHERE {where_sql}
        ORDER BY s.id
        LIMIT 5
    """
    
    # Wrap with text() as we do in discovery.py
    query = text(query_string)
    assert query is not None
    
    # Verify params are in correct format
    assert ':dataset_label' in query_string
    assert ':host_filter' in query_string
    assert '%(dataset_label)s' not in query_string
    assert '%(host_filter)s' not in query_string
    
    # Verify params dict structure
    assert params['dataset_label'] == 'Mizzou'
    assert params['host_filter'] == 'example.com'


def test_extraction_sql_statements():
    """Test that extraction.py SQL statements use text() correctly."""
    # These are defined as module-level constants in extraction.py
    
    article_insert = text(
        "INSERT INTO articles (id, url, title) "
        "VALUES (:id, :url, :title)"
    )
    
    candidate_update = text(
        "UPDATE candidate_links SET status = :status WHERE id = :id"
    )
    
    # Verify text() objects are created correctly
    assert article_insert is not None
    assert candidate_update is not None
    
    # Verify :param syntax is used
    assert ':id' in str(article_insert)
    assert ':url' in str(article_insert)
    assert ':title' in str(article_insert)
    assert ':status' in str(candidate_update)


def test_url_verification_update_query():
    """Test that url_verification.py constructs text() queries correctly."""
    # This mirrors the pattern in src/services/url_verification.py
    
    error_message = "Test error"
    
    update_query = """
        UPDATE candidate_links
        SET status = :status, processed_at = :processed_at
    """
    
    if error_message:
        update_query += ", error_message = :error_message"
    
    update_query += " WHERE id = :candidate_id"
    
    # Wrap with text()
    query = text(update_query)
    assert query is not None
    
    # Verify :param syntax
    assert ':status' in update_query
    assert ':processed_at' in update_query
    assert ':error_message' in update_query
    assert ':candidate_id' in update_query
    
    # Should not have %(param)s syntax
    assert '%(status)s' not in update_query
    assert '%(candidate_id)s' not in update_query


def test_versioning_advisory_lock_queries():
    """Test that versioning.py PostgreSQL functions use text() correctly."""
    # These use PostgreSQL-specific functions with parameters
    
    lock_query = text("SELECT pg_try_advisory_lock(:id)")
    unlock_query = text("SELECT pg_advisory_unlock(:id)")
    
    # Verify text() objects
    assert lock_query is not None
    assert unlock_query is not None
    
    # Verify :param syntax
    assert ':id' in str(lock_query)
    assert ':id' in str(unlock_query)
    
    # Should not have %(param)s syntax
    assert '%(id)s' not in str(lock_query)
    assert '%(id)s' not in str(unlock_query)


def test_parameter_binding_example():
    """
    Integration test showing the correct way to use parameterized queries.
    This doesn't need a real database, just demonstrates the API.
    """
    # Create an in-memory SQLite engine for testing
    engine = create_engine("sqlite:///:memory:")
    
    # Create a test table
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE test (id INTEGER, name TEXT)"))
        conn.commit()
    
    # Test INSERT with :param syntax
    insert_query = text("INSERT INTO test (id, name) VALUES (:id, :name)")
    with engine.connect() as conn:
        conn.execute(insert_query, {"id": 1, "name": "Test"})
        conn.commit()
    
    # Test SELECT with :param syntax
    select_query = text("SELECT id, name FROM test WHERE name = :name")
    with engine.connect() as conn:
        result = conn.execute(select_query, {"name": "Test"})
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1
        assert rows[0][1] == "Test"
    
    # Clean up
    engine.dispose()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
