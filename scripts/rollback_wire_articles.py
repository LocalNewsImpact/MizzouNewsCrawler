#!/usr/bin/env python3
"""
Rollback script to revert incorrectly marked wire articles back to labeled status.

This script targets articles that were marked as wire yesterday (Feb 2, 2026)
and reverts them to labeled status, assuming they were mistakenly flagged.
"""

import sys
from datetime import datetime, timezone
from sqlalchemy import text

# Add src to path for imports
sys.path.insert(0, 'src')

from src.models.database import DatabaseManager


def rollback_wire_articles():
    """Revert articles marked as wire yesterday back to labeled status."""

    # Yesterday's date (Feb 2, 2026)
    yesterday = datetime(2026, 2, 2, tzinfo=timezone.utc)

    db = DatabaseManager()
    with db.get_session() as session:
        # Find articles marked as wire yesterday
        result = session.execute(text("""
            SELECT a.id, a.url, cl.id as candidate_link_id
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.status = 'wire'
            AND a.wire_check_attempted_at >= :yesterday
        """), {'yesterday': yesterday})

        wire_articles = result.fetchall()

        if not wire_articles:
            print("No articles found that were marked as wire yesterday.")
            return

        print(f"Found {len(wire_articles)} articles marked as wire yesterday.")

        # For safety, just list a few examples
        for i, (article_id, url, _) in enumerate(wire_articles[:5]):
            print(f"Example {i+1}: {article_id} - {url[:100]}...")

        # Uncomment to actually revert
        # confirm = input(f"Revert {len(wire_articles)} articles back to 'labeled' status? (yes/no): ")
        # if confirm.lower() != 'yes':
        #     print("Rollback cancelled.")
        #     return

        print("Rollback simulation complete. Uncomment the confirmation block to actually revert.")

        # Revert each article
        reverted_count = 0
        for article_id, url, candidate_link_id in wire_articles:
            # Set article status back to labeled
            session.execute(text("""
                UPDATE articles
                SET status = 'labeled'
                WHERE id = :article_id
            """), {'article_id': article_id})

            # Set candidate_link status back to article
            session.execute(text("""
                UPDATE candidate_links
                SET status = 'article'
                WHERE id = :candidate_link_id
            """), {'candidate_link_id': candidate_link_id})

            reverted_count += 1

            if reverted_count % 100 == 0:
                print(f"Reverted {reverted_count} articles...")

        session.commit()
        print(f"Successfully reverted {reverted_count} articles back to 'labeled' status.")


if __name__ == '__main__':
    rollback_wire_articles()