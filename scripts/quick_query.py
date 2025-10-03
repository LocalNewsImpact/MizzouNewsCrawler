#!/usr/bin/env python3
"""
Quick SQLite query tool for database analysis.

Usage:
    python scripts/quick_query.py discovery_status
    python scripts/quick_query.py source_counts
    python scripts/quick_query.py recent_activity --hours 24
    python scripts/quick_query.py unattempted_sources
    python scripts/quick_query.py custom "SELECT COUNT(*) FROM sources"
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def get_db_path():
    """Get the path to the database."""
    return Path(__file__).parent.parent / "data" / "mizzou.db"


def execute_query(query, params=None, description="Query results"):
    """Execute a query and print results."""
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        results = cursor.fetchall()

        print(f"\n=== {description} ===")

        if not results:
            print("No results found.")
            return

        # Print column headers if available
        if cursor.description:
            headers = [desc[0] for desc in cursor.description]
            if len(headers) > 1:
                print(" | ".join(headers))
                print("-" * (sum(len(h) for h in headers) + 3 * (len(headers) - 1)))

        # Print results
        for row in results:
            if len(row) == 1:
                print(row[0])
            else:
                print(" | ".join(str(val) for val in row))

        print(f"\nTotal rows: {len(results)}")

    except Exception as e:
        print(f"Error executing query: {e}")
    finally:
        if "conn" in locals():
            conn.close()


def discovery_status():
    """Check overall discovery status across all sources."""
    queries = [
        ("SELECT COUNT(*) as total_sources FROM sources", None, "Total Sources"),
        (
            """
            SELECT COUNT(*) as sources_with_discoveries
            FROM sources
            WHERE discovery_attempted IS NOT NULL
        """,
            None,
            "Sources With Discovery Attempts",
        ),
        (
            """
            SELECT COUNT(*) as unattempted_sources
            FROM sources
            WHERE discovery_attempted IS NULL
        """,
            None,
            "Sources Never Attempted",
        ),
    ]

    for query, params, desc in queries:
        execute_query(query, params, desc)


def source_counts():
    """Show article counts by source."""
    query = """
        SELECT 
            cl.source_name,
            COUNT(*) as article_count,
            MIN(cl.created_at) as first_discovery,
            MAX(cl.created_at) as last_discovery
        FROM candidate_links cl
        GROUP BY cl.source_name
        ORDER BY article_count DESC
        LIMIT 20
    """
    execute_query(query, None, "Top 20 Sources by Article Count")


def recent_activity(hours=24):
    """Show recent discovery activity."""
    since_time = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    queries = [
        (
            """
            SELECT COUNT(DISTINCT cl.source_name) as active_sources
            FROM candidate_links cl
            WHERE cl.created_at >= ?
        """,
            (since_time,),
            f"Sources Active in Last {hours} Hours",
        ),
        (
            """
            SELECT 
                cl.source_name,
                COUNT(*) as articles_found
            FROM candidate_links cl
            WHERE cl.created_at >= ?
            GROUP BY cl.source_name
            ORDER BY articles_found DESC
            LIMIT 10
        """,
            (since_time,),
            f"Top Sources in Last {hours} Hours",
        ),
    ]

    for query, params, desc in queries:
        execute_query(query, params, desc)


def unattempted_sources(limit=20):
    """Show sources that have never been attempted."""
    query = """
        SELECT s.host, s.canonical_name
        FROM sources s
        LEFT JOIN candidate_links cl ON s.id = cl.source_host_id
        WHERE cl.source_host_id IS NULL
        ORDER BY s.host
        LIMIT ?
    """
    execute_query(query, (limit,), f"Unattempted Sources (first {limit})")


def telemetry_status():
    """Check telemetry/operation tracking status."""
    queries = [
        ("SELECT COUNT(*) FROM operations", None, "Total Operations Tracked"),
        (
            """
            SELECT 
                operation_type,
                COUNT(*) as count,
                MAX(created_at) as last_run
            FROM operations
            GROUP BY operation_type
            ORDER BY count DESC
        """,
            None,
            "Operations by Type",
        ),
        (
            """
            SELECT COUNT(*) FROM discovery_outcomes
        """,
            None,
            "Discovery Outcomes Recorded",
        ),
        (
            """
            SELECT 
                outcome,
                COUNT(*) as count,
                ROUND(AVG(discovery_time_ms), 1) as avg_time_ms
            FROM discovery_outcomes
            GROUP BY outcome
            ORDER BY count DESC
        """,
            None,
            "Discovery Outcomes Summary",
        ),
    ]

    for query, params, desc in queries:
        try:
            execute_query(query, params, desc)
        except Exception as e:
            print(f"Error with {desc}: {e}")


def custom_query(sql):
    """Execute a custom SQL query."""
    execute_query(sql, None, "Custom Query Results")


def main():
    parser = argparse.ArgumentParser(description="Quick SQLite database queries")
    parser.add_argument(
        "command",
        choices=[
            "discovery_status",
            "source_counts",
            "recent_activity",
            "unattempted_sources",
            "telemetry_status",
            "custom",
        ],
        help="Query to run",
    )
    parser.add_argument("query", nargs="?", help="SQL query for custom command")
    parser.add_argument(
        "--hours", type=int, default=24, help="Hours back for recent_activity"
    )
    parser.add_argument("--limit", type=int, default=20, help="Limit for results")

    args = parser.parse_args()

    if args.command == "discovery_status":
        discovery_status()
    elif args.command == "source_counts":
        source_counts()
    elif args.command == "recent_activity":
        recent_activity(args.hours)
    elif args.command == "unattempted_sources":
        unattempted_sources(args.limit)
    elif args.command == "telemetry_status":
        telemetry_status()
    elif args.command == "custom":
        if not args.query:
            print("Error: custom command requires a SQL query")
            sys.exit(1)
        custom_query(args.query)


if __name__ == "__main__":
    main()
