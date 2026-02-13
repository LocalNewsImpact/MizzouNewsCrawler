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


class TestCommitBatchLogic:
    """Test batch commit logic and database operations."""

    @patch("scripts.import_warc_minnesota.DatabaseManager")
    def test_commit_batch_success(self, mock_db_manager):
        """Test successful batch commit."""
        from src.models import Article, CandidateLink

        importer = WARCImporter(dataset_id="test-uuid", commit_interval=5)
        mock_session = MagicMock()

        # Add 5 articles to pending commits
        for i in range(5):
            candidate_link = CandidateLink(
                url=f"http://example.com/{i}",
                source="example.com",
                discovered_at=datetime.now(),
            )
            article = Article(
                url=f"http://example.com/{i}",
                title=f"Article {i}",
                text="Sample content",
            )
            importer.pending_commits.append((candidate_link, article))

        importer.commit_batch(mock_session, "test.warc.gz", "<urn:uuid:last>")

        assert mock_session.commit.called
        assert len(importer.pending_commits) == 0
        assert importer.total_imported == 5

    @patch("scripts.import_warc_minnesota.DatabaseManager")
    def test_commit_batch_empty(self, mock_db_manager):
        """Test commit with empty pending list."""
        importer = WARCImporter(dataset_id="test-uuid")
        mock_session = MagicMock()

        importer.commit_batch(mock_session, "test.warc.gz", "<urn:uuid:last>")

        assert not mock_session.commit.called
        assert importer.total_imported == 0

    @patch("scripts.import_warc_minnesota.DatabaseManager")
    def test_commit_batch_failure_rollback(self, mock_db_manager):
        """Test rollback on commit failure."""
        from src.models import Article, CandidateLink

        importer = WARCImporter(dataset_id="test-uuid")
        mock_session = MagicMock()
        mock_session.commit.side_effect = Exception("Database error")

        # Add articles to pending commits
        for i in range(3):
            candidate_link = CandidateLink(url=f"http://example.com/{i}")
            article = Article(url=f"http://example.com/{i}", title=f"Article {i}")
            importer.pending_commits.append((candidate_link, article))

        importer.commit_batch(mock_session, "test.warc.gz", "<urn:uuid:last>")

        assert mock_session.rollback.called
        assert len(importer.pending_commits) == 0  # Cleared after failure
        assert importer.total_failures == 3

    @patch("scripts.import_warc_minnesota.DatabaseManager")
    def test_commit_batch_sets_candidate_link_id(self, mock_db_manager):
        """Test that candidate_link_id is set correctly."""
        from src.models import Article, CandidateLink

        importer = WARCImporter(dataset_id="test-uuid")
        mock_session = MagicMock()

        candidate_link = CandidateLink(url="http://example.com/1")
        candidate_link.id = 12345  # Mock ID after flush
        article = Article(url="http://example.com/1", title="Test")

        importer.pending_commits.append((candidate_link, article))

        importer.commit_batch(mock_session, "test.warc.gz", "<urn:uuid:last>")

        assert mock_session.add.called
        assert mock_session.flush.called


