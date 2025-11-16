"""Tests for parallel extraction with row-level locking."""

import inspect
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import text as sql_text

from src.models import CandidateLink, Source


@pytest.mark.integration
def test_extraction_query_has_skip_locked():
    """Test extraction query includes FOR UPDATE SKIP LOCKED for parallel processing."""
    from src.cli.commands.extraction import _process_batch

    # Read the source to verify SKIP LOCKED is present
    source = inspect.getsource(_process_batch)

    assert "FOR UPDATE" in source, "Query must include FOR UPDATE"
    assert "SKIP LOCKED" in source, "Query must include SKIP LOCKED"
    assert (
        "FOR UPDATE OF cl SKIP LOCKED" in source
    ), "Query must lock candidate_links table with SKIP LOCKED"


@pytest.mark.integration
def test_extraction_query_has_dialect_detection():
    """Test extraction query includes dialect detection for PostgreSQL."""
    from src.cli.commands.extraction import _process_batch

    # Read the source to verify dialect detection is present
    source = inspect.getsource(_process_batch)

    assert "dialect_name" in source, "Query must detect database dialect"
    assert (
        'dialect_name == "postgresql"' in source
    ), "Query must check for PostgreSQL dialect"


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
def test_parallel_extraction_no_duplicates(cloud_sql_engine):
    """Test parallel extractions process different candidate links.

    This test uses cloud_sql_engine instead of cloud_sql_session to avoid
    transaction isolation issues. Each worker thread creates its own session
    from the engine, and all changes are committed to the database.
    """
    import threading

    from sqlalchemy import text as sql_text
    from sqlalchemy.orm import sessionmaker

    # Create a session for setup
    SessionLocal = sessionmaker(bind=cloud_sql_engine)
    setup_session = SessionLocal()

    try:
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
        setup_session.add(source1)
        setup_session.add(source2)
        setup_session.flush()

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

        setup_session.add_all(candidate_links)
        # Commit so worker threads can see the data
        setup_session.commit()

        # Track which candidate_link_ids were processed by each thread
        processed_by_thread1 = set()
        processed_by_thread2 = set()

        import time

        # Use a barrier to ensure threads start at the same time
        start_barrier = threading.Barrier(2)

        def mock_extraction_worker(processed_set):
            """Mock worker that simulates extraction by selecting candidate links."""
            # Create a new session for this thread from the engine
            SessionLocal = sessionmaker(bind=cloud_sql_engine)
            worker_session = SessionLocal()

            try:
                # Wait for both threads to be ready before starting
                start_barrier.wait()

                # This simulates _process_batch selecting candidate links
                # In the real implementation, this would call
                # extractor.extract_content()
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
                    ORDER BY cl.discovered_at
                    LIMIT 20
                    FOR UPDATE OF cl SKIP LOCKED
                """
                )

                result = worker_session.execute(query)
                rows = result.fetchall()

                # Simulate processing time to keep locks held longer
                time.sleep(0.1)

                for row in rows:
                    processed_set.add(str(row[0]))  # Add candidate_link_id

                worker_session.commit()
            finally:
                worker_session.close()

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

        # Verify no duplicates: each thread should process different candidate
        # links
        duplicates = processed_by_thread1.intersection(processed_by_thread2)
        assert len(duplicates) == 0, (
            f"Found {len(duplicates)} duplicate candidate_link_ids "
            f"processed by both threads"
        )

        # Verify both threads processed some links
        assert (
            len(processed_by_thread1) > 0
        ), "Thread 1 should have processed some candidate links"
        assert (
            len(processed_by_thread2) > 0
        ), "Thread 2 should have processed some candidate links"

        # Total processed should be reasonable (may be less than 40 due to
        # random ordering and timing)
        total_processed = len(processed_by_thread1) + len(processed_by_thread2)
        assert (
            total_processed <= 40
        ), f"Processed {total_processed} links, but LIMIT was 20 per thread"
        assert total_processed > 0, "No links were processed by either thread"

    finally:
        # Cleanup: delete test data
        setup_session.query(CandidateLink).filter(
            CandidateLink.source.in_(["test1.example.com", "test2.example.com"])
        ).delete(synchronize_session=False)
        setup_session.query(Source).filter(
            Source.host.in_(["test1.example.com", "test2.example.com"])
        ).delete(synchronize_session=False)
        setup_session.commit()
        setup_session.close()

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
    assert (
        len(duplicates) == 0
    ), f"Found {len(duplicates)} duplicate candidate_link_ids processed by both threads"

    # Verify both threads processed some links
    assert (
        len(processed_by_thread1) > 0
    ), "Thread 1 should have processed some candidate links"
    assert (
        len(processed_by_thread2) > 0
    ), "Thread 2 should have processed some candidate links"

    # Total processed should be reasonable (may be less than 40 due to
    # random ordering and timing)
    total_processed = len(processed_by_thread1) + len(processed_by_thread2)
    assert (
        total_processed <= 40
    ), f"Total processed ({total_processed}) should not exceed requested limit (40)"
