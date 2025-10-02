#!/usr/bin/env python3
"""
Migration script to backfill NULL source_host_id values in candidate_links table.

This script fixes the data integrity issue where all existing candidate_links
records have NULL source_host_id values, which breaks the discovery effectiveness
tracking system.

The script matches existing candidate_links to sources using:
1. URL hostname matching against sources.host
2. source_name matching against sources.canonical_name
3. Legacy source field matching

Run from project root: python scripts/migrations/backfill_source_host_id.py
"""

import logging
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_hostname(url: str) -> str:
    """Extract hostname from URL, handling edge cases."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        return hostname.lower() if hostname else ""
    except Exception:
        return ""


def backfill_source_host_ids(db_path: str = "data/mizzou.db", dry_run: bool = True):
    """
    Backfill NULL source_host_id values in candidate_links.
    
    Args:
        db_path: Path to SQLite database
        dry_run: If True, only show what would be changed without making changes
    """
    logger.info(f"Starting source_host_id backfill migration (dry_run={dry_run})")

    # Use direct sqlite3 connection for better control
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    cursor = conn.cursor()

    try:
        # Get count of records that need fixing
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM candidate_links 
            WHERE source_host_id IS NULL
        """)
        null_count = cursor.fetchone()['count']
        logger.info(f"Found {null_count} candidate_links with NULL source_host_id")

        if null_count == 0:
            logger.info("No records need updating")
            return

        # Get all sources for matching
        cursor.execute("""
            SELECT id, host, host_norm, canonical_name, city
            FROM sources
        """)
        sources = cursor.fetchall()
        logger.info(f"Loaded {len(sources)} sources for matching")

        # Create lookup dictionaries for fast matching
        host_to_source_id: dict[str, str] = {}
        name_to_source_id: dict[str, str] = {}

        for source in sources:
            # Map by host (normalized)
            if source['host']:
                host_to_source_id[source['host'].lower()] = source['id']
            if source['host_norm']:
                host_to_source_id[source['host_norm']] = source['id']

            # Map by canonical name (normalized)
            if source['canonical_name']:
                name_to_source_id[source['canonical_name'].lower()] = source['id']

        # Get candidate_links that need updating
        cursor.execute("""
            SELECT id, url, source, source_name
            FROM candidate_links 
            WHERE source_host_id IS NULL
            ORDER BY id
        """)
        candidate_links = cursor.fetchall()

        # Track matching statistics
        stats = {
            'total_processed': 0,
            'matched_by_url_host': 0,
            'matched_by_source_name': 0,
            'matched_by_source_field': 0,
            'no_match_found': 0,
            'would_update': 0
        }

        updates_to_make = []

        for link in candidate_links:
            stats['total_processed'] += 1
            source_id = None
            match_method = None

            # Method 1: Match by URL hostname
            if link['url'] and not source_id:
                hostname = extract_hostname(link['url'])
                if hostname and hostname in host_to_source_id:
                    source_id = host_to_source_id[hostname]
                    match_method = 'url_host'
                    stats['matched_by_url_host'] += 1

            # Method 2: Match by source_name field
            if link['source_name'] and not source_id:
                name_key = link['source_name'].lower()
                if name_key in name_to_source_id:
                    source_id = name_to_source_id[name_key]
                    match_method = 'source_name'
                    stats['matched_by_source_name'] += 1

            # Method 3: Match by legacy source field
            if link['source'] and not source_id:
                source_key = link['source'].lower()
                if source_key in name_to_source_id:
                    source_id = name_to_source_id[source_key]
                    match_method = 'source_field'
                    stats['matched_by_source_field'] += 1

            if source_id:
                updates_to_make.append((source_id, link['id']))
                stats['would_update'] += 1

                if stats['total_processed'] <= 5:  # Log first few matches
                    logger.info(
                        f"Match #{stats['total_processed']}: {link['url']} -> "
                        f"source_id {source_id} (via {match_method})"
                    )
            else:
                stats['no_match_found'] += 1
                if stats['no_match_found'] <= 3:  # Log first few unmatched
                    logger.warning(
                        f"No match for: URL={link['url']}, "
                        f"source={link['source']}, source_name={link['source_name']}"
                    )

        # Show statistics
        logger.info("Matching statistics:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")

        if dry_run:
            logger.info(f"DRY RUN: Would update {len(updates_to_make)} records")
            logger.info("Re-run with dry_run=False to apply changes")
        else:
            # Perform the updates
            logger.info(f"Applying updates to {len(updates_to_make)} records...")

            cursor.executemany("""
                UPDATE candidate_links 
                SET source_host_id = ? 
                WHERE id = ?
            """, updates_to_make)

            conn.commit()
            logger.info(f"Successfully updated {len(updates_to_make)} candidate_links")

            # Verify the update
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM candidate_links 
                WHERE source_host_id IS NULL
            """)
            remaining_nulls = cursor.fetchone()['count']
            logger.info(f"Remaining NULL source_host_id records: {remaining_nulls}")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        if not dry_run:
            conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill NULL source_host_id values")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be changed without making changes (default: True)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the changes (sets dry_run=False)"
    )
    parser.add_argument(
        "--db-path",
        default="data/mizzou.db",
        help="Path to SQLite database (default: data/mizzou.db)"
    )

    args = parser.parse_args()

    # If --apply is specified, turn off dry_run
    dry_run = not args.apply

    if dry_run:
        print("Running in DRY RUN mode. Use --apply to make actual changes.")
    else:
        print("APPLYING CHANGES to database!")

    backfill_source_host_ids(args.db_path, dry_run=dry_run)
