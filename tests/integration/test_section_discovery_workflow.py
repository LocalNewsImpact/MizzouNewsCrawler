"""Integration tests for section discovery workflow.

These tests verify that section discovery is actually integrated into
the production workflow and results are stored correctly.

This addresses the gap identified in PR #188: unit tests proved the
algorithms work in isolation, but didn't test the production integration.
"""

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import text

from src.models.database import DatabaseManager


@pytest.mark.integration
def test_discover_and_store_sections_method_exists():
    """Test that _discover_and_store_sections method exists in SourceProcessor.

    This is a smoke test to ensure the integration method we added actually
    exists in the production code.
    """
    from src.crawler.source_processing import SourceProcessor

    assert hasattr(
        SourceProcessor, "_discover_and_store_sections"
    ), "_discover_and_store_sections method should exist in SourceProcessor"


@pytest.mark.integration
def test_section_discovery_integration_with_mocked_discovery():
    """Test that section discovery runs and stores results.

    This test mocks the minimum required to verify the integration:
    1. Section discovery is called during processing
    2. Both strategies are invoked
    3. Results are stored in the database
    """
    import os

    database_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    db = DatabaseManager(database_url)

    # Create tables
    from src.models import Base

    Base.metadata.create_all(db.engine)

    # Create test source with section discovery enabled
    source_id = f"test-source-{uuid.uuid4()}"
    with db.engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sources
                (id, name, host, canonical_name, status, section_discovery_enabled)
                VALUES (:id, :name, :host, :canonical_name, :status, :enabled)
                """
            ),
            {
                "id": source_id,
                "name": "Test Source",
                "host": "test-source.com",
                "canonical_name": "Test Source",
                "status": "active",
                "enabled": True,
            },
        )
        conn.commit()

    try:
        # Import after DB setup
        from src.crawler.source_processing import SourceProcessor

        # Create a minimal mock discovery object
        mock_discovery = MagicMock()
        mock_discovery.database_url = database_url
        mock_discovery.session = MagicMock()
        mock_discovery.timeout = 30

        # Mock homepage response for Strategy 1
        mock_response = MagicMock()
        mock_response.text = """
            <nav>
                <a href="/news">News</a>
                <a href="/sports">Sports</a>
            </nav>
        """
        mock_response.status_code = 200
        mock_discovery.session.get.return_value = mock_response

        # Import real discovery methods so they actually run
        from src.crawler.discovery import NewsDiscovery

        mock_discovery._discover_section_urls = NewsDiscovery._discover_section_urls
        mock_discovery._extract_sections_from_article_urls = (
            NewsDiscovery._extract_sections_from_article_urls
        )

        # Create source_row as a pandas Series
        source_row = pd.Series(
            {
                "id": source_id,
                "name": "Test Source",
                "host": "test-source.com",
                "homepage_url": "https://test-source.com",
                "canonical_name": "Test Source",
                "status": "active",
                "section_discovery_enabled": True,
            }
        )

        # Create processor
        processor = SourceProcessor(
            discovery=mock_discovery,
            source_row=source_row,
        )

        # Mock _run_discovery_methods to return test articles
        with patch.object(processor, "_run_discovery_methods", return_value=[]):
            # Mock _store_candidates to prevent actual storage
            with patch.object(processor, "_store_candidates"):
                # Call the section discovery method directly
                processor._discover_and_store_sections(
                    [
                        {
                            "url": "https://test-source.com/news/article-1",
                            "discovered_at": datetime.utcnow().isoformat(),
                        },
                        {
                            "url": "https://test-source.com/sports/article-2",
                            "discovered_at": datetime.utcnow().isoformat(),
                        },
                    ]
                )

        # Verify sections were stored
        with db.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT discovered_sections, section_last_updated
                    FROM sources
                    WHERE id = :id
                    """
                ),
                {"id": source_id},
            ).fetchone()

            assert result is not None
            discovered_sections = result[0]
            section_last_updated = result[1]

            assert (
                discovered_sections is not None
            ), "discovered_sections should be populated"
            assert (
                section_last_updated is not None
            ), "section_last_updated should be set"

            # Parse JSON
            if isinstance(discovered_sections, str):
                sections_data = json.loads(discovered_sections)
            else:
                sections_data = discovered_sections

            # Verify structure
            assert "urls" in sections_data
            assert "discovered_at" in sections_data
            assert "discovery_method" in sections_data
            assert "count" in sections_data

            # Verify discovery method
            assert sections_data["discovery_method"] == "adaptive_combined"

            # Verify we got sections
            section_urls = sections_data["urls"]
            assert len(section_urls) > 0, "Should discover at least one section"

    finally:
        db.close()