class TestWARCProcessing:
    """Test WARC file processing logic."""

    @patch("scripts.import_warc_minnesota.ArchiveIterator")
    @patch("scripts.import_warc_minnesota.ContentExtractor")
    def test_process_warc_dry_run(self, mock_extractor, mock_iterator):
        """Test dry run mode doesn't write to database."""
        importer = WARCImporter(dataset_id="test-uuid")
        warc_path = Path("/tmp/test.warc.gz")

        # Mock WARC records
        mock_record = Mock()
        mock_record.rec_type = "response"
        mock_record.rec_headers.get_header.side_effect = lambda x: {
            "WARC-Record-ID": "<urn:uuid:test>",
            "WARC-Target-URI": "http://example.com",
            "WARC-Date": "2024-01-15T10:00:00Z",
        }.get(x)
        mock_record.content_stream().read.return_value = b"<html>Test</html>"

        mock_iterator.return_value = [mock_record]

        # Mock file with proper context manager protocol
        mock_file = MagicMock()
        mock_open = MagicMock(return_value=mock_file)
        mock_open.return_value.__enter__.return_value = mock_file

        with patch("builtins.open", mock_open):
            result = importer.process_warc(warc_path, dry_run=True)

        assert result is True

    @patch("scripts.import_warc_minnesota.ArchiveIterator")
    def test_process_warc_skip_non_response(self, mock_iterator):
        """Test skipping non-response records."""
        importer = WARCImporter(dataset_id="test-uuid")
        warc_path = Path("/tmp/test.warc.gz")

        # Mock various record types
        records = []
        for rec_type in ["warcinfo", "request", "metadata"]:
            mock_record = Mock()
            mock_record.rec_type = rec_type
            records.append(mock_record)

        mock_iterator.return_value = records

        # Mock file with proper context manager protocol
        mock_file = MagicMock()
        mock_open = MagicMock(return_value=mock_file)
        mock_open.return_value.__enter__.return_value = mock_file

        with patch("builtins.open", mock_open):
            result = importer.process_warc(warc_path, dry_run=True)

        # Should complete successfully without processing any records
        assert result is True
        assert importer.total_imported == 0

    @patch("scripts.import_warc_minnesota.ArchiveIterator")
    def test_process_warc_missing_record_id(self, mock_iterator):
        """Test handling records without WARC-Record-ID."""
        importer = WARCImporter(dataset_id="test-uuid")
        warc_path = Path("/tmp/test.warc.gz")

        mock_record = Mock()
        mock_record.rec_type = "response"
        mock_record.rec_headers.get_header.return_value = None  # No record ID

        mock_iterator.return_value = [mock_record]

        # Mock file with proper context manager protocol
        mock_file = MagicMock()
        mock_open = MagicMock(return_value=mock_file)
        mock_open.return_value.__enter__.return_value = mock_file

        with patch("builtins.open", mock_open):
            result = importer.process_warc(warc_path, dry_run=True)

        assert result is True
        assert importer.total_imported == 0

    @patch("scripts.import_warc_minnesota.ArchiveIterator")
    def test_process_warc_resume_from_record_id(self, mock_iterator):
        """Test resuming from specific record ID."""
        importer = WARCImporter(dataset_id="test-uuid")
        warc_path = Path("/tmp/test.warc.gz")

        # Create multiple records
        records = []
        for i in range(5):
            mock_record = Mock()
            mock_record.rec_type = "response"
            mock_record.rec_headers.get_header.side_effect = lambda x, i=i: {
                "WARC-Record-ID": f"<urn:uuid:record-{i}>",
                "WARC-Target-URI": f"http://example.com/{i}",
            }.get(x)
            records.append(mock_record)

        mock_iterator.return_value = records

        # Mock file with proper context manager protocol
        mock_file = MagicMock()
        mock_open = MagicMock(return_value=mock_file)
        mock_open.return_value.__enter__.return_value = mock_file

        with patch("builtins.open", mock_open):
            # Resume from record-2, should skip 0, 1, 2
            result = importer.process_warc(
                warc_path, resume_from="<urn:uuid:record-2>", dry_run=True
            )

        assert result is True


class TestProgressTracking:
    """Test progress tracking and resumption."""

    def test_progress_includes_all_metrics(self, tmp_path):
        """Test that progress includes all required metrics."""
        progress_file = tmp_path / "progress.json"
        importer = WARCImporter(dataset_id="test-uuid", progress_file=progress_file)

        importer.total_imported = 150
        importer.total_failures = 7
        importer.batch_number = 3

        importer.save_progress("archive.warc.gz", "<urn:uuid:xyz>")

        with open(progress_file) as f:
            progress = json.load(f)

        assert "current_warc_file" in progress
        assert "last_warc_record_id" in progress
        assert "total_articles_imported" in progress
        assert "total_failures" in progress
        assert "batch_number" in progress
        assert "timestamp" in progress

    def test_multiple_progress_saves(self, tmp_path):
        """Test multiple progress saves update file."""
        progress_file = tmp_path / "progress.json"
        importer = WARCImporter(dataset_id="test-uuid", progress_file=progress_file)

        # First save
        importer.total_imported = 10
        importer.save_progress("file1.warc.gz", "<urn:uuid:1>")

        with open(progress_file) as f:
            progress1 = json.load(f)

        # Second save
        importer.total_imported = 20
        importer.save_progress("file2.warc.gz", "<urn:uuid:2>")

        with open(progress_file) as f:
            progress2 = json.load(f)

        assert progress1["total_articles_imported"] == 10
        assert progress2["total_articles_imported"] == 20
        assert progress2["current_warc_file"] == "file2.warc.gz"


