"""Unit tests for WARC import script."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from scripts.import_warc_minnesota import WARCImporter


class TestWARCImporter:
    """Unit tests for WARCImporter class."""

    def test_init(self):
        """Test WARCImporter initialization."""
        importer = WARCImporter(
            dataset_id="test-uuid",
            batch_size=250,
            commit_interval=10,
            failure_threshold=5.0,
        )

        assert importer.dataset_id == "test-uuid"
        assert importer.batch_size == 250
        assert importer.commit_interval == 10
        assert importer.failure_threshold == 5.0
        assert importer.total_imported == 0
        assert importer.total_failures == 0

    def test_load_progress_no_file(self, tmp_path):
        """Test loading progress when no file exists."""
        importer = WARCImporter(
            dataset_id="test-uuid", progress_file=tmp_path / "progress.json"
        )

        progress = importer.load_progress()
        assert progress == {}

    def test_load_progress_existing_file(self, tmp_path):
        """Test loading progress from existing file."""
        progress_file = tmp_path / "progress.json"
        progress_data = {
            "current_warc_file": "test.warc.gz",
            "last_warc_record_id": "<urn:uuid:test-123>",
            "total_articles_imported": 100,
            "total_failures": 5,
        }

        with open(progress_file, "w") as f:
            json.dump(progress_data, f)

        importer = WARCImporter(dataset_id="test-uuid", progress_file=progress_file)

        progress = importer.load_progress()
        assert progress == progress_data

    def test_save_progress(self, tmp_path):
        """Test saving progress to file."""
        progress_file = tmp_path / "progress.json"
        importer = WARCImporter(dataset_id="test-uuid", progress_file=progress_file)

        importer.total_imported = 100
        importer.total_failures = 5
        importer.batch_number = 2

        importer.save_progress("test.warc.gz", "<urn:uuid:test-123>")

        assert progress_file.exists()

        with open(progress_file) as f:
            saved = json.load(f)

        assert saved["current_warc_file"] == "test.warc.gz"
        assert saved["last_warc_record_id"] == "<urn:uuid:test-123>"
        assert saved["total_articles_imported"] == 100
        assert saved["total_failures"] == 5
        assert saved["batch_number"] == 2

    def test_log_error(self, tmp_path):
        """Test error logging to JSONL."""
        error_file = tmp_path / "errors.jsonl"
        importer = WARCImporter(dataset_id="test-uuid", error_file=error_file)

        importer.log_error(
            "test.warc.gz",
            "<urn:uuid:test-123>",
            "http://example.com",
            "ParseError",
            "Failed to parse HTML",
        )

        assert error_file.exists()

        with open(error_file) as f:
            line = f.readline()
            error = json.loads(line)

        assert error["warc_filename"] == "test.warc.gz"
        assert error["warc_record_id"] == "<urn:uuid:test-123>"
        assert error["url"] == "http://example.com"
        assert error["error_type"] == "ParseError"
        assert error["error_message"] == "Failed to parse HTML"

    def test_check_failure_rate_below_threshold(self):
        """Test failure rate check when below threshold."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        importer.batch_articles = 100
        importer.batch_failures = 3  # 3% failure rate

        assert not importer.check_failure_rate()

    def test_check_failure_rate_at_threshold(self):
        """Test failure rate check at threshold."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        importer.batch_articles = 100
        importer.batch_failures = 5  # 5% failure rate

        assert not importer.check_failure_rate()  # Equal to threshold, not exceeded

    def test_check_failure_rate_above_threshold(self):
        """Test failure rate check when exceeds threshold."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        importer.batch_articles = 100
        importer.batch_failures = 6  # 6% failure rate

        assert importer.check_failure_rate()

    def test_check_failure_rate_no_articles(self):
        """Test failure rate check with no articles."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        importer.batch_articles = 0
        importer.batch_failures = 0

        assert not importer.check_failure_rate()

    def test_extract_warc_date_valid(self):
        """Test extracting valid WARC-Date header."""
        importer = WARCImporter(dataset_id="test-uuid")

        mock_record = Mock()
        mock_record.rec_headers.get_header.return_value = "2024-01-15T14:32:10Z"

        result = importer.extract_warc_date(mock_record)

        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 32

    def test_extract_warc_date_invalid(self):
        """Test extracting invalid WARC-Date header."""
        importer = WARCImporter(dataset_id="test-uuid")

        mock_record = Mock()
        mock_record.rec_headers.get_header.return_value = "invalid-date"

        result = importer.extract_warc_date(mock_record)

        assert result is None

    def test_extract_warc_date_missing(self):
        """Test extracting missing WARC-Date header."""
        importer = WARCImporter(dataset_id="test-uuid")

        mock_record = Mock()
        mock_record.rec_headers.get_header.return_value = None

        result = importer.extract_warc_date(mock_record)

        assert result is None

    @patch("scripts.import_warc_minnesota.ContentExtractor")
    def test_batch_commit_accumulation(self, mock_extractor):
        """Test that articles accumulate until commit interval."""
        importer = WARCImporter(dataset_id="test-uuid", commit_interval=10)

        assert len(importer.pending_commits) == 0

        # Simulate adding 9 articles
        for i in range(9):
            from src.models import Article, CandidateLink

            importer.pending_commits.append(
                (
                    CandidateLink(url=f"http://example.com/{i}"),
                    Article(url=f"http://example.com/{i}", title=f"Title {i}"),
                )
            )

        assert len(importer.pending_commits) == 9

    def test_failure_rate_calculation_various_batches(self):
        """Test failure rate calculation with different batch sizes."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        # Test with batch_size=250
        importer.batch_articles = 250
        importer.batch_failures = 12  # 4.8%, below threshold
        assert not importer.check_failure_rate()

        importer.batch_failures = 13  # 5.2%, above threshold
        assert importer.check_failure_rate()

        # Test with batch_size=500
        importer.batch_articles = 500
        importer.batch_failures = 24  # 4.8%, below threshold
        assert not importer.check_failure_rate()

        importer.batch_failures = 26  # 5.2%, above threshold
        assert importer.check_failure_rate()


class TestCLIArguments:
    """Test CLI argument parsing."""

    def test_required_arguments(self):
        """Test that required arguments are enforced."""
        import sys

        from scripts.import_warc_minnesota import main

        # Mock sys.argv to test argparse
        with patch.object(sys, "argv", ["import_warc_minnesota.py"]):
            with pytest.raises(SystemExit):
                main()

    def test_default_values(self):
        """Test default argument values."""
        import sys
        import tempfile

        from scripts.import_warc_minnesota import main

        with tempfile.TemporaryDirectory() as tmpdir:
            test_args = [
                "import_warc_minnesota.py",
                "--warc-dir",
                tmpdir,
                "--dataset-id",
                "test-uuid",
                "--dry-run",
            ]

            with patch.object(sys, "argv", test_args):
                with patch(
                    "scripts.import_warc_minnesota.WARCImporter"
                ) as mock_importer:
                    mock_instance = MagicMock()
                    mock_importer.return_value = mock_instance
                    mock_instance.import_directory.return_value = True

                    main()

                    # Verify default values were used
                    mock_importer.assert_called_once()
                    call_kwargs = mock_importer.call_args[1]
                    assert call_kwargs["batch_size"] == 250
                    assert call_kwargs["commit_interval"] == 10
                    assert call_kwargs["failure_threshold"] == 5.0
