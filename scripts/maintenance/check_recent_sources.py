#!/usr/bin/env python3
"""Check if recent backfill sources actually got gazetteer data."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text

from src.models.database import DatabaseManager


def check_recent_sources():
    """Check if sources from recent backfill have gazetteer data."""
    db = DatabaseManager()

    # Sources from recent backfill log
    recent_sources = [
        "Columbia Daily Tribune",
        "Columbia Missourian",
        "Constitution-Tribune",
        "Courier Tribune",
        "Daily American Republic",
        "Daily Journal, Park Hills",
        "Delta Dunklin Democrat",
        "Dos Mundos Bilingual Newspaper",
        "Douglas County Herald",
        "El Dorado Springs Sun",
    ]

    print("🔍 Checking if recent backfill sources actually got gazetteer data...")
    print("=" * 70)

    with db.engine.connect() as conn:
        for source_name in recent_sources:
            # Check if this source has gazetteer entries
            result = conn.execute(
                text(
                    """
                SELECT COUNT(g.id) as gazetteer_count
                FROM sources s
                LEFT JOIN gazetteer g ON s.id = g.source_id
                WHERE s.canonical_name = :source_name
            """
                ),
                {"source_name": source_name},
            )

            count = result.fetchone().gazetteer_count
            status = "✅ HAS DATA" if count > 0 else "❌ NO DATA"
            print(f"{status}: {source_name} - {count} entries")

    print()
    print(
        'If any show "❌ NO DATA", then the populate-gazetteer command failed silently'
    )
    print(
        'If they show "✅ HAS DATA", then the monitor script has a bug in its selection logic'
    )


if __name__ == "__main__":
    check_recent_sources()
