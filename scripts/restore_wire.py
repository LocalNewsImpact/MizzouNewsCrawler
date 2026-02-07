#!/usr/bin/env python3
"""
Restore wire status for articles that have wire detection results but were reverted to labeled.
Processes in batches to avoid deadlocks.
"""

import sys
import time
sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager

def restore_wire_statuses(batch_size=100):
    db = DatabaseManager()
    total_restored = 0

    while True:
        with db.get_session() as session:
            # Get batch of articles to restore
            result = session.execute(text('''
                SELECT id FROM articles
                WHERE wire_check_status = 'complete'
                AND wire IS NOT NULL
                AND status != 'wire'
                LIMIT :batch_size
            '''), {'batch_size': batch_size})

            ids_to_restore = [row[0] for row in result.fetchall()]

            if not ids_to_restore:
                break

            print(f"Restoring batch of {len(ids_to_restore)} articles...")

            # Update in smaller chunks to avoid deadlocks
            for i in range(0, len(ids_to_restore), 50):
                chunk_ids = ids_to_restore[i:i+50]
                try:
                    session.execute(text('''
                        UPDATE articles
                        SET status = 'wire'
                        WHERE id = ANY(:ids)
                        AND wire_check_status = 'complete'
                        AND wire IS NOT NULL
                        AND status != 'wire'
                    '''), {'ids': chunk_ids})
                    session.commit()
                    total_restored += len(chunk_ids)
                    print(f"  Restored {len(chunk_ids)} articles (total: {total_restored})")
                except Exception as e:
                    print(f"  Error restoring chunk: {e}")
                    session.rollback()
                    # Wait a bit before retrying
                    time.sleep(1)
                    continue

    print(f"Total articles restored to wire status: {total_restored}")

if __name__ == '__main__':
    restore_wire_statuses()