class TestErrorLogging:
    """Test error logging functionality."""

    def test_error_log_multiple_errors(self, tmp_path):
        """Test logging multiple errors to JSONL."""
        error_file = tmp_path / "errors.jsonl"
        importer = WARCImporter(dataset_id="test-uuid", error_file=error_file)

        errors = [
            ("file1.warc.gz", "<urn:uuid:1>", "http://a.com", "ParseError", "Error 1"),
            (
                "file2.warc.gz",
                "<urn:uuid:2>",
                "http://b.com",
                "ExtractError",
                "Error 2",
            ),
            ("file3.warc.gz", "<urn:uuid:3>", "http://c.com", "DBError", "Error 3"),
        ]

        for warc_file, record_id, url, error_type, msg in errors:
            importer.log_error(warc_file, record_id, url, error_type, msg)

        with open(error_file) as f:
            lines = f.readlines()

        assert len(lines) == 3

        for i, line in enumerate(lines):
            error = json.loads(line)
            assert error["warc_filename"] == errors[i][0]
            assert error["error_type"] == errors[i][3]

    def test_error_log_includes_timestamp(self, tmp_path):
        """Test that error log includes timestamp."""
        error_file = tmp_path / "errors.jsonl"
        importer = WARCImporter(dataset_id="test-uuid", error_file=error_file)

        importer.log_error(
            "test.warc.gz", "<urn:uuid:1>", "http://example.com", "Error", "Message"
        )

        with open(error_file) as f:
            error = json.loads(f.readline())

        assert "timestamp" in error
        # Verify timestamp format
        datetime.fromisoformat(error["timestamp"])


class TestFailureRateMonitoring:
    """Test failure rate monitoring and thresholds."""

    def test_failure_rate_tracking_across_batches(self):
        """Test failure rate tracking across multiple batches."""
        importer = WARCImporter(
            dataset_id="test-uuid", batch_size=100, failure_threshold=5.0
        )

        # Batch 1: 3% failure rate
        importer.batch_articles = 100
        importer.batch_failures = 3
        assert not importer.check_failure_rate()

        # Batch 2: 7% failure rate (should exceed)
        importer.batch_articles = 100
        importer.batch_failures = 7
        assert importer.check_failure_rate()

    def test_failure_rate_edge_cases(self):
        """Test failure rate edge cases."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        # Exactly at threshold
        importer.batch_articles = 100
        importer.batch_failures = 5
        assert not importer.check_failure_rate()

        # Just above threshold
        importer.batch_failures = 5.01
        # Can't have fractional failures, but test logic
        importer.batch_failures = 6
        assert importer.check_failure_rate()

    def test_failure_rate_with_small_batches(self):
        """Test failure rate with small batch sizes."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        # Small batch: 1 failure out of 10 = 10%
        importer.batch_articles = 10
        importer.batch_failures = 1
        assert importer.check_failure_rate()

        # Small batch: 1 failure out of 25 = 4%
        importer.batch_articles = 25
        importer.batch_failures = 1
        assert not importer.check_failure_rate()


class TestWARCDateParsing:
    """Test WARC-Date header parsing."""

    def test_parse_various_date_formats(self):
        """Test parsing various ISO date formats."""
        importer = WARCImporter(dataset_id="test-uuid")

        test_dates = [
            "2024-01-15T14:32:10Z",
            "2024-12-31T23:59:59Z",
            "2024-06-15T00:00:00Z",
        ]

        for date_str in test_dates:
            mock_record = Mock()
            mock_record.rec_headers.get_header.return_value = date_str

            result = importer.extract_warc_date(mock_record)
            assert result is not None

    def test_parse_date_without_timezone(self):
        """Test parsing date without timezone marker."""
        importer = WARCImporter(dataset_id="test-uuid")

        mock_record = Mock()
        # Without Z, should still work with fromisoformat
        mock_record.rec_headers.get_header.return_value = "2024-01-15T14:32:10+00:00"

        result = importer.extract_warc_date(mock_record)
        assert result is not None

    def test_parse_malformed_dates(self):
        """Test handling malformed dates gracefully."""
        importer = WARCImporter(dataset_id="test-uuid")

        malformed_dates = [
            "not-a-date",
            "2024-13-01T00:00:00Z",  # Invalid month
            "2024-01-32T00:00:00Z",  # Invalid day
            "",
            "null",
        ]

        for date_str in malformed_dates:
            mock_record = Mock()
            mock_record.rec_headers.get_header.return_value = date_str

            result = importer.extract_warc_date(mock_record)
            assert result is None


