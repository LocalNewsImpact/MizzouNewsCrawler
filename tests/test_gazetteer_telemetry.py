"""Tests for gazetteer telemetry system.

This module tests the GazetteerTelemetry class and its integration
with the gazetteer population process to ensure proper logging
of enrichment attempts, geocoding results, OSM queries, and outcomes.
"""

import itertools
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

# Add repo root to path for direct script imports when running tests standalone
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.populate_gazetteer import (  # noqa: E402
    GazetteerTelemetry,
    _process_single_source_osm,
)


class TestGazetteerTelemetry:
    """Test the GazetteerTelemetry class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.telemetry = GazetteerTelemetry(enable_console=False)
        self.test_source_id = "test-source-123"

    def test_telemetry_initialization(self):
        """Test telemetry class initializes correctly."""
        assert self.telemetry.logger.name == "gazetteer_telemetry"
        assert self.telemetry.logger.level == logging.INFO

    def test_log_enrichment_attempt(self, caplog):
        """Test enrichment attempt logging."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_enrichment_attempt(
                source_id=self.test_source_id,
                source_name="Test Source",
                city="Test City",
                county="Test County",
                state="MO"
            )

        assert len(caplog.records) == 1
        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "enrichment_attempt"
        assert log_data["source_id"] == self.test_source_id
        assert log_data["source_name"] == "Test Source"
        assert log_data["location_data"]["city"] == "Test City"
        assert log_data["location_data"]["county"] == "Test County"
        assert log_data["location_data"]["state"] == "MO"
        assert "timestamp" in log_data

    def test_log_geocoding_result_success(self, caplog):
        """Test successful geocoding result logging."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_geocoding_result(
                source_id=self.test_source_id,
                method="street_address",
                address_used="123 Main St, Test City, MO",
                success=True,
                lat=39.7,
                lon=-94.5
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "geocoding_result"
        assert log_data["geocoding"]["method"] == "street_address"
        assert log_data["geocoding"]["success"] is True
        assert log_data["geocoding"]["address_used"] == (
            "123 Main St, Test City, MO"
        )
        assert log_data["geocoding"]["coordinates"] == {
            "lat": 39.7,
            "lon": -94.5,
        }

    def test_log_geocoding_result_failure(self, caplog):
        """Test failed geocoding result logging."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_geocoding_result(
                source_id=self.test_source_id,
                method="street_address",
                address_used="Invalid Address",
                success=False,
                error="Geocoding failed"
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["geocoding"]["success"] is False
        assert log_data["geocoding"]["error"] == "Geocoding failed"
        assert log_data["geocoding"]["coordinates"] is None

    def test_log_osm_query_result(self, caplog):
        """Test OSM query result logging."""
        categories_data = {
            "schools": 5,
            "businesses": 10,
            "landmarks": 3
        }

        with caplog.at_level(logging.INFO):
            self.telemetry.log_osm_query_result(
                source_id=self.test_source_id,
                total_elements=18,
                categories_data=categories_data,
                query_groups_used=3,
                radius_miles=20
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "osm_query_result"
        assert log_data["osm_data"]["total_elements"] == 18
        assert log_data["osm_data"]["categories"] == categories_data
        assert log_data["osm_data"]["query_groups_used"] == 3
        assert log_data["osm_data"]["radius_miles"] == 20

    def test_log_enrichment_result_success(self, caplog):
        """Test successful enrichment result logging."""
        categories_inserted = {
            "schools": 3,
            "businesses": 7
        }

        with caplog.at_level(logging.INFO):
            self.telemetry.log_enrichment_result(
                source_id=self.test_source_id,
                success=True,
                total_inserted=10,
                categories_inserted=categories_inserted,
                processing_time_seconds=45.2
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "enrichment_result"
        assert log_data["result"]["success"] is True
        assert log_data["result"]["total_inserted"] == 10
        assert log_data["result"]["categories_inserted"] == categories_inserted
        assert log_data["result"]["processing_time_seconds"] == 45.2
        assert log_data["result"]["failure_reason"] is None

    def test_log_enrichment_result_failure(self, caplog):
        """Test failed enrichment result logging."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_enrichment_result(
                source_id=self.test_source_id,
                success=False,
                total_inserted=0,
                failure_reason="No OSM data found",
                processing_time_seconds=12.1
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["result"]["success"] is False
        assert log_data["result"]["total_inserted"] == 0
        assert log_data["result"]["failure_reason"] == "No OSM data found"
        assert log_data["result"]["processing_time_seconds"] == 12.1

    def test_log_structure_consistency(self, caplog):
        """Test that all log entries follow consistent structure."""
        # Log all types of events
        with caplog.at_level(logging.INFO):
            self.telemetry.log_enrichment_attempt(
                source_id=self.test_source_id,
                source_name="Test Source",
                city="",
                county="",
                state=""
            )
            self.telemetry.log_geocoding_result(
                source_id=self.test_source_id,
                method="city_county",
                address_used="test",
                success=True,
                lat=1.0,
                lon=1.0
            )
            self.telemetry.log_osm_query_result(
                source_id=self.test_source_id,
                total_elements=5,
                categories_data={},
                query_groups_used=1,
                radius_miles=10
            )
            self.telemetry.log_enrichment_result(
                source_id=self.test_source_id,
                success=True,
                total_inserted=5
            )

        # Verify all logs are valid JSON with required fields
        for record in caplog.records:
            log_data = json.loads(record.message)
            assert "timestamp" in log_data
            assert "event" in log_data
            assert "source_id" in log_data
            assert log_data["source_id"] == self.test_source_id

        # ensure event-specific payload keys exist
        event_payload_keys = {
            "enrichment_attempt": "location_data",
            "geocoding_result": "geocoding",
            "osm_query_result": "osm_data",
            "enrichment_result": "result",
        }
        for record in caplog.records:
            log_data = json.loads(record.message)
            expected_key = event_payload_keys[log_data["event"]]
            assert expected_key in log_data


class TestGazetteerTelemetryIntegration:
    """Test telemetry integration with gazetteer functions."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = Mock()
        execute_result = Mock()
        execute_result.fetchone.return_value = SimpleNamespace(
            label="Dataset Label"
        )
        session.execute.return_value = execute_result
        session.commit = Mock()
        session.rollback = Mock()
        return session

    @pytest.fixture
    def sample_source_data(self):
        """Create sample source data for testing."""
        return {
            "id": "test-source-456",
            "canonical_name": "Test News Source",
            "city": "Springfield",
            "county": "Greene",
            "metadata": {"state": "MO", "zip": "65802"},
        }

    @pytest.fixture
    def mock_osm_response(self):
        """Create mock OSM API response data."""
        return {
            "schools": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 37.2,
                    "lon": -93.3,
                    "tags": {"name": "Test Elementary", "amenity": "school"},
                },
                {
                    "type": "node",
                    "id": 2,
                    "lat": 37.21,
                    "lon": -93.31,
                    "tags": {"name": "Test High School", "amenity": "school"},
                },
            ],
            "businesses": [
                {
                    "type": "node",
                    "id": 3,
                    "lat": 37.19,
                    "lon": -93.29,
                    "tags": {"name": "Test Store", "shop": "grocery"},
                }
            ],
        }

    @patch(
        "scripts.populate_gazetteer.has_existing_osm_data",
        return_value=False,
    )
    @patch("scripts.populate_gazetteer.set_cached_geocode")
    @patch("scripts.populate_gazetteer.get_cached_geocode", return_value=None)
    @patch("scripts.populate_gazetteer.geocode_address_nominatim")
    @patch("scripts.populate_gazetteer.query_overpass_grouped_categories")
    def test_telemetry_in_source_processing(
        self,
        mock_query_overpass,
        mock_geocode,
        mock_get_cached,
        mock_set_cached,
        mock_has_existing,
        mock_session,
        sample_source_data,
        mock_osm_response,
        caplog,
    ):
        """Test that telemetry is properly logged during source processing."""

        mock_geocode.return_value = {"lat": 37.2, "lon": -93.3}
        mock_query_overpass.return_value = mock_osm_response

        with caplog.at_level(logging.INFO):
            time_sequence = itertools.chain(
                [1000, 1045],
                itertools.repeat(1045),
            )
            with patch(
                "scripts.populate_gazetteer.time.time",
                side_effect=time_sequence,
            ):
                result = _process_single_source_osm(
                    session=mock_session,
                    src=sample_source_data,
                    dataset_id="dataset-001",
                    radius_miles=25,
                    dry_run=True,
                )

        assert result is True

        telemetry_logs = [
            json.loads(record.message)
            for record in caplog.records
            if record.name == "gazetteer_telemetry"
        ]

        expected_events = {
            "enrichment_attempt",
            "geocoding_result",
            "osm_query_result",
            "enrichment_result",
        }
        events = {log["event"] for log in telemetry_logs}
        assert expected_events.issubset(events)

        for log in telemetry_logs:
            assert log["source_id"] == "test-source-456"

        enrichment_records = [
            log
            for log in telemetry_logs
            if log["event"] == "enrichment_result"
        ]
        assert enrichment_records
        enrichment_payload = enrichment_records[-1]["result"]
        assert enrichment_payload["success"] is True
        assert enrichment_payload["total_inserted"] == 3
        assert enrichment_payload["processing_time_seconds"] == 45

        geocode_logs = [
            log for log in telemetry_logs if log["event"] == "geocoding_result"
        ]
        assert geocode_logs
        assert geocode_logs[0]["geocoding"]["method"] == "city_county"

    def test_telemetry_parameter_validation(self):
        """Test that telemetry methods validate required parameters."""

        telemetry = GazetteerTelemetry()

        with pytest.raises(TypeError):
            telemetry.log_enrichment_attempt()  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            telemetry.log_geocoding_result(
                source_id="test"
            )  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            telemetry.log_osm_query_result(  # type: ignore[call-arg]
                source_id="test"
            )

        with pytest.raises(TypeError):
            telemetry.log_enrichment_result()  # type: ignore[call-arg]


