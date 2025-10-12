"""Tests for cleaning CLI command (src/cli/commands/cleaning.py)."""

import argparse
import logging
from unittest.mock import Mock, patch, MagicMock

from src.cli.commands import cleaning


class TestAddCleaningParser:
    """Tests for add_cleaning_parser function."""

    def test_adds_clean_articles_subcommand(self):
        """Test that clean-articles subcommand is added."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        result = cleaning.add_cleaning_parser(subparsers)

        assert result is not None
        # Verify the parser was created
        assert hasattr(result, "parse_args")

    def test_default_limit_is_50(self):
        """Test that default limit is 50."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        clean_parser = cleaning.add_cleaning_parser(subparsers)

        args = clean_parser.parse_args([])

        assert args.limit == 50

    def test_custom_limit_argument(self):
        """Test that custom limit can be specified."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        clean_parser = cleaning.add_cleaning_parser(subparsers)

        args = clean_parser.parse_args(["--limit", "100"])

        assert args.limit == 100

    def test_single_status_argument(self):
        """Test that single status can be specified."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        clean_parser = cleaning.add_cleaning_parser(subparsers)

        args = clean_parser.parse_args(["--status", "extracted"])

        assert args.status == ["extracted"]

    def test_multiple_status_arguments(self):
        """Test that multiple statuses can be specified."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        clean_parser = cleaning.add_cleaning_parser(subparsers)

        args = clean_parser.parse_args([
            "--status", "extracted",
            "--status", "wire",
        ])

        assert args.status == ["extracted", "wire"]

    def test_sets_handler_function(self):
        """Test that handler function is set as default."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        clean_parser = cleaning.add_cleaning_parser(subparsers)

        args = clean_parser.parse_args([])

        assert hasattr(args, "func")
        assert args.func == cleaning.handle_cleaning_command