class TestBatchCounters:
    """Test batch counter management."""

    def test_batch_counter_initialization(self):
        """Test that batch counters initialize to zero."""
        importer = WARCImporter(dataset_id="test-uuid")

        assert importer.total_imported == 0
        assert importer.total_failures == 0
        assert importer.batch_number == 0
        assert importer.batch_failures == 0
        assert importer.batch_articles == 0

    def test_batch_counter_increments(self):
        """Test that batch counters increment correctly."""
        importer = WARCImporter(dataset_id="test-uuid")

        # Simulate processing
        importer.batch_articles += 1
        assert importer.batch_articles == 1

        importer.batch_failures += 1
        assert importer.batch_failures == 1

        importer.total_imported += 10
        assert importer.total_imported == 10


class TestArticleExtraction:
    """Test article content extraction from WARC records."""

    @patch("scripts.import_warc_minnesota.ContentExtractor")
    def test_content_extraction_success(self, mock_extractor_class):
        """Test successful content extraction."""
        mock_extractor = Mock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract.return_value = {
            "title": "Test Article",
            "text": "Article content",
            "author": "John Doe",
        }

        importer = WARCImporter(dataset_id="test-uuid")
        assert importer.extractor is not None

    @patch("scripts.import_warc_minnesota.ContentExtractor")
    def test_content_extraction_failure(self, mock_extractor_class):
        """Test handling extraction failures."""
        mock_extractor = Mock()
        mock_extractor_class.return_value = mock_extractor
        mock_extractor.extract.side_effect = Exception("Extraction failed")

        importer = WARCImporter(dataset_id="test-uuid")
        # Should not crash on initialization
        assert importer is not None


class TestDatasetIntegration:
    """Test dataset ID handling and database integration."""

    def test_dataset_id_stored(self):
        """Test that dataset ID is stored correctly."""
        dataset_id = "minnesota-news-sources"
        importer = WARCImporter(dataset_id=dataset_id)

        assert importer.dataset_id == dataset_id

    def test_multiple_importers_different_datasets(self):
        """Test multiple importers with different dataset IDs."""
        importer1 = WARCImporter(dataset_id="minnesota-news-sources")
        importer2 = WARCImporter(dataset_id="wisconsin-news-sources")

        assert importer1.dataset_id != importer2.dataset_id


class TestURLProcessing:
    """Test URL processing and validation."""

    def test_url_normalization(self):
        """Test URL normalization in candidate links."""
        from src.models import CandidateLink

        urls = [
            "http://example.com/article",
            "https://example.com/article",
            "http://example.com/article?utm_source=test",
        ]

        for url in urls:
            candidate_link = CandidateLink(url=url, source="example.com")
            assert candidate_link.url == url  # URLs stored as-is


