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
        assert mock_session.execute.call_count == 5

    def test_get_counts_returns_correct_values(self, mock_db_manager):
        """Test that get_counts returns correct counts from database."""
        mock_dm, mock_session = mock_db_manager
        
        # Mock different return values for each query
        mock_results = [
            MagicMock(scalar=lambda: 5),   # verification_pending
            MagicMock(scalar=lambda: 10),  # extraction_pending
            MagicMock(scalar=lambda: 12),  # cleaning_pending
            MagicMock(scalar=lambda: 15),  # analysis_pending
            MagicMock(scalar=lambda: 20),  # entity_extraction_pending
        ]
        mock_session.execute.side_effect = mock_results
        
        counts = continuous_processor.WorkQueue.get_counts()
        
        assert counts["verification_pending"] == 5
        assert counts["extraction_pending"] == 10
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
        
        # Verify correct number of queries
        assert mock_session.execute.call_count == 5
        
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
            ["test-command", "--arg", "value"],
            "Test command"
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
            ["failing-command"],
            "Failing command"
        )
        
        assert result is False

    def test_run_cli_command_timeout(self, mock_subprocess):
        """Test CLI command timeout handling."""
        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd="test",
            timeout=3600
        )
        
        result = continuous_processor.run_cli_command(
            ["slow-command"],
            "Slow command"
        )
        
        assert result is False

    def test_run_cli_command_exception(self, mock_subprocess):
        """Test CLI command exception handling."""
        mock_subprocess.side_effect = Exception("Unexpected error")
        
        result = continuous_processor.run_cli_command(
            ["broken-command"],
            "Broken command"
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
    """Test the process_entity_extraction function - the fixed code."""

    def test_process_entity_extraction_returns_false_when_count_zero(self, mock_subprocess):
        """Test that entity extraction is skipped when count is 0."""
        result = continuous_processor.process_entity_extraction(0)
        
        assert result is False
        mock_subprocess.assert_not_called()

    def test_process_entity_extraction_builds_correct_command(self, mock_subprocess):
        """Test that entity extraction command is built correctly WITHOUT --limit."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        continuous_processor.process_entity_extraction(50)
        
        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]
        
        # Verify command structure
        assert "populate-gazetteer" in cmd
        
        # CRITICAL: Verify that --limit is NOT in the command
        assert "--limit" not in cmd, "populate-gazetteer should NOT have --limit argument"

    def test_process_entity_extraction_no_limit_argument(self, mock_subprocess):
        """Test that entity extraction does NOT pass --limit (regression test for bug)."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # This should NOT fail with "unrecognized arguments: --limit"
        result = continuous_processor.process_entity_extraction(100)
        
        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]
        
        # Double-check: ensure no --limit anywhere in command
        for i, arg in enumerate(cmd):
            if arg == "--limit":
                pytest.fail(f"Found --limit at position {i} in command: {cmd}")
        
        # The command should only contain the base CLI invocation + populate-gazetteer
        # Expected: [sys.executable, "-m", "src.cli.cli_modular", "populate-gazetteer"]
        assert cmd[-1] == "populate-gazetteer"
        assert result is True


class TestProcessCycle:
    """Test the process_cycle function."""

    @patch("orchestration.continuous_processor.process_verification")
    @patch("orchestration.continuous_processor.process_extraction")
    @patch("orchestration.continuous_processor.process_analysis")
    @patch("orchestration.continuous_processor.process_entity_extraction")
    @patch("orchestration.continuous_processor.WorkQueue.get_counts")
    def test_process_cycle_runs_all_steps_with_work(
        self,
        mock_get_counts,
        mock_entity,
        mock_analysis,
        mock_extraction,
        mock_verification,
    ):
        """Test that process_cycle runs all steps when there's work."""
        mock_get_counts.return_value = {
            "verification_pending": 10,
            "extraction_pending": 20,
            "cleaning_pending": 25,
            "analysis_pending": 30,
            "entity_extraction_pending": 40,
        }
        
        continuous_processor.process_cycle()
        
        mock_verification.assert_called_once_with(10)
        mock_extraction.assert_called_once_with(20)
        mock_analysis.assert_called_once_with(30)
        mock_entity.assert_called_once_with(40)

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
        
        continuous_processor.process_cycle()
        
        # process_cycle() only calls process functions if count > 0
        # So with all counts at 0, none should be called
        mock_verification.assert_not_called()
        mock_extraction.assert_not_called()
        mock_analysis.assert_not_called()
        mock_entity.assert_not_called()

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


class TestCommandArgumentsRegression:
    """Regression tests for command argument bugs."""

    def test_populate_gazetteer_has_no_limit_argument(self, mock_subprocess):
        """
        Regression test: populate-gazetteer should NOT have --limit argument.
        
        This test catches the bug that caused:
        'news-crawler: error: unrecognized arguments: --limit 50'
        
        Bug was in process_entity_extraction() passing --limit to populate-gazetteer.
        """
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Run entity extraction
        continuous_processor.process_entity_extraction(50)
        
        # Get the command that was run
        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]
        
        # CRITICAL ASSERTION: --limit should NOT be present
        assert "--limit" not in cmd, (
            "BUG: populate-gazetteer command incorrectly includes --limit argument. "
            "This command does not accept --limit and will fail with: "
            "'news-crawler: error: unrecognized arguments: --limit 50'"
        )
        
        # Verify the command is just the base CLI + populate-gazetteer
        assert "populate-gazetteer" in cmd
        
        # Count arguments after "populate-gazetteer" - should be 0
        gazetteer_idx = cmd.index("populate-gazetteer")
        args_after = cmd[gazetteer_idx + 1:]
        assert len(args_after) == 0, (
            f"populate-gazetteer should have no arguments, but found: {args_after}"
        )

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
