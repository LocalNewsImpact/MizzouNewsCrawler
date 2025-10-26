#!/usr/bin/env python3
"""
Baseline Metrics Collection for PR #78 Phase 1

This script collects baseline metrics before deployment using the existing
DatabaseManager (Cloud SQL Python Connector, no sidecar proxy).

Run from project root with virtual environment activated:
    source venv/bin/activate
    python scripts/baseline_metrics.py
"""
import sys
from datetime import datetime

# Add src to path so we can import DatabaseManager
sys.path.insert(0, "/app")

from src.models.database import DatabaseManager
from sqlalchemy import text


def run_query(session, query, description):
    """Execute a SQL query and display results."""
    print(f"\n{description}")
    print("-" * 60)
    
    try:
        result = session.execute(text(query))
        rows = result.fetchall()
        
        if not rows:
            print("  (no data)")
        else:
            for row in rows:
                print("  " + " | ".join(str(x) for x in row))
        
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    """Collect baseline metrics from Cloud SQL database."""
    print("=" * 70)
    print(f"BASELINE METRICS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Queries to run
    queries = [
        (
            """
            SELECT status, COUNT(*) as count 
            FROM articles 
            GROUP BY status 
            ORDER BY count DESC
            """,
            "Query 1: Article counts by status"
        ),
        (
            """
            SELECT status, COUNT(*) as count 
            FROM candidate_links 
            GROUP BY status 
            ORDER BY count DESC
            """,
            "Query 2: Candidate link counts by status"
        ),
        (
            """
            SELECT COUNT(*) as new_articles 
            FROM articles 
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            """,
            "Query 3: Extraction rate (last 24 hours)"
        ),
        (
            """
            SELECT 'cleaning_pending' as queue, COUNT(*) as depth 
            FROM articles 
            WHERE status = 'cleaning_pending'
            UNION ALL
            SELECT 'analysis_pending' as queue, COUNT(*) as depth 
            FROM articles 
            WHERE status = 'analysis_pending'
            """,
            "Query 4: Queue depths"
        )
    ]
    
    try:
        # Create DatabaseManager (uses Cloud SQL Python Connector)
        print("\n[INFO] Connecting to Cloud SQL via Python Connector...")
        db_manager = DatabaseManager()
        
        with db_manager.get_session() as session:
            success_count = 0
            for query, description in queries:
                if run_query(session, query, description):
                    success_count += 1
            
            print("\n" + "=" * 70)
            print(
                f"BASELINE COMPLETE: {success_count}/{len(queries)} "
                "queries successful"
            )
            print("=" * 70)
            
            if success_count < len(queries):
                print("\n[WARNING] Some queries failed. Review errors above.")
                sys.exit(1)
            else:
                print(
                    "\n[SUCCESS] All queries completed. "
                    "Save this output to baseline_metrics.txt"
                )
                sys.exit(0)
    
    except Exception as e:
        print(f"\n[FATAL ERROR] Failed to connect to database: {e}")
        print("\nEnsure environment variables are set:")
        print("  - USE_CLOUD_SQL_CONNECTOR=true")
        print("  - CLOUD_SQL_INSTANCE=mizzou-news-crawler:us-central1:mizzou-db-prod")
        print("  - DATABASE_USER, DATABASE_PASSWORD, DATABASE_NAME")
        sys.exit(1)


if __name__ == "__main__":
    main()
