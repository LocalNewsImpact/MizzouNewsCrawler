"""Final telemetry validation test.

This test demonstrates the complete telemetry system working
with realistic data and validates the JSON output structure.
"""

import json
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.populate_gazetteer import GazetteerTelemetry


def test_telemetry_json_output():
    """Test that telemetry produces proper JSON output for analytics."""
    
    # Set up logging to capture output
    logger = logging.getLogger("gazetteer_telemetry")
    logger.setLevel(logging.INFO)
    
    # Capture logs
    logs = []
    
    class LogCapture(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())
    
    handler = LogCapture()
    logger.addHandler(handler)
    logger.handlers = [handler]  # Ensure only our handler is used
    
    telemetry = GazetteerTelemetry()
    
    # Simulate realistic telemetry sequence
    print("🔍 Testing complete telemetry sequence...")
    
    # 1. Enrichment attempt
    telemetry.log_enrichment_attempt(
        source_id="test-source-final",
        source_name="Springfield Daily News",
        city="Springfield",
        county="Greene",
        state="MO"
    )
    
    # 2. Geocoding result
    telemetry.log_geocoding_result(
        source_id="test-source-final",
        method="nominatim",
        address_used="Springfield, Greene County, MO",
        success=True,
        lat=37.2153,
        lon=-93.2982
    )
    
    # 3. OSM query result
    telemetry.log_osm_query_result(
        source_id="test-source-final",
        total_elements=243,
        categories_data={
            "schools": 18,
            "businesses": 89,
            "landmarks": 12,
            "government": 8,
            "healthcare": 15,
            "religious": 34,
            "entertainment": 22,
            "sports": 45
        },
        query_groups_used=3,
        radius_miles=20
    )
    
    # 4. Enrichment result
    telemetry.log_enrichment_result(
        source_id="test-source-final",
        success=True,
        total_inserted=243,
        categories_inserted={
            "schools": 18,
            "businesses": 89,
            "landmarks": 12,
            "government": 8,
            "healthcare": 15,
            "religious": 34,
            "entertainment": 22,
            "sports": 45
        },
        processing_time_seconds=67.3
    )
    
    # Validate all logs are proper JSON
    print(f"📊 Generated {len(logs)} telemetry events")
    
    for i, log_msg in enumerate(logs, 1):
        try:
            log_data = json.loads(log_msg)
            print(f"✓ Event {i}: {log_data['event']}")
            
            # Validate required fields
            assert "timestamp" in log_data
            assert "event" in log_data
            assert "source_id" in log_data
            assert log_data["source_id"] == "test-source-final"
            
        except json.JSONDecodeError as e:
            print(f"✗ Event {i}: Invalid JSON - {e}")
            return False
        except AssertionError as e:
            print(f"✗ Event {i}: Missing required field - {e}")
            return False
    
    print("🎉 All telemetry events validated successfully!")
    print("\n📋 Sample telemetry JSON:")
    print(json.dumps(json.loads(logs[0]), indent=2))
    
    return True


if __name__ == "__main__":
    success = test_telemetry_json_output()
    sys.exit(0 if success else 1)