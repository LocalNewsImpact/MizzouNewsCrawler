#!/usr/bin/env python3
"""Export comprehensive discovery and status report for the past 48 hours.

Generates a CSV with all discovered URLs, their final status, and decision telemetry.
Groups results by host and includes hosts with no discoveries.
"""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
script_dir = Path(__file__).parent
if script_dir.name == "tmp":
    # Running in pod, add /app to path
    sys.path.insert(0, "/app")
else:
    # Running locally
    sys.path.insert(0, str(script_dir.parent))

from src.models.database import DatabaseManager


def export_discovery_status_report(hours: int = 48, output_file: str = "discovery_status_report.csv"):
    """Export discovery status report to CSV.

    Args:
        hours: Number of hours to look back (default: 48)
        output_file: Output CSV filename
    """
    db = DatabaseManager()

    print(f"Generating discovery status report for past {hours} hours...")
    print(f"Output file: {output_file}")

    # Query for all discoveries in the time period with their status decisions
    query = text("""
        WITH time_window AS (
            SELECT NOW() - INTERVAL '1 hour' * :hours AS cutoff
        ),
        all_sources AS (
            SELECT DISTINCT id, host, canonical_name
            FROM sources
            WHERE status IS NULL OR status = 'active'
            ORDER BY host
        ),
        discoveries AS (
            SELECT
                cl.id as discovery_uuid,
                cl.source as host,
                cl.source_id,
                cl.url,
                cl.status,
                cl.discovered_at,
                a.title as title,
                -- Article-level status (if extracted)
                a.id as article_id,
                a.status as article_status,
                a.wire_check_status,
                -- Decision metadata
                cl.error_message,
                cl.http_status,
                -- Telemetry for decision tracking
                CASE
                    -- Not article (verification)
                    WHEN cl.status = 'not_article' THEN
                        'verification: StorySniffer rejected (not article)'

                    -- Wire detection
                    WHEN a.wire_check_status = 'wire' THEN
                        'wire detection: wire service detected'

                    -- Opinion
                    WHEN a.status = 'opinion' THEN
                        'content analysis: opinion piece detected'

                    -- Obituary
                    WHEN a.status = 'obituary' THEN
                        'content analysis: obituary detected'

                    -- Successfully labeled
                    WHEN a.status = 'labeled' THEN
                        'ml classification: CIN labeled'

                    -- Extraction failed
                    WHEN cl.status = 'extraction_failed' THEN
                        COALESCE('extraction error: ' || cl.error_message, 'extraction failed')

                    -- Verification failed
                    WHEN cl.status = 'verification_failed' THEN
                        COALESCE('verification error: ' || cl.error_message, 'verification failed')

                    -- Still in pipeline
                    WHEN cl.status = 'discovered' THEN 'pending verification'
                    WHEN cl.status = 'article' THEN 'pending extraction'
                    WHEN a.status = 'extracted' THEN 'pending cleaning'
                    WHEN a.status = 'cleaned' THEN 'pending ml analysis'

                    ELSE 'status: ' || COALESCE(a.status, cl.status, 'unknown')
                END as status_decision,

                -- Final consolidated status for export
                CASE
                    WHEN a.status = 'labeled' AND a.wire_check_status IN ('local', 'complete') THEN 'labeled'
                    WHEN a.wire_check_status = 'wire' THEN 'wire'
                    WHEN a.status = 'opinion' THEN 'opinion'
                    WHEN a.status = 'obituary' THEN 'obituary'
                    WHEN cl.status = 'not_article' THEN 'not_article'
                    WHEN cl.status IN ('extraction_failed', 'verification_failed') THEN 'error'
                    ELSE COALESCE(a.status, cl.status, 'unknown')
                END as final_status

            FROM candidate_links cl
            LEFT JOIN articles a ON a.candidate_link_id = cl.id
            CROSS JOIN time_window tw
            WHERE cl.discovered_at >= tw.cutoff
            ORDER BY cl.source, cl.discovered_at DESC
        )
        SELECT
            s.host,
            s.canonical_name,
            COALESCE(d.discovery_uuid, '') as discovery_uuid,
            COALESCE(d.title, '') as title,
            COALESCE(d.final_status, 'no_discoveries') as status,
            COALESCE(d.url, '') as url,
            COALESCE(d.status_decision, 'no discoveries in time period') as status_decision,
            d.discovered_at
        FROM all_sources s
        LEFT JOIN discoveries d ON d.source_id = s.id
        ORDER BY s.host, d.discovered_at DESC NULLS LAST
    """)

    with db.get_session() as session:
        result = session.execute(query, {"hours": hours})
        rows = result.fetchall()

    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'Host',
            'Canonical Name',
            'Discovery UUID',
            'Title',
            'Status',
            'URL',
            'Status Decision',
            'Discovered At'
        ])

        # Data rows
        current_host = None
        host_count = 0
        url_count = 0

        for row in rows:
            host, canonical_name, discovery_uuid, title, status, url, decision, discovered_at = row

            # Track host changes for console output
            if host != current_host:
                if current_host is not None:
                    print(f"  {current_host}: {host_count} URLs")
                current_host = host
                host_count = 0

            if discovery_uuid:  # Only count actual discoveries
                host_count += 1
                url_count += 1

            # Format discovered_at
            discovered_str = discovered_at.strftime('%Y-%m-%d %H:%M:%S') if discovered_at else ''

            writer.writerow([
                host,
                canonical_name or host,
                discovery_uuid,
                title[:200] if title else '',  # Truncate long titles
                status,
                url,
                decision,
                discovered_str
            ])

        # Print final host count
        if current_host is not None:
            print(f"  {current_host}: {host_count} URLs")

    print(f"\n✓ Exported {url_count} URLs from {len(set(row[0] for row in rows))} sources")
    print(f"✓ Report saved to: {output_file}")

    # Generate summary statistics
    print("\n" + "="*60)
    print("STATUS SUMMARY")
    print("="*60)

    with db.get_session() as session:
        summary_query = text("""
            WITH time_window AS (
                SELECT NOW() - INTERVAL '1 hour' * :hours AS cutoff
            ),
            discoveries AS (
                SELECT
                    cl.source,
                    CASE
                        WHEN a.status = 'labeled' AND a.wire_check_status IN ('local', 'complete') THEN 'labeled'
                        WHEN a.wire_check_status = 'wire' THEN 'wire'
                        WHEN a.status = 'opinion' THEN 'opinion'
                        WHEN a.status = 'obituary' THEN 'obituary'
                        WHEN cl.status = 'not_article' THEN 'not_article'
                        WHEN cl.status IN ('extraction_failed', 'verification_failed') THEN 'error'
                        ELSE COALESCE(a.status, cl.status, 'unknown')
                    END as final_status
                FROM candidate_links cl
                LEFT JOIN articles a ON a.candidate_link_id = cl.id
                CROSS JOIN time_window tw
                WHERE cl.discovered_at >= tw.cutoff
            )
            SELECT final_status, COUNT(*) as count
            FROM discoveries
            GROUP BY final_status
            ORDER BY count DESC
        """)

        summary = session.execute(summary_query, {"hours": hours})

        for status, count in summary:
            print(f"{status:20} {count:6,} URLs")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export discovery status report")
    parser.add_argument("--hours", type=int, default=48, help="Hours to look back (default: 48)")
    parser.add_argument("--output", type=str, default="discovery_status_report.csv", help="Output CSV filename")

    args = parser.parse_args()

    export_discovery_status_report(hours=args.hours, output_file=args.output)