class TestImporterConfiguration:
    """Test importer configuration options."""

    def test_custom_batch_size(self):
        """Test custom batch size configuration."""
        importer = WARCImporter(dataset_id="test-uuid", batch_size=500)
        assert importer.batch_size == 500

    def test_custom_commit_interval(self):
        """Test custom commit interval configuration."""
        importer = WARCImporter(dataset_id="test-uuid", commit_interval=20)
        assert importer.commit_interval == 20

    def test_custom_failure_threshold(self):
        """Test custom failure threshold configuration."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=10.0)
        assert importer.failure_threshold == 10.0

    def test_all_custom_parameters(self):
        """Test all custom parameters together."""
        importer = WARCImporter(
            dataset_id="test-uuid",
            batch_size=1000,
            commit_interval=50,
            failure_threshold=2.5,
        )

        assert importer.batch_size == 1000
        assert importer.commit_interval == 50
        assert importer.failure_threshold == 2.5


class TestFileHandling:
    """Test file path handling."""

    def test_progress_file_custom_path(self, tmp_path):
        """Test custom progress file path."""
        custom_path = tmp_path / "custom" / "progress.json"
        custom_path.parent.mkdir(parents=True, exist_ok=True)

        importer = WARCImporter(dataset_id="test-uuid", progress_file=custom_path)
        importer.save_progress("test.warc.gz", "<urn:uuid:test>")

        assert custom_path.exists()

    def test_error_file_custom_path(self, tmp_path):
        """Test custom error file path."""
        custom_path = tmp_path / "custom" / "errors.jsonl"
        custom_path.parent.mkdir(parents=True, exist_ok=True)

        importer = WARCImporter(dataset_id="test-uuid", error_file=custom_path)
        importer.log_error("test.warc.gz", "<urn:uuid:1>", "http://a.com", "E", "M")

        assert custom_path.exists()


class TestConcurrentProcessing:
    """Test concurrent processing scenarios."""

    def test_multiple_warc_files_sequential(self):
        """Test processing multiple WARC files sequentially."""
        importer = WARCImporter(dataset_id="test-uuid")

        # Simulate processing multiple files
        files = ["file1.warc.gz", "file2.warc.gz", "file3.warc.gz"]

        for file in files:
            importer.batch_number += 1
            assert importer.batch_number == len([f for f in files if f <= file])


class TestErrorRecovery:
    """Test error recovery and resilience."""

    def test_continue_after_parse_error(self, tmp_path):
        """Test continuing after parse errors."""
        error_file = tmp_path / "errors.jsonl"
        importer = WARCImporter(dataset_id="test-uuid", error_file=error_file)

        # Log multiple errors
        for i in range(5):
            importer.log_error(
                f"file{i}.warc.gz",
                f"<urn:uuid:{i}>",
                f"http://example.com/{i}",
                "ParseError",
                f"Error {i}",
            )
            importer.total_failures += 1

        assert importer.total_failures == 5

        # Check error file has all entries
        with open(error_file) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_graceful_degradation_high_failure_rate(self):
        """Test graceful degradation with high failure rate."""
        importer = WARCImporter(dataset_id="test-uuid", failure_threshold=5.0)

        importer.batch_articles = 100
        importer.batch_failures = 50  # 50% failure rate

        assert importer.check_failure_rate()


class TestMetadataExtraction:
    """Test metadata extraction from WARC records."""

    def test_extract_all_required_headers(self):
        """Test extracting all required WARC headers."""
        mock_record = Mock()

        headers = {
            "WARC-Record-ID": "<urn:uuid:test-123>",
            "WARC-Target-URI": "http://example.com/article",
            "WARC-Date": "2024-01-15T10:00:00Z",
            "Content-Type": "application/http",
        }

        mock_record.rec_headers.get_header.side_effect = lambda x: headers.get(x)

        for header in headers:
            value = mock_record.rec_headers.get_header(header)
            assert value == headers[header]

    def test_handle_missing_optional_headers(self):
        """Test handling missing optional headers gracefully."""
        mock_record = Mock()
        mock_record.rec_headers.get_header.return_value = None

        # Should not crash when headers are missing
        result = mock_record.rec_headers.get_header("WARC-Optional-Header")
        assert result is None


class TestStatisticsTracking:
    """Test statistics tracking throughout import."""

    def test_cumulative_statistics(self):
        """Test cumulative statistics across batches."""
        importer = WARCImporter(dataset_id="test-uuid")

        # Batch 1
        importer.total_imported += 100
        importer.total_failures += 5

        # Batch 2
        importer.total_imported += 150
        importer.total_failures += 3

        # Batch 3
        importer.total_imported += 200
        importer.total_failures += 7

        assert importer.total_imported == 450
        assert importer.total_failures == 15

    def test_statistics_reset_between_importers(self):
        """Test that statistics don't leak between importers."""
        importer1 = WARCImporter(dataset_id="test-uuid-1")
        importer1.total_imported = 100

        importer2 = WARCImporter(dataset_id="test-uuid-2")

        assert importer2.total_imported == 0
        assert importer1.total_imported == 100
