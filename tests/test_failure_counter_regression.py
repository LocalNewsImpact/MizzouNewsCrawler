"""Test that failure counter is actually set when discovery finds no articles.

This test reproduces the production issue where sources with 0 articles
don't have the no_effective_methods_consecutive counter set.
"""

from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from src.crawler.discovery import NewsDiscovery
from src.crawler.source_processing import SourceProcessor


@pytest.mark.integration
@pytest.mark.postgres
def test_failure_counter_set_when_no_articles_found(cloud_sql_engine):
    """Test that counter is incremented when discovery finds nothing.

    Note: This test uses cloud_sql_engine directly (not cloud_sql_session)
    because it needs actual committed data visible to new connections.
    The transactional fixture would rollback changes, making them invisible
    to Discovery's separate database connections.
    """
    # Create a real session WITHOUT the transaction wrapper
    SessionLocal = sessionmaker(bind=cloud_sql_engine)
    session = SessionLocal()

    try:
        # Create a real source in the database
        from src.models import Source

        source = Source(
            host="example-regression.com",
            host_norm="example-regression.com",
            canonical_name="Example Regression Test",
            meta={"frequency": "daily"},  # Use 'meta' attribute, not 'metadata'
        )
        session.add(source)
        session.commit()  # This actually commits to the database
        source_id = source.id

        # Verify source exists immediately after commit
        test_check = session.query(Source).filter_by(id=source_id).first()
        assert test_check is not None, "Source should exist after commit"
        print(f"\n=== Source created and committed: {source_id} ===")
        print(f"Source.meta = {test_check.meta}")

        # Get database URL from the engine
        database_url = str(cloud_sql_engine.url)
        discovery = NewsDiscovery(database_url=database_url)

        # Create source row
        source_row = pd.Series(
            {
                "id": source_id,
                "url": "https://example-regression.com",
                "name": "Example Regression Test",
                "host": "example-regression.com",
                "metadata": '{"frequency": "daily"}',  # This is the serialized JSON string
            }
        )

        # Mock discovery methods to return nothing
        processor = SourceProcessor(
            discovery=discovery,
            source_row=source_row,
            dataset_label=None,
            operation_id="test-op",
        )

        # Mock the discovery methods to return empty results
        with patch.object(processor, "_try_rss", return_value=([], {}, False, False)):
            with patch.object(processor, "_try_newspaper", return_value=[]):
                with patch.object(processor, "_try_storysniffer", return_value=[]):
                    # Process should find nothing
                    result = processor.process()

        # Verify result shows no articles
        assert result.articles_found == 0

        # Refresh the source to see the updated metadata
        session.expire_all()
        source = session.query(Source).filter_by(id=source_id).first()

        assert source is not None
        print("\n=== After first discovery ===")
        print(f"Source ID: {source_id}")
        print(f"Metadata type: {type(source.meta)}")
        print(f"Metadata: {source.meta}")
        assert source.meta is not None

        # This should be set but isn't in production
        counter = source.meta.get("no_effective_methods_consecutive")
        print(f"Counter value: {counter}")
        assert counter is not None, "Counter should be set when no articles found"
        assert counter == 1, f"Counter should be 1, got {counter}"

        # Run again to verify it increments
        processor2 = SourceProcessor(
            discovery=discovery,
            source_row=source_row,
            dataset_label=None,
            operation_id="test-op-2",
        )

        with patch.object(processor2, "_try_rss", return_value=([], {}, False, False)):
            with patch.object(processor2, "_try_newspaper", return_value=[]):
                with patch.object(processor2, "_try_storysniffer", return_value=[]):
                    processor2.process()

        session.expire_all()
        source = session.query(Source).filter_by(id=source_id).first()
        assert source is not None
        counter = source.meta.get("no_effective_methods_consecutive")
        assert counter == 2, f"Counter should increment to 2, got {counter}"

    finally:
        # Clean up: delete the test source
        try:
            from src.models import Source as SourceCleanup

            session.query(SourceCleanup).filter_by(id=source_id).delete()
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()


@pytest.mark.integration
@pytest.mark.postgres
def test_failure_counter_not_set_when_articles_exist(cloud_sql_session):
    """Test that counter is NOT incremented if source has historical articles."""
    from src.models import Article, CandidateLink, Source

    # Create source with one extracted article
    source = Source(
        host="hasnews.com",
        host_norm="hasnews.com",
        canonical_name="Has News",
        metadata={"frequency": "daily"},
    )
    cloud_sql_session.add(source)
    cloud_sql_session.flush()

    candidate = CandidateLink(
        url="https://hasnews.com/article1",
        source="Has News",
        source_id=source.id,
        source_host_id=source.id,
        status="extracted",
    )
    cloud_sql_session.add(candidate)
    cloud_sql_session.flush()

    article = Article(
        candidate_link_id=candidate.id,
        url="https://hasnews.com/article1",
        title="Test Article",
        status="extracted",
        text="Some content",
    )
    cloud_sql_session.add(article)
    cloud_sql_session.commit()
    source_id = source.id

    # Get database URL from the session's engine
    engine = cloud_sql_session.get_bind().engine
    database_url = str(engine.url)
    discovery = NewsDiscovery(database_url=database_url)

    source_row = pd.Series(
        {
            "id": source_id,
            "url": "https://hasnews.com",
            "name": "Has News",
            "host": "hasnews.com",
            "metadata": '{"frequency": "daily"}',
        }
    )

    processor = SourceProcessor(
        discovery=discovery,
        source_row=source_row,
        dataset_label=None,
        operation_id="test-op",
    )

    # Mock discovery to return nothing
    with patch.object(processor, "_try_rss", return_value=([], {}, False, False)):
        with patch.object(processor, "_try_newspaper", return_value=[]):
            processor.process()

    # Counter should NOT be set because source has historical articles
    cloud_sql_session.expire_all()
    source = cloud_sql_session.query(Source).filter_by(id=source_id).first()
    counter = source.metadata.get("no_effective_methods_consecutive")

    assert (
        counter is None or counter == 0
    ), f"Counter should not be set for sources with articles, got {counter}"
