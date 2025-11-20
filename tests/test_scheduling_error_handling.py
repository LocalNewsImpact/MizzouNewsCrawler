import logging
from unittest.mock import MagicMock, patch
from src.crawler.scheduling import should_schedule_discovery


class TestSchedulingErrorHandling:
    """Tests for error handling in scheduling logic."""

    def test_should_schedule_discovery_db_error(self, caplog):
        """
        Test that should_schedule_discovery returns True (safe default)
        and logs the error when the database query fails.
        """
        caplog.set_level(logging.DEBUG)

        mock_db = MagicMock()
        # Simulate a database error when connecting or executing
        mock_db.engine.connect.side_effect = Exception("Database Connection Failed")

        source_id = "test-source"

        # Call the function
        result = should_schedule_discovery(mock_db, source_id)

        # Assert safe default
        assert result is True

        # Assert error logging
        assert (
            "Could not query last processed date for test-source: "
            "Database Connection Failed" in caplog.text
        )

    def test_should_schedule_discovery_metadata_error(self, caplog):
        """
        Test that should_schedule_discovery handles malformed metadata gracefully.
        """
        mock_db = MagicMock()
        # Mock successful DB query returning None (no prior processing)
        mock_conn = MagicMock()
        mock_db.engine.connect.return_value.__enter__.return_value = mock_conn

        # Mock safe_execute to return None (no rows)
        with patch("src.crawler.scheduling.safe_execute") as mock_execute:
            mock_execute.return_value.fetchone.return_value = None

            # Pass malformed metadata that might cause parsing errors
            source_meta = {"frequency": ["invalid", "type"]}  # List instead of string

            result = should_schedule_discovery(mock_db, "test-source", source_meta)

            # Should default to 7 days cadence and return True since no last
            # processed date
            assert result is True

    def test_should_schedule_discovery_date_parsing_error(self, caplog):
        """
        Test handling of invalid date strings in the database.
        """
        caplog.set_level(logging.DEBUG)

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("src.crawler.scheduling.safe_execute") as mock_execute:
            # Return an invalid date string
            mock_execute.return_value.fetchone.return_value = ["not-a-date"]

            result = should_schedule_discovery(mock_db, "test-source")

            # Should treat invalid date as None and return True
            assert result is True
