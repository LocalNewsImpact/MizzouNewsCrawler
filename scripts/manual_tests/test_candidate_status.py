#!/usr/bin/env python3
"""Quick test to verify candidate status updates work."""

import sys
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))

from src.models.database import DatabaseManager


def test_candidate_status_update():
    """Test updating candidate status."""
    db = DatabaseManager()

    # Get a few candidates with status 'discovered'
    with db.engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT id, url, status FROM candidate_links WHERE status = 'discovered' LIMIT 3"
            )
        )
        candidates = [dict(row._mapping) for row in result]

    print(f"Found {len(candidates)} candidates with status 'discovered'")

    if not candidates:
        print("No candidates found with 'discovered' status")
        return

    # Test updating the first candidate
    candidate_id = candidates[0]["id"]
    print(f"Testing status update for candidate {candidate_id}")

    # Update to 'extracted' status
    with db.engine.connect() as conn:
        conn.execute(
            text(
                """UPDATE candidate_links 
               SET status = 'extracted', 
                   processed_at = :processed_at, 
                   publish_date = '2024-01-15'
               WHERE id = :candidate_id"""
            ),
            {"processed_at": datetime.now().isoformat(), "candidate_id": candidate_id},
        )
        conn.commit()

    # Verify the update
    with db.engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT id, status, processed_at, publish_date FROM candidate_links WHERE id = :candidate_id"
            ),
            {"candidate_id": candidate_id},
        )
        updated = dict(result.fetchone()._mapping)

    print(f"Updated candidate {candidate_id}:")
    print(f"  Status: {updated['status']}")
    print(f"  Processed at: {updated['processed_at']}")
    print(f"  Publish date: {updated['publish_date']}")

    # Check status distribution after update
    with db.engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT status, COUNT(*) as count FROM candidate_links GROUP BY status ORDER BY count DESC"
            )
        )
        status_counts = [dict(row._mapping) for row in result]

    print("\nStatus distribution after update:")
    for status in status_counts:
        print(f"  {status['status']}: {status['count']}")


if __name__ == "__main__":
    test_candidate_status_update()
