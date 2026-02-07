#!/usr/bin/env python3
"""
Re-run wire detection on articles that were incorrectly reset from wire status.
Uses the proper wire detection pipeline instead of manual restoration.
"""

import sys
sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager

def reset_wire_detection_for_recent_articles():
    """Reset wire detection status for recently processed articles so they can be re-detected."""

    db = DatabaseManager()
    with db.get_session() as session:
        # Reset wire detection for articles that were processed recently
        # This will allow the continuous processor to re-run wire detection on them
        result = session.execute(text('''
            UPDATE articles
            SET wire_check_status = 'pending',
                wire = NULL,
                wire_check_attempted_at = NULL,
                wire_check_error = NULL,
                wire_check_metadata = NULL
            WHERE status IN ('labeled', 'cleaned')
            AND extracted_at >= '2026-01-01'
            AND (wire_check_status IS NULL OR wire_check_status != 'pending')
        '''))

        reset_count = result.rowcount
        session.commit()

        print(f"Reset wire detection status for {reset_count} recently extracted articles")
        print("The continuous processor will now re-run wire detection on these articles")

        return reset_count

if __name__ == '__main__':
    reset_wire_detection_for_recent_articles()