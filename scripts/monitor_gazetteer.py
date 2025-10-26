#!/usr/bin/env python3
"""Simple gazetteer process monitoring script."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from src.models.database import DatabaseManager


def monitor_gazetteer():
    """Monitor gazetteer processes through telemetry."""
    db = DatabaseManager()

    print("🔍 Gazetteer Process Monitor")
    print("=" * 50)

    with db.engine.connect() as conn:
        # Get latest gazetteer processes
        result = conn.execute(
            text(
                """
            SELECT id, process_type, command, status, started_at, completed_at, 
                   progress_current, progress_total, error_message, process_metadata
            FROM background_processes 
            WHERE process_type LIKE '%gazetteer%' OR command LIKE '%gazetteer%'
            ORDER BY started_at DESC
            LIMIT 3
        """
            )
        )

        processes = result.fetchall()

        if not processes:
            print("⏳ No gazetteer processes found in telemetry")
            return

        for process in processes:
            print(f"📊 Process {process.id}:")
            print(f"  Type: {process.process_type}")
            print(f"  Status: {process.status}")
            print(f"  Started: {process.started_at}")

            if process.progress_total:
                pct = (process.progress_current / process.progress_total) * 100
                print(
                    f"  Progress: {process.progress_current}/{process.progress_total} ({pct:.1f}%)"
                )
            else:
                print(f"  Progress: {process.progress_current}")

            if process.completed_at:
                print(f"  Completed: {process.completed_at}")

            if process.error_message:
                print(f"  ❌ Error: {process.error_message}")

            print()

        # Check current gazetteer coverage
        result = conn.execute(
            text(
                """
            SELECT COUNT(*) as total_sources
            FROM sources
        """
            )
        )
        total = result.fetchone().total_sources

        result = conn.execute(
            text(
                """
            SELECT COUNT(DISTINCT source_id) as populated_sources
            FROM gazetteer
        """
            )
        )
        populated = result.fetchone().populated_sources

        remaining = total - populated

        print("📈 Current Coverage:")
        print(f"  Total sources: {total}")
        print(f"  Populated: {populated}")
        print(f"  Remaining: {remaining}")
        print(f"  Coverage: {populated / total * 100:.1f}%")


if __name__ == "__main__":
    monitor_gazetteer()
