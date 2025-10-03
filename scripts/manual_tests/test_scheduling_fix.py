#!/usr/bin/env python3
"""Test script to verify the scheduling logic works correctly."""

import sqlite3
from datetime import datetime
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.crawler.scheduling import should_schedule_discovery
from src.models.database import DatabaseManager


def test_weekly_source_scheduling():
    """Test that weekly sources are not scheduled multiple times per day."""
    print("Testing weekly source scheduling logic...")

    # Connect to database
    conn = sqlite3.connect("data/mizzou.db")
    cursor = conn.cursor()

    # Get Barry County Advertiser info
    barry_source_id = "5c02a690-ddc5-4782-b749-f132d266ea39"
    cursor.execute("SELECT metadata FROM sources WHERE id = ?", (barry_source_id,))
    row = cursor.fetchone()

    if not row or not row[0]:
        print("ERROR: Could not find Barry County Advertiser metadata")
        return False

    import json

    metadata = json.loads(row[0])
    frequency = metadata.get("frequency")
    last_discovery = metadata.get("last_discovery_at")

    print(f"Source frequency: {frequency}")
    print(f"Last discovery: {last_discovery}")

    # Test the scheduling logic
    db_manager = DatabaseManager("sqlite:///data/mizzou.db")
    should_schedule = should_schedule_discovery(
        db_manager, barry_source_id, source_meta=metadata
    )

    print(f"Should schedule for discovery: {should_schedule}")

    # For a weekly source discovered 6 minutes ago, this should be False
    if frequency == "weekly" and last_discovery:
        last_dt = datetime.fromisoformat(last_discovery)
        now = datetime.utcnow()
        hours_since = (now - last_dt).total_seconds() / 3600

        if hours_since < 24:  # Less than a day ago
            if should_schedule:
                print(
                    f"ERROR: Weekly source discovered {hours_since:.1f} hours ago should NOT be scheduled"
                )
                return False
            else:
                print(
                    f"SUCCESS: Weekly source discovered {hours_since:.1f} hours ago correctly NOT scheduled"
                )
                return True
        else:
            print(
                f"INFO: Source was discovered {hours_since:.1f} hours ago (more than 24h)"
            )

    conn.close()
    return True


if __name__ == "__main__":
    success = test_weekly_source_scheduling()
    print("\n" + "=" * 50)
    if success:
        print("SCHEDULING TEST PASSED")
    else:
        print("SCHEDULING TEST FAILED")
    print("=" * 50)