@pytest.mark.integration
def test_section_discovery_respects_disabled_flag():
    """Test that section discovery is skipped when disabled."""
    import os

    database_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    db = DatabaseManager(database_url)

    # Create tables
    from src.models import Base

    Base.metadata.create_all(db.engine)

    # Create test source with section discovery DISABLED
    source_id = f"test-source-{uuid.uuid4()}"
    with db.engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sources
                (id, name, host, canonical_name, status, section_discovery_enabled)
                VALUES (:id, :name, :host, :canonical_name, :status, :enabled)
                """
            ),
            {
                "id": source_id,
                "name": "Test Source",
                "host": "test-source.com",
                "canonical_name": "Test Source",
                "status": "active",
                "enabled": False,  # DISABLED
            },
        )
        conn.commit()

    try:
        from src.crawler.source_processing import SourceProcessor

        # Create minimal mock
        mock_discovery = MagicMock()
        mock_discovery.database_url = database_url
        mock_discovery.session = MagicMock()

        source_row = pd.Series(
            {
                "id": source_id,
                "name": "Test Source",
                "host": "test-source.com",
                "homepage_url": "https://test-source.com",
                "section_discovery_enabled": False,
            }
        )

        processor = SourceProcessor(
            discovery=mock_discovery,
            source_row=source_row,
        )

        # Call section discovery - should return early
        processor._discover_and_store_sections([])

        # Verify sections were NOT stored
        with db.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT discovered_sections
                    FROM sources
                    WHERE id = :id
                    """
                ),
                {"id": source_id},
            ).fetchone()

            assert result is not None, "Source should exist"
            assert result[0] is None, "discovered_sections should be NULL when disabled"

    finally:
        db.close()


@pytest.mark.integration
def test_process_method_calls_section_discovery():
    """Test that SourceProcessor.process() calls _discover_and_store_sections.

    This is the KEY integration test: verify the method is actually called
    in the production workflow, not just defined.
    """
    import os

    database_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    db = DatabaseManager(database_url)

    from src.models import Base

    Base.metadata.create_all(db.engine)

    source_id = f"test-source-{uuid.uuid4()}"
    with db.engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sources
                (id, name, host, canonical_name, status, section_discovery_enabled)
                VALUES (:id, :name, :host, :canonical_name, :status, :enabled)
                """
            ),
            {
                "id": source_id,
                "name": "Test Source",
                "host": "test-source.com",
                "canonical_name": "Test Source",
                "status": "active",
                "enabled": True,
            },
        )
        conn.commit()

    try:
        from src.crawler.source_processing import SourceProcessor

        mock_discovery = MagicMock()
        mock_discovery.database_url = database_url

        source_row = pd.Series(
            {
                "id": source_id,
                "name": "Test Source",
                "host": "test-source.com",
                "homepage_url": "https://test-source.com",
                "section_discovery_enabled": True,
            }
        )

        processor = SourceProcessor(
            discovery=mock_discovery,
            source_row=source_row,
        )

        # Patch both discovery methods and storage
        with patch.object(processor, "_run_discovery_methods", return_value=[]):
            with patch.object(processor, "_store_candidates"):
                with patch.object(
                    processor, "_discover_and_store_sections"
                ) as mock_section_discovery:
                    # Run process
                    processor.process()

                    # CRITICAL ASSERTION: Verify section discovery was called
                    assert (
                        mock_section_discovery.called
                    ), "_discover_and_store_sections should be called during process()"

    finally:
        db.close()
