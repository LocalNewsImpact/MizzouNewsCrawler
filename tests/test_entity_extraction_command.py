"""
Tests for the entity extraction CLI command.

Tests the extract-entities command that processes articles with content
but no entity data, extracting location entities and storing them in
the article_entities table.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.cli.commands.entity_extraction import (
    handle_entity_extraction_command,
)


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager for testing."""
    with patch("src.cli.commands.entity_extraction.DatabaseManager") as mock:
        yield mock


@pytest.fixture
def mock_entity_extractor():
    """Mock ArticleEntityExtractor for testing."""
    with patch("src.cli.commands.entity_extraction.ArticleEntityExtractor") as mock:
        extractor = MagicMock()
        extractor.extractor_version = "test-v1"
        extractor.extract.return_value = [
            {
                "text": "Springfield",
                "label": "GPE",
                "start": 0,
                "end": 11,
            }
        ]
        mock.return_value = extractor
        yield mock


@pytest.fixture
def mock_gazetteer():
    """Mock gazetteer functions."""
    with (
        patch("src.cli.commands.entity_extraction.get_gazetteer_rows") as get_rows,
        patch("src.cli.commands.entity_extraction.attach_gazetteer_matches") as attach,
    ):
        get_rows.return_value = []
        attach.return_value = [
            {
                "text": "Springfield",
                "label": "GPE",
                "start": 0,
                "end": 11,
                "gazetteer_match": True,
            }
        ]
        yield get_rows, attach


@pytest.fixture
def mock_save_entities():
    """Mock save_article_entities function."""
    with patch("src.cli.commands.entity_extraction.save_article_entities") as mock:
        yield mock


class TestEntityExtractionCommand:
    """Test suite for entity extraction command."""

    def test_no_articles_needing_extraction(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test when no articles need entity extraction."""
        # Setup mock session
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        # Create args
        args = MagicMock()
        args.limit = 100
        args.source = None

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify
        assert result == 0
        mock_session.execute.assert_called_once()
        mock_save_entities.assert_not_called()

    def test_successful_entity_extraction(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test successful entity extraction for articles."""
        # Setup mock session with articles
        article_id = str(uuid.uuid4())
        source_id = str(uuid.uuid4())
        dataset_id = str(uuid.uuid4())

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            (
                article_id,
                "Test article about Springfield.",
                "hash123",
                source_id,
                dataset_id,
            )
        ]
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        get_rows_mock, attach_mock = mock_gazetteer

        # Create args
        args = MagicMock()
        args.limit = 100
        args.source = None

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify
        assert result == 0
        mock_session.execute.assert_called_once()

        # Verify entity extraction pipeline was called
        extractor = mock_entity_extractor.return_value
        extractor.extract.assert_called_once()
        get_rows_mock.assert_called_once()
        attach_mock.assert_called_once()
        mock_save_entities.assert_called_once()

        # Verify save_article_entities received correct data
        save_call_args = mock_save_entities.call_args
        assert save_call_args[0][1] == article_id  # article_id
        assert save_call_args[0][3] == "test-v1"  # extractor_version

    def test_multiple_articles_extraction(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test entity extraction for multiple articles."""
        # Setup mock session with multiple articles
        articles = [
            (
                str(uuid.uuid4()),
                f"Article {i} text",
                f"hash{i}",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )
            for i in range(3)
        ]

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = articles
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        # Create args
        args = MagicMock()
        args.limit = 100
        args.source = None

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify
        assert result == 0
        assert mock_save_entities.call_count == 3

    def test_entity_extraction_with_source_filter(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test entity extraction with source filter."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        # Create args with source filter
        args = MagicMock()
        args.limit = 100
        args.source = "test-source"

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify
        assert result == 0
        # Check that query includes source filter
        execute_call = mock_session.execute.call_args
        query_str = str(execute_call[0][0])
        assert "source" in query_str.lower()

    def test_entity_extraction_with_limit(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test entity extraction respects limit parameter."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        # Create args with custom limit
        args = MagicMock()
        args.limit = 50
        args.source = None

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify
        assert result == 0
        execute_call = mock_session.execute.call_args
        params = execute_call[0][1]
        assert params["limit"] == 50

    def test_entity_extraction_error_handling(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test entity extraction handles errors gracefully."""
        # Setup mock session
        article_id = str(uuid.uuid4())
        source_id = str(uuid.uuid4())
        dataset_id = str(uuid.uuid4())

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            (article_id, "Test article", "hash123", source_id, dataset_id)
        ]
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        # Make entity extraction fail
        extractor = mock_entity_extractor.return_value
        extractor.extract.side_effect = Exception("Entity extraction failed")

        # Create args
        args = MagicMock()
        args.limit = 100
        args.source = None

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify command returns error code
        assert result == 1
        mock_session.rollback.assert_called()
        mock_save_entities.assert_not_called()

    def test_entity_extraction_commits_in_batches(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test entity extraction commits after every 10 articles."""
        # Setup mock session with 25 articles
        # Should commit 3 times: at 10, 20, and final
        articles = [
            (
                str(uuid.uuid4()),
                f"Article {i}",
                f"hash{i}",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )
            for i in range(25)
        ]

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = articles
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        # Create args
        args = MagicMock()
        args.limit = 100
        args.source = None

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify
        assert result == 0
        # Should commit 3 times: after 10, after 20, and final commit
        assert mock_session.commit.call_count == 3

    def test_entity_extraction_partial_failure(
        self, mock_db_manager, mock_entity_extractor, mock_gazetteer, mock_save_entities
    ):
        """Test entity extraction continues after individual article failure."""
        # Setup mock session with 3 articles
        articles = [
            (
                str(uuid.uuid4()),
                f"Article {i}",
                f"hash{i}",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )
            for i in range(3)
        ]

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = articles
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        # Make second article fail
        extractor = mock_entity_extractor.return_value
        extractor.extract.side_effect = [
            [{"text": "Location", "label": "GPE"}],  # Success
            Exception("Failed"),  # Fail
            [{"text": "Location", "label": "GPE"}],  # Success
        ]

        # Create args
        args = MagicMock()
        args.limit = 100
        args.source = None

        # Execute command
        result = handle_entity_extraction_command(args)

        # Verify: should have 1 error but return error code
        assert result == 1
        # Should save entities for 2 successful articles
        assert mock_save_entities.call_count == 2

    def test_entity_extraction_query_structure(
        self, mock_db_manager, mock_entity_extractor
    ):
        """Test that the query correctly filters articles needing entity extraction."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_db_manager.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )

        args = MagicMock()
        args.limit = 100
        args.source = None

        handle_entity_extraction_command(args)

        # Verify query structure
        execute_call = mock_session.execute.call_args
        query_str = str(execute_call[0][0]).lower()

        # Should select required fields
        assert "a.id" in query_str
        assert "a.text" in query_str
        # source_id comes from candidate_links join
        assert "cl.source_id" in query_str or "source_id" in query_str

        # Should filter for articles with content but no entities
        assert "content is not null" in query_str
        assert "text is not null" in query_str
        assert "not exists" in query_str
        assert "article_entities" in query_str

        # Should exclude error articles
        assert "status" in query_str
        assert "error" in query_str
