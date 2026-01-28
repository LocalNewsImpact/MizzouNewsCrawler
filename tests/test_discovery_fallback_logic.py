import json
import logging
from unittest.mock import ANY, MagicMock, patch

import pandas as pd
import pytest

from src.crawler.discovery import NewsDiscovery
from src.crawler.source_processing import DiscoveryMethod, SourceProcessor
from src.models import create_tables
from src.models.database import DatabaseManager, safe_execute


class TestSourceProcessorCoverage:
    @pytest.fixture
    def mock_processor_setup(self, tmp_path):
        """Set up a mock environment for SourceProcessor testing."""
        db_path = tmp_path / "test_processor_fallback.db"
        database_url = f"sqlite:///{db_path}"

        # Create discovery instance
        discovery = NewsDiscovery(database_url=database_url)

        # Create required tables via ORM (includes typed columns)
        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)

        yield discovery, database_url, db_manager

        db_manager.close()

    def _create_processor(self, discovery, source_id, host, metadata=None, **kwargs):
        if metadata is None:
            metadata = {}

        # Prepare DB record using begin() for auto-commit
        with discovery._create_db_manager().engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT OR REPLACE INTO sources (
                    id, host, host_norm, status, metadata,
                    rss_consecutive_failures, rss_transient_failures,
                    no_effective_methods_consecutive
                )
                VALUES (
                    :id, :host, :host_norm, :status, :metadata,
                    :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps(metadata),
                    "rss_cf": kwargs.get("rss_cf", 0),
                    "rss_tf": json.dumps(kwargs.get("rss_tf", [])),
                    "nem_cf": kwargs.get("nem_cf", 0),
                },
            )

        source_row = pd.Series(
            {
                "id": source_id,
                "url": f"https://{host}",
                "name": host,
                "host": host,
                "metadata": json.dumps(metadata),
            }
        )

        processor = SourceProcessor(
            discovery=discovery,
            source_row=source_row,
            dataset_label=None,
            operation_id="test-op",
        )
        return processor

    def test_fallback_methods_added_after_two_failures(self, mock_processor_setup):
        discovery, _, _ = mock_processor_setup

        with patch.object(discovery, "telemetry") as mock_telemetry:
            mock_telemetry.has_historical_data.return_value = True
            mock_telemetry.get_effective_discovery_methods.return_value = [
                DiscoveryMethod.NEWSPAPER4K
            ]

            processor = self._create_processor(
                discovery,
                "test-source-fallback",
                "test-fallback.com",
                nem_cf=2,
                metadata={"frequency": "daily"},
            )
            processor._initialize_context()

            # Ensure the counter was actually read from DB correctly
            assert (
                processor._get_counter_value() == 2
            ), "Counter not loaded from DB correctly"

            assert (
                DiscoveryMethod.RSS_FEED in processor.effective_methods
            ), f"Effective methods: {processor.effective_methods}"
            assert DiscoveryMethod.NEWSPAPER4K in processor.effective_methods

    def test_no_fallback_at_zero_failures(self, mock_processor_setup):
        discovery, _, _ = mock_processor_setup

        with patch.object(discovery, "telemetry") as mock_telemetry:
            mock_telemetry.has_historical_data.return_value = True
            mock_telemetry.get_effective_discovery_methods.return_value = [
                DiscoveryMethod.NEWSPAPER4K
            ]

            processor = self._create_processor(
                discovery,
                "test-source-healthy",
                "test-healthy.com",
                nem_cf=1,
                metadata={"frequency": "daily"},
            )
            processor._initialize_context()

            assert processor.effective_methods == [DiscoveryMethod.NEWSPAPER4K]
            assert DiscoveryMethod.RSS_FEED not in processor.effective_methods

    def test_calculate_pause_threshold(self, mock_processor_setup):
        discovery, _, _ = mock_processor_setup

        # Daily -> 7
        p1 = self._create_processor(
            discovery, "s1", "h1", metadata={"frequency": "daily"}
        )
        p1._initialize_context()
        assert p1._calculate_pause_threshold() == 7

        # Weekly -> 5
        p2 = self._create_processor(
            discovery, "s2", "h2", metadata={"frequency": "weekly"}
        )
        p2._initialize_context()
        assert p2._calculate_pause_threshold() == 5

        # Monthly -> 3
        p3 = self._create_processor(
            discovery, "s3", "h3", metadata={"frequency": "monthly"}
        )
        p3._initialize_context()
        assert p3._calculate_pause_threshold() == 3

        # Unknown -> 5 (default 7 days -> 5 threshold)
        p4 = self._create_processor(discovery, "s4", "h4", metadata={})
        p4._initialize_context()
        assert p4._calculate_pause_threshold() == 5

    def test_prioritize_last_success(self, mock_processor_setup):
        discovery, _, _ = mock_processor_setup

        # Test prioritizing RSS
        p1 = self._create_processor(
            discovery, "s_rss", "h_rss", metadata={"last_successful_method": "rss_feed"}
        )
        p1._initialize_context()
        methods = [DiscoveryMethod.NEWSPAPER4K, DiscoveryMethod.RSS_FEED]
        ordered = p1._prioritize_last_success(methods)
        assert ordered[0] == DiscoveryMethod.RSS_FEED

        # Test prioritizing Newspaper
        p2 = self._create_processor(
            discovery,
            "s_news",
            "h_news",
            metadata={"last_successful_method": "newspaper4k"},
        )
        p2._initialize_context()
        methods = [DiscoveryMethod.RSS_FEED, DiscoveryMethod.NEWSPAPER4K]
        ordered = p2._prioritize_last_success(methods)
        assert ordered[0] == DiscoveryMethod.NEWSPAPER4K

    def test_parse_source_meta_legacy_bridge(self, mock_processor_setup):
        """Test that legacy JSON metadata is correctly merged with typed columns."""
        discovery, database_url, db_manager = mock_processor_setup

        # Manually insert a row with distinct values in JSON vs Typed columns
        source_id = "test-legacy-bridge"
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                    id, host, host_norm, status, metadata,
                    rss_consecutive_failures,
                    rss_transient_failures,
                    no_effective_methods_consecutive
                )
                VALUES (:id, :host, :host_norm, :status, :metadata, :rss_cf, :rss_tf, :nem_cf)
                """,
                {
                    "id": source_id,
                    "host": "bridge.com",
                    "host_norm": "bridge.com",
                    "status": "active",
                    "metadata": json.dumps(
                        {
                            "rss_consecutive_failures": 99,  # Old value in JSON
                            "frequency": "daily",
                        }
                    ),
                    "rss_cf": 5,  # authoritative typed value
                    "rss_tf": "[]",  # required default
                    "nem_cf": 2,
                },
            )

        source_row = pd.Series(
            {
                "id": source_id,
                "url": "https://bridge.com",
                "name": "bridge",
                "metadata": json.dumps(
                    {"rss_consecutive_failures": 99}
                ),  # Passed from pandas
            }
        )

        processor = SourceProcessor(discovery, source_row, None, "op")
        processor._initialize_context()

        # Should reflect the typed column value (5), NOT the JSON value (99)
        assert processor.source_meta["rss_consecutive_failures"] == 5
        assert processor.source_meta["no_effective_methods_consecutive"] == 2

    def test_has_persistent_technical_errors(self, mock_processor_setup):
        discovery, _, _ = mock_processor_setup
        processor = self._create_processor(discovery, "tech-err", "tech.com")
        processor._initialize_context()

        # Case 1: 403 Forbidden
        processor.rss_summary = {"network_errors": 5, "last_transient_status": 403}
        has_error, reason = processor._has_persistent_technical_errors()
        assert has_error is True
        assert "403 Forbidden" in reason

        # Case 2: 0 success, many tries
        processor.rss_summary = {
            "network_errors": 10,
            "feeds_tried": 5,
            "feeds_successful": 0,
            "last_transient_status": None,
        }
        has_error, reason = processor._has_persistent_technical_errors()
        assert has_error is True
        assert "Network failures" in reason

        # Case 3: No errors
        processor.rss_summary = {"network_errors": 0}
        has_error, reason = processor._has_persistent_technical_errors()
        assert has_error is False

    @patch("src.crawler.source_processing.SourceProcessor._run_discovery_methods")
    @patch("src.crawler.source_processing.SourceProcessor._discover_and_store_sections")
    @patch("src.crawler.source_processing.SourceProcessor._store_candidates")
    def test_process_flow(
        self, mock_store, mock_sections, mock_run, mock_processor_setup
    ):
        """Test the high level process method calls the right components."""
        discovery, _, _ = mock_processor_setup
        processor = self._create_processor(discovery, "flow-test", "flow.com")

        # Mock returns
        mock_run.return_value = [{"url": "http://flow.com/a1"}]
        mock_store.return_value = {
            "articles_new": 1,
            "articles_found_total": 1,
            "articles_duplicate": 0,
            "articles_expired": 0,
            "stored_count": 1,
            "articles_out_of_scope": 0,
        }

        result = processor.process()

        # Verify call chain
        mock_run.assert_called_once()
        mock_sections.assert_called_once()
        mock_store.assert_called_once()

        assert result.articles_found == 1
