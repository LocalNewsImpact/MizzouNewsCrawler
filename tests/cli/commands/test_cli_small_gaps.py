"""Tests to close small coverage gaps in CLI commands.

Targets modules at 89-92% coverage with <20 uncovered lines.
"""

import argparse
import json
import sys
from io import StringIO
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from src.cli.commands import cleanup_candidates, discovery_report, gazetteer, list_sources


class TestCleanupCandidates:
    """Test cleanup_candidates exception handling."""

    def test_main_handles_exceptions_gracefully(self):
        """Should catch and log exceptions in main function."""
        # Mock database to raise exception
        with patch("src.cli.commands.cleanup_candidates.DatabaseManager") as mock_db:
            mock_db.side_effect = Exception("Database connection failed")

            # Capture stdout
            captured_output = StringIO()
            with patch('sys.stdout', captured_output):
                result = cleanup_candidates.handle_cleanup_candidates_command(Mock())

            assert result == 1
            assert "Error:" in captured_output.getvalue()


class TestDiscoveryReport:
    """Test discovery_report CLI parsing and error handling."""

    def test_add_parser_registers_all_arguments(self):
        """Should register all discovery-report arguments."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        discovery_report.add_discovery_report_parser(subparsers)

        # Parse with all args
        args = parser.parse_args([
            "discovery-report",
            "--operation-id", "test-op-123",
            "--hours-back", "48",
            "--format", "json"
        ])

        assert args.operation_id == "test-op-123"
        assert args.hours_back == 48
        assert args.format == "json"

    def test_add_parser_sets_defaults(self):
        """Should set default values for optional arguments."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        discovery_report.add_discovery_report_parser(subparsers)

        # Parse with no args
        args = parser.parse_args(["discovery-report"])

        assert args.hours_back == 24
        assert args.format == "summary"

    def test_print_detailed_report_handles_missing_top_sources(self):
        """Should handle report with no top_performing_sources."""
        report = {
            "summary": {
                "total_sources": 10,
                "technical_success_count": 8,
                "content_success_count": 6,
                "technical_failure_count": 2,
                "total_articles_found": 100,
                "total_duplicate_articles": 20,
                "total_expired_articles": 5,
            },
            "outcome_breakdown": [],
            "top_performing_sources": []  # Empty list
        }

        # Should not raise exception
        captured_output = StringIO()
        with patch('sys.stdout', captured_output):
            discovery_report._print_detailed_discovery_report(report)

        output = captured_output.getvalue()
        assert "Detailed Statistics" in output
        assert "Technical successes: 8" in output


class TestListSources:
    """Test list_sources CLI parsing."""

    def test_add_parser_registers_all_arguments(self):
        """Should register all list-sources arguments."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        list_sources.add_list_sources_parser(subparsers)

        # Parse with all args
        args = parser.parse_args([
            "list-sources",
            "--dataset", "mizzou",
            "--format", "csv"
        ])

        assert args.dataset == "mizzou"
        assert args.format == "csv"

    def test_add_parser_sets_default_format(self):
        """Should default to table format."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        list_sources.add_list_sources_parser(subparsers)

        args = parser.parse_args(["list-sources"])

        assert args.format == "table"

    def test_format_table_handles_empty_dataframe(self):
        """Should handle empty DataFrame gracefully."""
        empty_df = pd.DataFrame(columns=["uuid", "name", "city"])

        captured_output = StringIO()
        with patch('sys.stdout', captured_output):
            list_sources._format_table(empty_df)

        output = captured_output.getvalue()
        assert "Found 0 sources" in output


class TestGazetteer:
    """Test gazetteer CLI parsing and error handling."""

    def test_add_parser_registers_all_arguments(self):
        """Should register all populate-gazetteer arguments."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        gazetteer.add_gazetteer_parser(subparsers)

        # Parse with all args
        args = parser.parse_args([
            "populate-gazetteer",
            "--dataset", "mizzou",
            "--address", "123 Main St, Columbia, MO",
            "--radius", "25.5",
            "--publisher", "pub-uuid-123",
            "--dry-run"
        ])

        assert args.dataset == "mizzou"
        assert args.address == "123 Main St, Columbia, MO"
        assert args.radius == 25.5
        assert args.publisher == "pub-uuid-123"
        assert args.dry_run is True

    def test_handle_command_returns_error_when_script_unavailable(self):
        """Should return 1 when run_gazetteer_population is None."""
        # Mock the import to simulate unavailable script
        with patch("src.cli.commands.gazetteer.run_gazetteer_population", None):
            captured_output = StringIO()
            with patch('sys.stdout', captured_output):
                result = gazetteer.handle_gazetteer_command(Mock())

            assert result == 1
            assert "not available" in captured_output.getvalue()


class TypeLLMCommand:
    """Test LLM command parsing."""

    def test_add_parser_registers_llm_analyze_command(self):
        """Should register llm-analyze command with all arguments."""
        from src.cli.commands import llm

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        llm.add_llm_parser(subparsers)

        # Parse with args - just verify it doesn't raise
        args = parser.parse_args([
            "llm-analyze",
            "--limit", "50",
            "--batch-size", "10"
        ])

        assert hasattr(args, 'func')
