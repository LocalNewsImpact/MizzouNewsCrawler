"""Tests for parallel extraction with row-level locking."""

import inspect
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import text as sql_text

from src.models import Article, CandidateLink, Source


@pytest.mark.integration
def test_extraction_query_has_skip_locked():
    """Test extraction query includes FOR UPDATE SKIP LOCKED for parallel processing."""
    from src.cli.commands.extraction import _process_batch

    # Read the source to verify SKIP LOCKED is present
    source = inspect.getsource(_process_batch)

    assert "FOR UPDATE" in source, "Query must include FOR UPDATE"
    assert "SKIP LOCKED" in source, "Query must include SKIP LOCKED"
    assert "FOR UPDATE OF cl SKIP LOCKED" in source, (
        "Query must lock candidate_links table with SKIP LOCKED"
    )


@pytest.mark.integration
def test_extraction_query_has_dialect_detection():
    """Test extraction query includes dialect detection for PostgreSQL."""
    from src.cli.commands.extraction import _process_batch

    # Read the source to verify dialect detection is present
    source = inspect.getsource(_process_batch)

    assert "dialect_name" in source, "Query must detect database dialect"
    assert 'dialect_name == "postgresql"' in source, (
        "Query must check for PostgreSQL dialect"
    )


@pytest.mark.postgres
@pytest.mark.integration
def test_skip_locked_syntax_is_valid_postgres(cloud_sql_session):
    """Test the SKIP LOCKED query syntax works with PostgreSQL."""
    # This is the actual query pattern from extraction.py
    query = sql_text(
        """
        SELECT cl.id, cl.url, cl.source, cl.status
        FROM candidate_links cl
        WHERE cl.status = 'article'
        AND cl.id NOT IN (
            SELECT candidate_link_id FROM articles
            WHERE candidate_link_id IS NOT NULL
        )
        ORDER BY RANDOM()
        LIMIT 10
        FOR UPDATE OF cl SKIP LOCKED
    """
    )

    # Should execute without syntax error
    result = cloud_sql_session.execute(query)
    rows = result.fetchall()
    assert isinstance(rows, list)


@pytest.mark.postgres
@pytest.mark.integration
def test_parallel_extraction_no_duplicates(cloud_sql_session):
    """Test that parallel extractions process different candidate links without duplicates."""
    import threading
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from src.cli.commands.extraction import _process_batch
    from src.models.database import DatabaseManager

    # Create test sources
    source1 = Source(
        id=uuid4(),
        host="test1.example.com",
        host_norm="test1.example.com",
        canonical_name="Test Source 1",
        status="active",
    )
    source2 = Source(
        id=uuid4(),
        host="test2.example.com",
        host_norm="test2.example.com",
        canonical_name="Test Source 2",
        status="active",
    )
    cloud_sql_session.add(source1)
    cloud_sql_session.add(source2)
    cloud_sql_session.flush()

    # Create 60 candidate links (30 per source) with status='article'
    candidate_links = []
    for i in range(30):
        cl1 = CandidateLink(
            id=str(uuid4()),
            url=f"https://test1.example.com/article-{i}",
            source="test1.example.com",
            source_id=source1.id,
            status="article",
            discovered_at=datetime.utcnow(),
        )
        cl2 = CandidateLink(
            id=str(uuid4()),
            url=f"https://test2.example.com/article-{i}",
            source="test2.example.com",
            source_id=source2.id,
            status="article",
            discovered_at=datetime.utcnow(),
        )
        candidate_links.extend([cl1, cl2])

    cloud_sql_session.add_all(candidate_links)
    cloud_sql_session.commit()

    # Track which candidate_link_ids were processed by each thread
    processed_by_thread1 = set()
    processed_by_thread2 = set()

    def mock_extraction_worker(processed_set):
        """Mock worker that simulates extraction by selecting candidate links."""
        # Create a new session for this thread
        db = DatabaseManager()
        session = db.session

        try:
            # This simulates _process_batch selecting candidate links
            # In the real implementation, this would call extractor.extract_content()
            # But for this test, we just need to verify row locking works
            query = sql_text(
                """
                SELECT cl.id, cl.url, cl.source, cl.status
                FROM candidate_links cl
                WHERE cl.status = 'article'
                AND cl.id NOT IN (
                    SELECT candidate_link_id FROM articles
                    WHERE candidate_link_id IS NOT NULL
                )
                ORDER BY RANDOM()
                LIMIT 20
                FOR UPDATE OF cl SKIP LOCKED
            """
            )

            result = session.execute(query)
            rows = result.fetchall()

            for row in rows:
                processed_set.add(str(row[0]))  # Add candidate_link_id

            session.commit()
        finally:
            session.close()

    # Run two threads concurrently
    thread1 = threading.Thread(
        target=mock_extraction_worker, args=(processed_by_thread1,)
    )
    thread2 = threading.Thread(
        target=mock_extraction_worker, args=(processed_by_thread2,)
    )

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()

    # Verify no duplicates: each thread should process different candidate links
    duplicates = processed_by_thread1.intersection(processed_by_thread2)
    assert len(duplicates) == 0, (
        f"Found {len(duplicates)} duplicate candidate_link_ids processed by both threads"
    )

    # Verify both threads processed some links
    assert len(processed_by_thread1) > 0, (
        "Thread 1 should have processed some candidate links"
    )
    assert len(processed_by_thread2) > 0, (
        "Thread 2 should have processed some candidate links"
    )

    # Total processed should be reasonable (may be less than 40 due to random ordering and timing)
    total_processed = len(processed_by_thread1) + len(processed_by_thread2)
    assert total_processed <= 40, (
        f"Total processed ({total_processed}) should not exceed requested limit (40)"
    )