class TestGazetteerTelemetryErrorHandling:
    """Test telemetry error handling and edge cases."""

    def test_telemetry_with_none_values(self, caplog):
        """Test telemetry handles None values gracefully."""
        telemetry = GazetteerTelemetry()

        with caplog.at_level(logging.INFO):
            none_value = cast(str, None)
            telemetry.log_enrichment_attempt(
                source_id="test",
                source_name="Example Source",
                city=none_value,
                county=none_value,
                state=none_value,
            )

        log_data = json.loads(caplog.records[0].message)
        assert log_data["location_data"]["city"] is None
        assert log_data["location_data"]["county"] is None
        assert log_data["location_data"]["state"] is None

    def test_telemetry_with_empty_categories(self, caplog):
        """Test telemetry with empty OSM categories."""
        telemetry = GazetteerTelemetry()

        with caplog.at_level(logging.INFO):
            telemetry.log_osm_query_result(
                source_id="test",
                total_elements=0,
                categories_data={},
                query_groups_used=0,
                radius_miles=20
            )

        log_data = json.loads(caplog.records[0].message)
        assert log_data["osm_data"]["total_elements"] == 0
        assert log_data["osm_data"]["categories"] == {}

    def test_telemetry_json_serialization(self, caplog):
        """Test that telemetry produces valid JSON even with complex data."""
        telemetry = GazetteerTelemetry()

        complex_categories = {
            "schools": 5,
            "businesses": 10,
            "landmarks": 0,
            "government": 2
        }

        with caplog.at_level(logging.INFO):
            telemetry.log_osm_query_result(
                source_id="test-complex",
                total_elements=17,
                categories_data=complex_categories,
                query_groups_used=4,
                radius_miles=25
            )

        # Verify JSON is parseable
        log_data = json.loads(caplog.records[0].message)
        assert log_data["osm_data"]["categories"] == complex_categories


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
