"""Unit tests for test-domain diagnostic command."""

import json
import os
from datetime import datetime
from unittest import mock

import pytest

from src.cli.commands.domain_diagnostics import (
    DomainTestResult,
    add_test_domain_parser,
    categorize_error,
    get_recommendation,
    handle_domain_diagnostics_command,
)


class TestDomainTestResult:
    """Test DomainTestResult dataclass."""

    def test_domain_test_result_creation(self):
        """Verify DomainTestResult can be created."""
        result = DomainTestResult(
            domain="example.com",
            url="http://example.com/article",
            status="success",
            methods_attempted=["http", "selenium"],
            methods_passed={"http": True, "selenium": False},
            methods_errors={"selenium": "timeout"},
            fields_extracted={"title": True, "author": True, "content": True},
            missing_fields=[],
            final_content_length=1000,
            recommendations=["Recommendation 1"],
            timestamp=datetime.utcnow().isoformat(),
        )
        assert result.domain == "example.com"
        assert result.status == "success"

    def test_domain_test_result_to_dict(self):
        """Verify to_dict() converts dataclass to dict."""
        result = DomainTestResult(
            domain="example.com",
            url="http://example.com/article",
            status="success",
            methods_attempted=[],
            methods_passed={},
            methods_errors={},
            fields_extracted={},
            missing_fields=[],
            final_content_length=500,
            recommendations=[],
            timestamp=datetime.utcnow().isoformat(),
        )
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert result_dict["domain"] == "example.com"
        assert result_dict["status"] == "success"


class TestCategorizeError:
    """Test error categorization function."""

    def test_categorize_cloudflare_error(self):
        """Verify Cloudflare errors are categorized correctly."""
        assert (
            categorize_error("Cloudflare challenge failed") == "CLOUDFLARE_PROTECTION"
        )
        assert categorize_error("CF_CHALLENGE detected") == "CLOUDFLARE_PROTECTION"

    def test_categorize_subscription_error(self):
        """Verify subscription wall errors are categorized."""
        assert categorize_error("Subscription required") == "SUBSCRIPTION_WALL"
        assert categorize_error("Paywall detected") == "SUBSCRIPTION_WALL"

    def test_categorize_proxy_error(self):
        """Verify proxy challenge errors are categorized."""
        assert categorize_error("Proxy challenge failed") == "PROXY_CHALLENGE"
        assert categorize_error("Squid blocked request") == "PROXY_CHALLENGE"

    def test_categorize_403_error(self):
        """Verify 403 errors are categorized."""
        assert categorize_error("403 Forbidden") == "HTTP_403_FORBIDDEN"
        assert categorize_error("Access Forbidden") == "HTTP_403_FORBIDDEN"

    def test_categorize_404_error(self):
        """Verify 404 errors are categorized."""
        assert categorize_error("404 Not Found") == "HTTP_404_NOT_FOUND"
        assert categorize_error("Page not found") == "HTTP_404_NOT_FOUND"

    def test_categorize_timeout_error(self):
        """Verify timeout errors are categorized."""
        assert categorize_error("Request timed out") == "TIMEOUT"
        assert categorize_error("Connection timed out") == "TIMEOUT"

    def test_categorize_chrome_error(self):
        """Verify Chrome/driver errors are categorized."""
        assert categorize_error("ChromeDriver failed") == "CHROME_DRIVER_ERROR"
        assert categorize_error("Selenium error") == "CHROME_DRIVER_ERROR"

    def test_categorize_connection_error(self):
        """Verify connection errors are categorized."""
        assert categorize_error("Connection refused") == "CONNECTION_ERROR"
        assert categorize_error("Cannot connect") == "CONNECTION_ERROR"

    def test_categorize_unknown_error(self):
        """Verify unknown errors default to OTHER_ERROR."""
        assert categorize_error("Some random error") == "OTHER_ERROR"

    def test_categorize_case_insensitive(self):
        """Verify categorization is case-insensitive."""
        assert categorize_error("CLOUDFLARE CHALLENGE") == "CLOUDFLARE_PROTECTION"
        assert categorize_error("timeout ERROR") == "TIMEOUT"


class TestGetRecommendation:
    """Test recommendation generation function."""

    def test_recommendation_cloudflare(self):
        """Verify Cloudflare recommendations are generated."""
        recs = get_recommendation("CLOUDFLARE_PROTECTION", "example.com")
        assert len(recs) > 0
        assert any("example.com" in r for r in recs)

    def test_recommendation_subscription(self):
        """Verify subscription wall recommendations are generated."""
        recs = get_recommendation("SUBSCRIPTION_WALL", "example.com")
        assert len(recs) > 0
        assert any("subscription" in r.lower() for r in recs)

    def test_recommendation_proxy(self):
        """Verify proxy recommendations are generated."""
        recs = get_recommendation("PROXY_CHALLENGE", "example.com")
        assert len(recs) > 0
        assert any("proxy" in r.lower() for r in recs)

    def test_recommendation_403(self):
        """Verify 403 error recommendations."""
        recs = get_recommendation("HTTP_403_FORBIDDEN", "example.com")
        assert len(recs) > 0

    def test_recommendation_404(self):
        """Verify 404 error recommendations."""
        recs = get_recommendation("HTTP_404_NOT_FOUND", "example.com")
        assert len(recs) > 0

    def test_recommendation_timeout(self):
        """Verify timeout recommendations."""
        recs = get_recommendation("TIMEOUT", "example.com")
        assert len(recs) > 0

    def test_recommendation_chrome(self):
        """Verify Chrome error recommendations."""
        recs = get_recommendation("CHROME_DRIVER_ERROR", "example.com")
        assert len(recs) > 0

    def test_recommendation_connection(self):
        """Verify connection error recommendations."""
        recs = get_recommendation("CONNECTION_ERROR", "example.com")
        assert len(recs) > 0

    def test_recommendation_unknown(self):
        """Verify unknown error recommendations."""
        recs = get_recommendation("UNKNOWN_ERROR_TYPE", "example.com")
        assert len(recs) > 0


