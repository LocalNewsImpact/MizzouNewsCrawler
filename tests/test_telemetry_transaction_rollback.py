"""
Tests for telemetry transaction rollback behavior.
Ensures that database errors trigger a rollback to prevent 'InterfaceError: in failed transaction block'.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics,
)
from src.utils.telemetry import OperationTracker
from src.telemetry.store import TelemetryStore
from src.utils.discovery_outcomes import DiscoveryResult, DiscoveryOutcome


class FakeTelemetryStore(TelemetryStore):
    def __init__(self):
        self.submit = Mock()
        self.async_writes = False
        self._is_postgres = True
        self.connection = MagicMock()
        # Setup connection context manager
        self.connection.return_value.__enter__.return_value = Mock()


class TestTelemetryTransactionRollback(unittest.TestCase):
    def test_comprehensive_telemetry_rollback_on_integrity_error(self):
        """Test that ComprehensiveExtractionTelemetry rolls back on IntegrityError."""
        # Setup
        mock_store = FakeTelemetryStore()

        telemetry = ComprehensiveExtractionTelemetry(store=mock_store)
        metrics = ExtractionMetrics(
            operation_id="op1",
            article_id="art1",
            url="http://test.com",
            publisher="test",
        )

        # Trigger the method that defines 'writer' and calls store.submit
        telemetry.record_extraction(metrics)

        # Get the writer function passed to submit
        # submit(writer) is called
        if not mock_store.submit.called:
            self.fail("store.submit was not called")

        writer_func = mock_store.submit.call_args[0][0]

        # Mock connection
        mock_conn = Mock()

        error = IntegrityError("duplicate", {}, None)
        mock_conn.execute.side_effect = [error, Mock(), Mock(), Mock()]

        # Execute writer
        writer_func(mock_conn)

        # Assert rollback called
        # It should be called once after the first IntegrityError
        mock_conn.rollback.assert_called()

    def test_operation_tracker_rollback_on_db_error(self):
        """Test that OperationTracker rolls back on DB errors during retries."""
        # Setup
        mock_store = FakeTelemetryStore()

        tracker = OperationTracker(store=mock_store, database_url="sqlite:///:memory:")

        # Reset mock because _ensure_base_schema called submit
        mock_store.submit.reset_mock()

        # Create DiscoveryResult
        result = DiscoveryResult(
            outcome=DiscoveryOutcome.NEW_ARTICLES_FOUND,
            articles_found=10,
            articles_new=5,
            metadata={"discovery_time_ms": 100.0},
        )

        # Trigger record_discovery_outcome
        tracker.record_discovery_outcome(
            "op1", "source1", "Source Name", "http://source1.com", result
        )

        # Get writer
        if not mock_store.submit.called:
            self.fail("store.submit was not called")

        writer_func = mock_store.submit.call_args[0][0]

        # Mock connection
        mock_conn = Mock()
        # Raise error on execute
        # The writer uses cursor = conn.cursor(); cursor.execute(...)
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        error = SQLAlchemyError("DB Error")
        mock_cursor.execute.side_effect = error

        # Execute writer
        # It retries 4 times. We want to ensure rollback is called each time.
        try:
            writer_func(mock_conn)
        except SQLAlchemyError:
            pass  # Expected after retries exhausted

        # Assert rollback called at least once (actually 4 times)
        self.assertGreaterEqual(mock_conn.rollback.call_count, 1)
        self.assertEqual(mock_conn.rollback.call_count, 4)


if __name__ == "__main__":
    unittest.main()
