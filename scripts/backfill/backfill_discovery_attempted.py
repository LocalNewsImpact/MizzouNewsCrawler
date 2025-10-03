#!/usr/bin/env python3

"""
Backfill discovery_attempted column from existing discovery evidence.

This script updates the discovery_attempted timestamp for sources that have
evidence of previous discovery attempts in other tables.
"""

import sqlite3
from pathlib import Path


def backfill_discovery_attempted():
    """Backfill discovery_attempted column from existing evidence."""
    db_path = "data/mizzou.db"

    if not Path(db_path).exists():
        print(f"Database not found at {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("Starting discovery_attempted backfill...")

        # Strategy 1: Use discovery_outcomes table (most recent evidence)
        print("\n1. Backfilling from discovery_outcomes table...")
        cursor.execute("""
            UPDATE sources 
            SET discovery_attempted = (
                SELECT MIN(timestamp) 
                FROM discovery_outcomes 
                WHERE discovery_outcomes.source_id = sources.id
            )
            WHERE id IN (
                SELECT DISTINCT source_id 
                FROM discovery_outcomes
            )
            AND discovery_attempted IS NULL
        """)
        outcomes_updated = cursor.rowcount
        print(f"   Updated {outcomes_updated} sources from discovery_outcomes")

        # Strategy 2: Use candidate_links table (older evidence)
        print("\n2. Backfilling from candidate_links table...")
        cursor.execute("""
            UPDATE sources 
            SET discovery_attempted = (
                SELECT MIN(created_at) 
                FROM candidate_links 
                WHERE candidate_links.source_host_id = sources.id
            )
            WHERE id IN (
                SELECT DISTINCT source_host_id 
                FROM candidate_links 
                WHERE source_host_id IS NOT NULL
            )
            AND discovery_attempted IS NULL
        """)
        candidate_links_updated = cursor.rowcount
        print(f"   Updated {candidate_links_updated} sources from candidate_links")

        # Strategy 3: Use discovery_method_effectiveness table if needed
        print("\n3. Backfilling from discovery_method_effectiveness table...")
        cursor.execute("""
            UPDATE sources 
            SET discovery_attempted = (
                SELECT MIN(last_attempt) 
                FROM discovery_method_effectiveness 
                WHERE discovery_method_effectiveness.source_id = sources.id
            )
            WHERE id IN (
                SELECT DISTINCT source_id 
                FROM discovery_method_effectiveness
            )
            AND discovery_attempted IS NULL
        """)
        effectiveness_updated = cursor.rowcount
        print(
            f"   Updated {effectiveness_updated} sources from discovery_method_effectiveness"
        )

        total_updated = (
            outcomes_updated + candidate_links_updated + effectiveness_updated
        )

        # Check final status
        cursor.execute(
            "SELECT COUNT(*) FROM sources WHERE discovery_attempted IS NOT NULL"
        )
        sources_with_attempts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sources WHERE discovery_attempted IS NULL")
        sources_never_attempted = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sources")
        total_sources = cursor.fetchone()[0]

        conn.commit()

        print("\n=== Backfill Results ===")
        print(f"Total sources updated: {total_updated}")
        print(f"Sources with discovery attempts: {sources_with_attempts}")
        print(f"Sources never attempted: {sources_never_attempted}")
        print(f"Total sources: {total_sources}")
        print(f"Coverage: {sources_with_attempts / total_sources * 100:.1f}%")

        return True

    except Exception as e:
        print(f"Error during backfill: {e}")
        return False
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    backfill_discovery_attempted()
