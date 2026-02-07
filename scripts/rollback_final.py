#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from sqlalchemy import text
from src.models.database import DatabaseManager
from datetime import datetime, timezone

yesterday = datetime(2026, 2, 2, tzinfo=timezone.utc)
db = DatabaseManager()
with db.get_session() as session:
    # Update articles
    result = session.execute(text("""
        UPDATE articles
        SET status = 'labeled'
        WHERE status = 'wire'
        AND wire_check_attempted_at >= :yesterday
    """), {'yesterday': yesterday})
    articles_updated = result.rowcount
    
    # Update candidate_links for the articles we just updated
    result = session.execute(text("""
        UPDATE candidate_links
        SET status = 'article'
        WHERE id IN (
            SELECT a.candidate_link_id
            FROM articles a
            WHERE a.status = 'labeled'
            AND a.wire_check_attempted_at >= :yesterday
        )
    """), {'yesterday': yesterday})
    links_updated = result.rowcount
    
    session.commit()
    print(f'Reverted {articles_updated} articles and {links_updated} candidate links')