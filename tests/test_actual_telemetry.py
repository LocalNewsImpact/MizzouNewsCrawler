"""Focused tests for the actual gazetteer telemetry implementation."""

import json
import logging
import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.populate_gazetteer import GazetteerTelemetry


class TestActualGazetteerTelemetry:
    """Test the actual GazetteerTelemetry implementation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.telemetry = GazetteerTelemetry()
        self.test_source_id = "test-source-123"

    def test_log_enrichment_attempt(self, caplog):
        """Test actual enrichment attempt logging."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_enrichment_attempt(
                source_id=self.test_source_id,
                source_name="Test News Source",
                city="Test City",
                county="Test County",
                state="MO",
            )

        assert len(caplog.records) == 1
        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "enrichment_attempt"
        assert log_data["source_id"] == self.test_source_id
        assert "timestamp" in log_data

    def test_log_geocoding_result_success(self, caplog):
        """Test actual geocoding result logging - success case."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_geocoding_result(
                source_id=self.test_source_id,
                method="nominatim",
                address_used="123 Main St, Test City, MO",
                success=True,
                lat=39.7,
                lon=-94.5,
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "geocoding_result"
        assert log_data["source_id"] == self.test_source_id
        assert log_data["geocoding"]["method"] == "nominatim"
        assert log_data["geocoding"]["success"] is True
        assert log_data["geocoding"]["coordinates"]["lat"] == 39.7
        assert log_data["geocoding"]["coordinates"]["lon"] == -94.5

    def test_log_geocoding_result_failure(self, caplog):
        """Test actual geocoding result logging - failure case."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_geocoding_result(
                source_id=self.test_source_id,
                method="nominatim",
                address_used="Invalid Address",
                success=False,
                error="Geocoding failed",
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["geocoding"]["success"] is False
        assert log_data["geocoding"]["error"] == "Geocoding failed"
        assert log_data["geocoding"]["coordinates"] is None

    def test_log_osm_query_result(self, caplog):
        """Test actual OSM query result logging."""
        categories_data = {"schools": 5, "businesses": 10, "landmarks": 3}

        with caplog.at_level(logging.INFO):
            self.telemetry.log_osm_query_result(
                source_id=self.test_source_id,
                total_elements=18,
                categories_data=categories_data,
                query_groups_used=3,
                radius_miles=20,
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "osm_query_result"
        assert log_data["osm_data"]["total_elements"] == 18
        assert log_data["osm_data"]["categories"] == categories_data
        assert log_data["osm_data"]["query_groups_used"] == 3
        assert log_data["osm_data"]["radius_miles"] == 20

    def test_log_enrichment_result_success(self, caplog):
        """Test actual enrichment result logging - success case."""
        categories_inserted = {"schools": 3, "businesses": 7}

        with caplog.at_level(logging.INFO):
            self.telemetry.log_enrichment_result(
                source_id=self.test_source_id,
                success=True,
                total_inserted=10,
                categories_inserted=categories_inserted,
                processing_time_seconds=45.2,
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["event"] == "enrichment_result"
        assert log_data["result"]["success"] is True
        assert log_data["result"]["total_inserted"] == 10
        assert log_data["result"]["categories_inserted"] == categories_inserted
        assert log_data["result"]["processing_time_seconds"] == 45.2

    def test_log_enrichment_result_failure(self, caplog):
        """Test actual enrichment result logging - failure case."""
        with caplog.at_level(logging.INFO):
            self.telemetry.log_enrichment_result(
                source_id=self.test_source_id,
                success=False,
                total_inserted=0,
                failure_reason="No OSM data found",
                processing_time_seconds=12.1,
            )

        log_data = json.loads(caplog.records[0].message)

        assert log_data["result"]["success"] is False
        assert log_data["result"]["total_inserted"] == 0
        assert log_data["result"]["failure_reason"] == "No OSM data found"
        assert log_data["result"]["processing_time_seconds"] == 12.1

    def test_log_structure_consistency(self, caplog):
        """Test that all log entries have consistent structure."""
        with caplog.at_level(logging.INFO):
            # Log all types of events
            self.telemetry.log_enrichment_attempt(
                source_id=self.test_source_id,
                source_name="Test Source",
                city="Test City",
                county="Test County",
                state="MO",
            )
            self.telemetry.log_geocoding_result(
                source_id=self.test_source_id,
                method="test",
                address_used="test address",
                success=True,
                lat=1.0,
                lon=1.0,
            )
            self.telemetry.log_osm_query_result(
                source_id=self.test_source_id,
                total_elements=5,
                categories_data={"schools": 5},
                query_groups_used=1,
                radius_miles=10,
            )
            self.telemetry.log_enrichment_result(
                source_id=self.test_source_id, success=True, total_inserted=5
            )

        # Verify all logs are valid JSON with required fields
        for record in caplog.records:
            log_data = json.loads(record.message)
            assert "timestamp" in log_data
            assert "event" in log_data
            assert "source_id" in log_data
            assert log_data["source_id"] == self.test_source_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