class TestHandleCleaningCommand:
    """Tests for handle_cleaning_command function."""

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_no_articles_found(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test behavior when no articles need cleaning."""
        # Setup mocks
        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        args = argparse.Namespace(limit=50, status=None)

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No articles found" in captured.out

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_successful_cleaning_with_status_change(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test successful cleaning with status change."""
        # Setup article data
        articles = [
            (
                "article-id-1",
                "Original content with footer",
                "extracted",
                "https://example.com/article-1",
            ),
        ]

        # Setup mocks
        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        # Setup cleaner mock
        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.return_value = (
            "Cleaned content",
            {
                "wire_detected": False,
                "locality_assessment": None,
                "chars_removed": 20,
            },
        )
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Content cleaning completed" in captured.out
        assert "Articles processed: 1" in captured.out

        # Verify cleaner was called
        mock_cleaner_instance.process_single_article.assert_called_once_with(
            text="Original content with footer",
            domain="example.com",
            article_id="article-id-1",
        )

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_wire_detection_changes_status(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test that wire detection changes status to wire."""
        articles = [
            (
                "article-id-1",
                "Wire service content",
                "extracted",
                "https://example.com/wire-article",
            ),
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.return_value = (
            "Wire content cleaned",
            {
                "wire_detected": True,
                "locality_assessment": {"is_local": False},
                "chars_removed": 10,
            },
        )
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        captured = capsys.readouterr()
        # Verify wire status change happened
        assert "extracted→wire" in captured.out

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_local_wire_detection_changes_status_to_local(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test that local wire changes status to local."""
        articles = [
            (
                "article-id-1",
                "Local wire content",
                "extracted",
                "https://example.com/local-wire",
            ),
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.return_value = (
            "Local wire cleaned",
            {
                "wire_detected": True,
                "locality_assessment": {"is_local": True},
                "chars_removed": 15,
            },
        )
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        captured = capsys.readouterr()
        # Verify local status change happened
        assert "extracted→local" in captured.out

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_extracted_to_cleaned_status_change(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test extracted to cleaned status change."""
        articles = [
            (
                "article-id-1",
                "Normal article content",
                "extracted",
                "https://example.com/normal-article",
            ),
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.return_value = (
            "Cleaned article",
            {
                "wire_detected": False,
                "locality_assessment": None,
                "chars_removed": 25,
            },
        )
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        captured = capsys.readouterr()
        # Verify cleaned status change happened
        assert "extracted→cleaned" in captured.out

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_multiple_articles_from_same_domain(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test processing multiple articles from same domain."""
        articles = [
            ("id-1", "Content 1", "extracted", "https://example.com/a1"),
            ("id-2", "Content 2", "extracted", "https://example.com/a2"),
            ("id-3", "Content 3", "extracted", "https://example.com/a3"),
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.return_value = (
            "Cleaned",
            {"wire_detected": False, "chars_removed": 5},
        )
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        assert mock_cleaner_instance.process_single_article.call_count == 3
        captured = capsys.readouterr()
        assert "Articles processed: 3" in captured.out

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_multiple_articles_from_different_domains(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test processing articles from different domains."""
        articles = [
            ("id-1", "Content 1", "extracted", "https://site1.com/a1"),
            ("id-2", "Content 2", "extracted", "https://site2.com/a2"),
            ("id-3", "Content 3", "extracted", "https://site1.com/a3"),
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.return_value = (
            "Cleaned",
            {"wire_detected": False, "chars_removed": 5},
        )
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        # Should process all 3 articles
        assert mock_cleaner_instance.process_single_article.call_count == 3

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_handles_cleaning_error_gracefully(
        self, mock_db_manager, mock_cleaner, capsys, caplog
    ):
        """Test error handling during article cleaning."""
        articles = [
            ("id-1", "Content 1", "extracted", "https://example.com/a1"),
            ("id-2", "Content 2", "extracted", "https://example.com/a2"),
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        # First article fails, second succeeds
        mock_cleaner_instance.process_single_article.side_effect = [
            Exception("Cleaning error"),
            ("Cleaned", {"wire_detected": False, "chars_removed": 5}),
        ]
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        with caplog.at_level(logging.ERROR):
            result = cleaning.handle_cleaning_command(args)

        assert result == 0  # Should complete despite error
        captured = capsys.readouterr()
        assert "Errors: 1" in captured.out

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_uses_default_status_extracted(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test that default status is 'extracted' when not specified."""
        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        args = argparse.Namespace(limit=50, status=None)

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        # Verify query was called with 'extracted' status
        execute_call = mock_session.execute.call_args_list[0]
        params = execute_call[0][1]
        assert "status0" in params
        assert params["status0"] == "extracted"

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_respects_custom_limit(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test that custom limit is used in query."""
        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        args = argparse.Namespace(limit=100, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        execute_call = mock_session.execute.call_args_list[0]
        params = execute_call[0][1]
        assert params["limit"] == 100

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_database_error_returns_error_code(
        self, mock_db_manager, mock_cleaner, capsys, caplog
    ):
        """Test that database errors return error code."""
        mock_db = Mock()
        mock_db.get_session.side_effect = Exception("Database connection error")
        mock_db_manager.return_value = mock_db

        args = argparse.Namespace(limit=50, status=["extracted"])

        with caplog.at_level(logging.ERROR):
            result = cleaning.handle_cleaning_command(args)

        assert result == 1  # Error code

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_commits_every_10_articles(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test that session commits occur every 10 articles."""
        # Create 25 articles to test commit batching
        articles = [
            (f"id-{i}", f"Content {i}", "extracted", f"https://example.com/a{i}")
            for i in range(25)
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.return_value = (
            "Cleaned",
            {"wire_detected": False, "chars_removed": 5},
        )
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        # Should commit at 10, 20, and final
        assert mock_session.commit.call_count == 3

    @patch("src.cli.commands.cleaning.BalancedBoundaryContentCleaner")
    @patch("src.cli.commands.cleaning.DatabaseManager")
    def test_displays_status_change_summary(
        self, mock_db_manager, mock_cleaner, capsys
    ):
        """Test that status change summary is displayed."""
        articles = [
            ("id-1", "Content 1", "extracted", "https://example.com/a1"),
            ("id-2", "Wire content", "extracted", "https://example.com/a2"),
        ]

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.fetchall.return_value = articles
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        mock_db = Mock()
        mock_db.get_session.return_value = mock_session
        mock_db_manager.return_value = mock_db

        mock_cleaner_instance = Mock()
        mock_cleaner_instance.process_single_article.side_effect = [
            ("Cleaned 1", {"wire_detected": False, "chars_removed": 5}),
            ("Cleaned 2", {"wire_detected": True, "chars_removed": 10}),
        ]
        mock_cleaner.return_value = mock_cleaner_instance

        args = argparse.Namespace(limit=50, status=["extracted"])

        result = cleaning.handle_cleaning_command(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Status changes:" in captured.out
        assert "extracted→cleaned" in captured.out or "extracted→wire" in captured.out
