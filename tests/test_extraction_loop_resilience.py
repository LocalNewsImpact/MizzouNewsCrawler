from unittest.mock import MagicMock, patch

import pytest

from src.cli.commands.extraction import handle_extraction_command


@pytest.mark.unit
@patch("src.cli.commands.extraction.DatabaseManager")
@patch("src.cli.commands.extraction.ContentExtractor")
@patch("src.cli.commands.extraction.safe_session_execute")
@patch("src.cli.commands.extraction.BylineCleaner")
@patch("src.cli.commands.extraction.ComprehensiveExtractionTelemetry")
@patch("src.cli.commands.extraction._run_post_extraction_cleaning")
def test_extraction_loop_resilience(
    mock_post_clean,
    mock_telemetry_cls,
    mock_byline_cleaner_cls,
    mock_execute,
    mock_extractor_cls,
    mock_db_class,
    caplog,
):
    """
    Test that the extraction loop continues processing subsequent articles
    even if one article fails during extraction.
    """
    # Mock DatabaseManager
    mock_db_instance = MagicMock()
    mock_session = MagicMock()
    mock_db_instance.get_session.return_value.__enter__.return_value = mock_session
    mock_db_instance.session = mock_session  # For direct access
    mock_db_class.return_value = mock_db_instance

    # Mock ContentExtractor
    mock_extractor_instance = MagicMock()
    mock_extractor_cls.return_value = mock_extractor_instance

    # CRITICAL: _check_rate_limit must return False, otherwise the loop skips articles
    mock_extractor_instance._check_rate_limit.return_value = False

    # Mock BylineCleaner
    mock_byline_cleaner_instance = MagicMock()
    mock_byline_cleaner_cls.return_value = mock_byline_cleaner_instance
    mock_byline_cleaner_instance.clean_byline.return_value = {
        "authors": ["Test Author"],
        "wire_services": [],
        "is_wire_content": False,
    }

    # Mock Telemetry
    mock_telemetry_instance = MagicMock()
    mock_telemetry_cls.return_value = mock_telemetry_instance

    # Mock database results
    # We need to handle multiple calls to safe_session_execute:
    # 1. _analyze_dataset_domains (select distinct url)
    # 2. _process_batch (select candidate links)
    # 3. _get_status_counts (select count)

    # Define the rows for the main extraction query
    extraction_rows = [
        (1, "http://example.com/1", "example.com", "article", "Example"),
        (2, "http://example.com/2", "example.com", "article", "Example"),
    ]

    # Define a side effect to return appropriate results
    def execute_side_effect(session, query, params=None):
        query_str = str(query).strip()
        mock_result = MagicMock()

        if "SELECT DISTINCT cl.url" in query_str:
            # _analyze_dataset_domains
            mock_result.fetchall.return_value = [
                ("http://example.com/1",),
                ("http://example.com/2",),
            ]
            return mock_result

        if "SELECT cl.id, cl.url" in query_str:
            # Main extraction query
            mock_result.fetchall.return_value = extraction_rows
            return mock_result

        if "SELECT cl.status, COUNT(*)" in query_str:
            # _get_status_counts
            mock_result.fetchall.return_value = [("article", 0), ("extracted", 2)]
            return mock_result

        if "SELECT COUNT(*)" in query_str:
            # Remaining count
            mock_result.scalar.return_value = 0
            return mock_result

        # Default empty result for updates/inserts
        mock_result.fetchall.return_value = []
        return mock_result

    mock_execute.side_effect = execute_side_effect

    # Setup extraction failure for the first URL
    # First call raises Exception, second call returns content
    mock_extractor_instance.extract_content.side_effect = [
        Exception("Simulated Extraction Failure"),
        {
            "title": "Success Article",
            "text": "Some content",
            "author": "Test Author",
            "publish_date": "2023-01-01",
        },
    ]

    # Run the command
    args = MagicMock()
    args.limit = 10
    args.batches = 1
    args.source = None
    args.dataset = None
    args.exhaust_queue = False  # Stop after 1 batch

    # Call the function directly
    exit_code = handle_extraction_command(args)

    # Assertions
    assert exit_code == 0

    # Verify extract_content was called twice (once for each URL)
    assert mock_extractor_instance.extract_content.call_count == 2

    # Verify the first failure was logged
    # Note: The exact log message depends on how the exception is handled
    assert (
        "Simulated Extraction Failure" in caplog.text
        or "Failed to extract" in caplog.text
    )

    # Verify we attempted to insert the successful article
    # We can check if safe_session_execute was called with an INSERT statement
    insert_calls = [
        c for c in mock_execute.call_args_list if "INSERT INTO articles" in str(c[0][1])
    ]
    # We expect at least one insert for the successful article
    assert len(insert_calls) >= 1
