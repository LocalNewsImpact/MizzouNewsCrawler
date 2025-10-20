"""Tests for orchestration/continuous_processor.py"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from orchestration import continuous_processor  # noqa: E402


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager for testing."""
    with patch("orchestration.continuous_processor.DatabaseManager") as mock_dm:
        mock_session = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=MagicMock(session=mock_session))
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_dm.return_value = mock_context
        yield mock_dm, mock_session


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.Popen for CLI command testing with streaming output."""
    with patch("orchestration.continuous_processor.subprocess.Popen") as mock_popen:
        # Mock process object with wait() method and stdout with readline
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0  # Default to success
        # Mock stdout with readline that returns empty string (end of stream)
        mock_stdout = MagicMock()
        mock_stdout.readline.return_value = ""
        mock_proc.stdout = mock_stdout
        mock_popen.return_value = mock_proc
        yield mock_popen


class TestWorkQueue:
    """Test the WorkQueue class."""

    def test_get_counts_returns_all_zeros_when_empty(self, mock_db_manager):
        """Test that get_counts returns zeros when database is empty."""
        mock_dm, mock_session = mock_db_manager

        # Mock all queries to return 0
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_result

        counts = continuous_processor.WorkQueue.get_counts()

        assert counts == {
            "verification_pending": 0,
            "extraction_pending": 0,
            "cleaning_pending": 0,
            "analysis_pending": 0,
            "entity_extraction_pending": 0,
        }
        # Only enabled steps query the database (cleaning, ML, entities by default)
        # Verification and extraction are disabled by default, so 3 queries expected
        assert mock_session.execute.call_count == 3

    def test_get_counts_returns_correct_values(self, mock_db_manager):
        """Test that get_counts returns correct counts from database."""
        mock_dm, mock_session = mock_db_manager

        # Mock different return values for each enabled query
        # By default: verification and extraction are DISABLED (return 0)
        # cleaning, ML analysis, and entity extraction are ENABLED (query DB)
        mock_results = [
            MagicMock(scalar=lambda: 12),  # cleaning_pending
            MagicMock(scalar=lambda: 15),  # analysis_pending
            MagicMock(scalar=lambda: 20),  # entity_extraction_pending
        ]
        mock_session.execute.side_effect = mock_results

        counts = continuous_processor.WorkQueue.get_counts()

        # Disabled steps should be 0 (not queried)
        assert counts["verification_pending"] == 0
        assert counts["extraction_pending"] == 0
        # Enabled steps should return database values
        assert counts["cleaning_pending"] == 12
        assert counts["analysis_pending"] == 15
        assert counts["entity_extraction_pending"] == 20

    def test_get_counts_queries_correct_tables(self, mock_db_manager):
        """Test that get_counts executes correct SQL queries."""
        mock_dm, mock_session = mock_db_manager

        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_result

        continuous_processor.WorkQueue.get_counts()

        # Verify correct number of queries (only enabled steps)
        # By default: cleaning, ML analysis, entity extraction = 3 queries
        assert mock_session.execute.call_count == 3

        # Verify queries are text objects (SQLAlchemy text)
        calls = mock_session.execute.call_args_list
        for call in calls:
            assert len(call[0]) == 1  # One positional argument
            # First argument should be a text() query


class TestRunCliCommand:
    """Test the run_cli_command function."""

    def test_run_cli_command_success(self, mock_subprocess):
        """Test successful CLI command execution."""
        # Configure the mock process object (already returned by fixture)
        mock_proc = mock_subprocess.return_value
        mock_proc.wait.return_value = 0
        # Mock stdout with readline method that returns empty after first call
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = ["Success\n", ""]
        mock_proc.stdout = mock_stdout

        result = continuous_processor.run_cli_command(
            ["test-command", "--arg", "value"], "Test command"
        )

        assert result is True
        mock_subprocess.assert_called_once()

        # Verify command structure
        call_args = mock_subprocess.call_args
        # Popen is called with command list as first arg
        assert "args" in call_args[1] or len(call_args[0]) > 0
        cmd = call_args[1].get("args") if "args" in call_args[1] else call_args[0][0]
        assert cmd[0] == sys.executable
        assert cmd[1] == "-m"
        assert cmd[2] == "src.cli.cli_modular"
        assert cmd[3:] == ["test-command", "--arg", "value"]

    def test_run_cli_command_failure(self, mock_subprocess):
        """Test CLI command execution failure."""
        # Configure the mock process object to return failure
        mock_proc = mock_subprocess.return_value
        mock_proc.wait.return_value = 1  # Failure exit code
        # Mock stdout with readline method
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = ["Error message\n", ""]
        mock_proc.stdout = mock_stdout

        result = continuous_processor.run_cli_command(
            ["failing-command"], "Failing command"
        )

        assert result is False

    def test_run_cli_command_timeout(self, mock_subprocess):
        """Test CLI command timeout handling."""
        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd="test", timeout=3600
        )

        result = continuous_processor.run_cli_command(["slow-command"], "Slow command")

        assert result is False

    def test_run_cli_command_exception(self, mock_subprocess):
        """Test CLI command exception handling."""
        mock_subprocess.side_effect = Exception("Unexpected error")

        result = continuous_processor.run_cli_command(
            ["broken-command"], "Broken command"
        )

        assert result is False


class TestProcessVerification:
    """Test the process_verification function."""

    def test_process_verification_returns_false_when_count_zero(self, mock_subprocess):
        """Test that verification is skipped when count is 0."""
        result = continuous_processor.process_verification(0)

        assert result is False
        mock_subprocess.assert_not_called()

    def test_process_verification_builds_correct_command(self, mock_subprocess):
        """Test that verification command is built correctly."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Test with default batch size (10)
        continuous_processor.process_verification(25)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        # Verify command structure
        assert "verify-urls" in cmd
        assert "--batch-size" in cmd
        assert "--max-batches" in cmd
        assert "--sleep-interval" in cmd
        assert "5" in cmd  # sleep interval value

    def test_process_verification_limits_batches_to_10(self, mock_subprocess):
        """Test that verification limits batches to max of 10."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # 500 items with batch size 10 = 50 batches needed, but should cap at 10
        continuous_processor.process_verification(500)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        max_batches_idx = cmd.index("--max-batches")
        max_batches_value = cmd[max_batches_idx + 1]

        assert max_batches_value == "10"


class TestProcessExtraction:
    """Test the process_extraction function."""

    def test_process_extraction_returns_false_when_count_zero(self, mock_subprocess):
        """Test that extraction is skipped when count is 0."""
        result = continuous_processor.process_extraction(0)

        assert result is False
        mock_subprocess.assert_not_called()

    def test_process_extraction_builds_correct_command(self, mock_subprocess):
        """Test that extraction command is built correctly."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        continuous_processor.process_extraction(50)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        # Verify command structure
        assert "extract" in cmd
        assert "--limit" in cmd
        assert "--batches" in cmd

    def test_process_extraction_limits_batches_to_5(self, mock_subprocess):
        """Test that extraction limits batches to max of 5."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # 500 items with batch size 20 = 25 batches needed, but should cap at 5
        continuous_processor.process_extraction(500)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        batches_idx = cmd.index("--batches")
        batches_value = cmd[batches_idx + 1]

        assert batches_value == "5"


class TestProcessAnalysis:
    """Test the process_analysis function."""

    def test_process_analysis_returns_false_when_count_zero(self, mock_subprocess):
        """Test that analysis is skipped when count is 0."""
        result = continuous_processor.process_analysis(0)

        assert result is False
        mock_subprocess.assert_not_called()

    def test_process_analysis_builds_correct_command(self, mock_subprocess):
        """Test that analysis command is built correctly."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        continuous_processor.process_analysis(50)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        # Verify command structure
        assert "analyze" in cmd
        assert "--limit" in cmd
        assert "--batch-size" in cmd
        assert "--top-k" in cmd
        assert "2" in cmd  # top-k value

    def test_process_analysis_limits_to_100_articles(self, mock_subprocess):
        """Test that analysis limits to max of 100 articles per cycle."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        continuous_processor.process_analysis(500)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        limit_idx = cmd.index("--limit")
        limit_value = cmd[limit_idx + 1]

        assert limit_value == "100"


class TestProcessEntityExtraction:
    """Test the process_entity_extraction function - now uses direct function call."""

    def test_process_entity_extraction_returns_false_when_count_zero(self):
        """Test that entity extraction is skipped when count is 0."""
        result = continuous_processor.process_entity_extraction(0)

        assert result is False

    @patch("src.cli.commands.entity_extraction.handle_entity_extraction_command")
    @patch("orchestration.continuous_processor.get_cached_entity_extractor")
    def test_process_entity_extraction_calls_function_directly(
        self, mock_get_extractor, mock_handle_command
    ):
        """Test that entity extraction now calls function directly instead of subprocess."""
        # Setup mocks
        mock_extractor = MagicMock()
        mock_get_extractor.return_value = mock_extractor
        mock_handle_command.return_value = 0  # Success

        result = continuous_processor.process_entity_extraction(50)

        # Verify it calls the cached extractor
        mock_get_extractor.assert_called_once()

        # Verify it calls the handler function with correct args
        mock_handle_command.assert_called_once()
        call_args = mock_handle_command.call_args

        # Check args namespace
        args = call_args[0][0]
        assert args.limit == 50
        assert args.source is None

        # Check extractor was passed
        assert call_args[1]["extractor"] is mock_extractor
        assert result is True

    @patch("src.cli.commands.entity_extraction.handle_entity_extraction_command")
    @patch("orchestration.continuous_processor.get_cached_entity_extractor")
    def test_process_entity_extraction_uses_batch_size(
        self, mock_get_extractor, mock_handle_command
    ):
        """Test that entity extraction limits to GAZETTEER_BATCH_SIZE."""
        mock_get_extractor.return_value = MagicMock()
        mock_handle_command.return_value = 0  # Success

        # Pass count larger than batch size
        result = continuous_processor.process_entity_extraction(1000)

        # Verify it was called with the batch size limit
        call_args = mock_handle_command.call_args
        args = call_args[0][0]

        # Should be capped at GAZETTEER_BATCH_SIZE (500)
        assert args.limit == min(1000, continuous_processor.GAZETTEER_BATCH_SIZE)
        assert args.limit == continuous_processor.GAZETTEER_BATCH_SIZE
        assert result is True


class TestProcessCycle:
    """Test the process_cycle function."""

    @patch("orchestration.continuous_processor.process_verification")
    @patch("orchestration.continuous_processor.process_extraction")
    @patch("orchestration.continuous_processor.process_cleaning")
    @patch("orchestration.continuous_processor.process_analysis")
    @patch("orchestration.continuous_processor.process_entity_extraction")
    @patch("orchestration.continuous_processor.WorkQueue.get_counts")
    def test_process_cycle_runs_all_steps_with_work(
        self,
        mock_get_counts,
        mock_entity,
        mock_analysis,
        mock_cleaning,
        mock_extraction,
        mock_verification,
    ):
        """Test that process_cycle runs enabled steps when there's work.

        By default, verification and extraction are disabled (not called).
        Cleaning, ML analysis, and entity extraction are enabled (called).
        """
        mock_get_counts.return_value = {
            "verification_pending": 10,
            "extraction_pending": 20,
            "cleaning_pending": 25,
            "analysis_pending": 30,
            "entity_extraction_pending": 40,
        }

        result = continuous_processor.process_cycle()

        # Verification and extraction should NOT be called (disabled by default)
        mock_verification.assert_not_called()
        mock_extraction.assert_not_called()

        # Cleaning, analysis, and entity extraction should be called (enabled by default)
        mock_cleaning.assert_called_once_with(25)
        mock_analysis.assert_called_once_with(30)
        mock_entity.assert_called_once_with(40)

        assert result is True

    @patch("orchestration.continuous_processor.process_verification")
    @patch("orchestration.continuous_processor.process_extraction")
    @patch("orchestration.continuous_processor.process_analysis")
    @patch("orchestration.continuous_processor.process_entity_extraction")
    @patch("orchestration.continuous_processor.WorkQueue.get_counts")
    def test_process_cycle_skips_steps_with_no_work(
        self,
        mock_get_counts,
        mock_entity,
        mock_analysis,
        mock_extraction,
        mock_verification,
    ):
        """Test that process_cycle skips process functions when no work."""
        mock_get_counts.return_value = {
            "verification_pending": 0,
            "extraction_pending": 0,
            "cleaning_pending": 0,
            "analysis_pending": 0,
            "entity_extraction_pending": 0,
        }

        # Make the process functions return False (behavior when count is 0)
        mock_verification.return_value = False
        mock_extraction.return_value = False
        mock_analysis.return_value = False
        mock_entity.return_value = False

        result = continuous_processor.process_cycle()

        # process_cycle() only calls process functions if count > 0
        # So with all counts at 0, none should be called
        mock_verification.assert_not_called()
        mock_extraction.assert_not_called()
        mock_analysis.assert_not_called()
        mock_entity.assert_not_called()

        assert result is False

    @patch("orchestration.continuous_processor.WorkQueue.get_counts")
    def test_process_cycle_handles_exceptions(self, mock_get_counts):
        """Test that process_cycle handles exceptions gracefully."""
        mock_get_counts.side_effect = Exception("Database error")

        # Should not raise, but should log the exception
        try:
            continuous_processor.process_cycle()
        except Exception:
            pytest.fail("process_cycle should catch and log exceptions, not raise")


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    def test_default_poll_interval(self):
        """Test default POLL_INTERVAL value."""
        # The module-level constant should be set
        assert hasattr(continuous_processor, "POLL_INTERVAL")
        assert isinstance(continuous_processor.POLL_INTERVAL, int)
        assert continuous_processor.POLL_INTERVAL == 60

    def test_default_idle_poll_interval(self):
        """Test default IDLE_POLL_INTERVAL value."""
        assert hasattr(continuous_processor, "IDLE_POLL_INTERVAL")
        assert isinstance(continuous_processor.IDLE_POLL_INTERVAL, int)
        assert continuous_processor.IDLE_POLL_INTERVAL == 300

    def test_default_batch_sizes(self):
        """Test default batch size values."""
        assert hasattr(continuous_processor, "VERIFICATION_BATCH_SIZE")
        assert hasattr(continuous_processor, "EXTRACTION_BATCH_SIZE")
        assert hasattr(continuous_processor, "ANALYSIS_BATCH_SIZE")
        assert hasattr(continuous_processor, "GAZETTEER_BATCH_SIZE")

        assert isinstance(continuous_processor.VERIFICATION_BATCH_SIZE, int)
        assert isinstance(continuous_processor.EXTRACTION_BATCH_SIZE, int)
        assert isinstance(continuous_processor.ANALYSIS_BATCH_SIZE, int)
        assert isinstance(continuous_processor.GAZETTEER_BATCH_SIZE, int)

    def test_cli_module_configured(self):
        """Test CLI_MODULE is set correctly."""
        assert continuous_processor.CLI_MODULE == "src.cli.cli_modular"

    def test_project_root_exists(self):
        """Test PROJECT_ROOT points to valid directory."""
        assert hasattr(continuous_processor, "PROJECT_ROOT")
        assert continuous_processor.PROJECT_ROOT.exists()
        assert continuous_processor.PROJECT_ROOT.is_dir()

    def test_feature_flags_exist(self):
        """Test that feature flag environment variables are defined."""
        assert hasattr(continuous_processor, "ENABLE_DISCOVERY")
        assert hasattr(continuous_processor, "ENABLE_VERIFICATION")
        assert hasattr(continuous_processor, "ENABLE_EXTRACTION")
        assert hasattr(continuous_processor, "ENABLE_CLEANING")
        assert hasattr(continuous_processor, "ENABLE_ML_ANALYSIS")
        assert hasattr(continuous_processor, "ENABLE_ENTITY_EXTRACTION")

        # All should be boolean values
        assert isinstance(continuous_processor.ENABLE_DISCOVERY, bool)
        assert isinstance(continuous_processor.ENABLE_VERIFICATION, bool)
        assert isinstance(continuous_processor.ENABLE_EXTRACTION, bool)
        assert isinstance(continuous_processor.ENABLE_CLEANING, bool)
        assert isinstance(continuous_processor.ENABLE_ML_ANALYSIS, bool)
        assert isinstance(continuous_processor.ENABLE_ENTITY_EXTRACTION, bool)

    def test_default_feature_flags(self):
        """Test default feature flag values (without env vars set)."""
        # Discovery, verification, and extraction should be disabled by default
        # (moved to dataset-specific jobs)
        assert continuous_processor.ENABLE_DISCOVERY is False
        assert continuous_processor.ENABLE_VERIFICATION is False
        assert continuous_processor.ENABLE_EXTRACTION is False

        # Cleaning, ML analysis, and entity extraction should be enabled by default
        # (remain in continuous processor)
        assert continuous_processor.ENABLE_CLEANING is True
        assert continuous_processor.ENABLE_ML_ANALYSIS is True
        assert continuous_processor.ENABLE_ENTITY_EXTRACTION is True


class TestCommandArgumentsRegression:
    """Regression tests for command argument bugs (placeholder for future tests)."""

    pass  # Removed outdated populate-gazetteer test - now uses extract-entities

    def test_extract_command_has_limit_argument(self, mock_subprocess):
        """
        Test that extract command DOES have --limit (it's valid for extract).

        This ensures we didn't accidentally break the correct commands.
        """
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        continuous_processor.process_extraction(50)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        # Extract SHOULD have --limit
        assert "--limit" in cmd, "extract command should have --limit argument"

    def test_analyze_command_has_limit_argument(self, mock_subprocess):
        """Test that analyze command DOES have --limit (it's valid for analyze)."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        continuous_processor.process_analysis(50)

        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]

        # Analyze SHOULD have --limit
        assert "--limit" in cmd, "analyze command should have --limit argument"


class TestFeatureFlagProcessing:
    """Test that feature flags control which pipeline steps are executed."""

    @patch("orchestration.continuous_processor.process_verification")
    @patch("orchestration.continuous_processor.process_extraction")
    @patch("orchestration.continuous_processor.process_cleaning")
    @patch("orchestration.continuous_processor.WorkQueue.get_counts")
    def test_disabled_steps_not_called(
        self,
        mock_get_counts,
        mock_cleaning,
        mock_extraction,
        mock_verification,
    ):
        """Test that disabled pipeline steps are not executed.

        By default, verification and extraction are disabled, so they
        should not be called even when work is available.
        """
        mock_get_counts.return_value = {
            "verification_pending": 10,
            "extraction_pending": 20,
            "cleaning_pending": 30,
            "analysis_pending": 0,
            "entity_extraction_pending": 0,
        }

        continuous_processor.process_cycle()

        # Verification and extraction should not be called (disabled by default)
        mock_verification.assert_not_called()
        mock_extraction.assert_not_called()

        # Cleaning should still be called (enabled by default)
        mock_cleaning.assert_called_once_with(30)

    def test_get_counts_skips_disabled_queries(self, mock_db_manager):
        """Test that get_counts skips queries for disabled steps."""
        # When verification and extraction are disabled (default),
        # their counts should remain 0 without querying the database
        mock_dm, mock_session = mock_db_manager

        mock_result = MagicMock()
        mock_result.scalar.return_value = 10
        mock_session.execute.return_value = mock_result

        counts = continuous_processor.WorkQueue.get_counts()

        # Verify that disabled steps return 0 (not queried)
        assert counts["verification_pending"] == 0
        assert counts["extraction_pending"] == 0

        # Enabled steps should still be counted (may be non-zero if work exists)
        assert "cleaning_pending" in counts
        assert "analysis_pending" in counts
        assert "entity_extraction_pending" in counts