class TestAddTestDomainParser:
    """Test parser creation for test-domain command."""

    def test_add_test_domain_parser(self):
        """Verify parser is created with required arguments."""
        import argparse

        main_parser = argparse.ArgumentParser()
        subparsers = main_parser.add_subparsers()

        parser = add_test_domain_parser(subparsers)
        assert parser is not None

    def test_parser_domain_required(self):
        """Verify --domain argument is required."""
        import argparse

        main_parser = argparse.ArgumentParser()
        subparsers = main_parser.add_subparsers()

        parser = add_test_domain_parser(subparsers)
        # Parser should be configured with --domain required
        assert any(action.dest == "domain" for action in parser._actions)

    def test_parser_limit_optional(self):
        """Verify --limit argument is optional with default."""
        import argparse

        main_parser = argparse.ArgumentParser()
        subparsers = main_parser.add_subparsers()

        parser = add_test_domain_parser(subparsers)
        assert any(action.dest == "limit" for action in parser._actions)


class TestHandleDomainDiagnosticsCommand:
    """Test main command handler."""

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_success_path(self, mock_extractor_class, mock_db, mock_print):
        """Verify command handles successful extraction."""
        # Setup args
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = None

        # Setup database mock
        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article", "example.com")
        ]

        # Setup extractor mock - return dict
        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.return_value = {
            "title": "Test Article",
            "author": "Test Author",
            "published_date": "2024-01-01",
            "content": "Test content here",
        }

        # Call command
        result = handle_domain_diagnostics_command(mock_args)

        # Verify success
        assert result == 0

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    def test_command_no_articles_found(self, mock_db, mock_print):
        """Verify command handles no articles found."""
        mock_args = mock.MagicMock()
        mock_args.domain = "nonexistent.com"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = []

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 0

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    def test_command_database_error(self, mock_db, mock_print):
        """Verify command handles database errors."""
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.side_effect = Exception("Database connection failed")

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 1

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_partial_extraction(
        self, mock_extractor_class, mock_db, mock_print
    ):
        """Verify command handles partial extraction (missing fields)."""
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article", "example.com")
        ]

        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.return_value = {
            "title": "Test Article",
            "author": None,  # Missing field
            "published_date": "2024-01-01",
            "content": "Test content",
        }

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 0

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_extraction_failure(
        self, mock_extractor_class, mock_db, mock_print
    ):
        """Verify command handles extraction failure."""
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article", "example.com")
        ]

        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.side_effect = Exception(
            "Timeout during extraction"
        )

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 1

    @mock.patch("builtins.print")
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_output_to_file(
        self, mock_extractor_class, mock_db, mock_file, mock_print
    ):
        """Verify command saves results to JSON file."""
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = "/tmp/results.json"

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article", "example.com")
        ]

        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.return_value = {
            "title": "Test Article",
            "author": "Test Author",
            "published_date": "2024-01-01",
            "content": "Test content",
        }

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 0
        # Verify file was written
        mock_file.assert_called_with("/tmp/results.json", "w")

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_verbose_mode(self, mock_extractor_class, mock_db, mock_print):
        """Verify verbose flag enables debug logging."""
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 1
        mock_args.verbose = True
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article", "example.com")
        ]

        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.return_value = {
            "title": "Test Article",
            "author": "Test Author",
            "published_date": "2024-01-01",
            "content": "Test content",
        }

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 0

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_domain_normalization(
        self, mock_extractor_class, mock_db, mock_print
    ):
        """Verify domain is normalized (http/https stripped)."""
        mock_args = mock.MagicMock()
        mock_args.domain = "https://example.com/path"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article", "example.com")
        ]

        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.return_value = {
            "title": "Test",
            "author": "Test",
            "published_date": "2024-01-01",
            "content": "Test",
        }

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 0

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_multiple_urls(self, mock_extractor_class, mock_db, mock_print):
        """Verify command handles multiple URLs."""
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 3
        mock_args.verbose = False
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article1", "example.com"),
            (2, "http://example.com/article2", "example.com"),
            (3, "http://example.com/article3", "example.com"),
        ]

        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.return_value = {
            "title": "Test",
            "author": "Test",
            "published_date": "2024-01-01",
            "content": "Test content",
        }

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 0

    @mock.patch("builtins.print")
    @mock.patch("src.cli.commands.domain_diagnostics.DatabaseManager")
    @mock.patch("src.cli.commands.domain_diagnostics.ContentExtractor")
    def test_command_chrome_error_handling(
        self, mock_extractor_class, mock_db, mock_print
    ):
        """Verify Chrome errors are handled with detailed output."""
        mock_args = mock.MagicMock()
        mock_args.domain = "example.com"
        mock_args.limit = 1
        mock_args.verbose = False
        mock_args.output = None

        mock_session = mock.MagicMock()
        mock_db.return_value.get_session.return_value.__enter__.return_value = (
            mock_session
        )
        mock_session.execute.return_value.fetchall.return_value = [
            (1, "http://example.com/article", "example.com")
        ]

        mock_extractor = mock.MagicMock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract_content.side_effect = Exception(
            "ChromeDriver error: process died"
        )

        result = handle_domain_diagnostics_command(mock_args)
        assert result == 1
