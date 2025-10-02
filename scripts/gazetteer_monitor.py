#!/usr/bin/env python3
"""
Gazetteer Monitoring and Backfill Script

This script monitors sources/publishers for missing gazetteer data and
automatically triggers background population processes to fill gaps.

Usage:
    python scripts/gazetteer_monitor.py --check
    python scripts/gazetteer_monitor.py --backfill [--limit N] [--dry-run]
    python scripts/gazetteer_monitor.py --monitor [--interval SECONDS]

Features:
- Check status of gazetteer coverage across all sources
- Trigger background backfill for unpopulated sources
- Continuous monitoring mode for automated operations
- Rate limiting and batch processing for OSM API conservation
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from src.models.database import DatabaseManager
from src.utils.process_tracker import ProcessContext, ProcessTracker

logger = logging.getLogger(__name__)


class GazetteerMonitor:
    """Monitor and manage gazetteer population across all sources."""

    def __init__(self, database_url: str = "sqlite:///data/mizzou.db"):
        self.db = DatabaseManager(database_url)
        self.tracker = ProcessTracker()

    def get_gazetteer_status(self) -> tuple[int, int, list[dict]]:
        """Get current gazetteer population status.

        Returns:
            Tuple of (total_sources, populated_sources, unpopulated_sources_list)
        """
        with self.db.engine.connect() as conn:
            # Total sources
            result = conn.execute(text("SELECT COUNT(*) as count FROM sources"))
            total_sources = result.fetchone().count

            # Sources with gazetteer entries
            result = conn.execute(
                text(
                    """
                SELECT COUNT(DISTINCT source_id) as count 
                FROM gazetteer
            """
                )
            )
            populated_sources = result.fetchone().count

            # Get unpopulated sources
            result = conn.execute(
                text(
                    """
                SELECT s.id, s.canonical_name, s.city, s.county, s.host
                FROM sources s
                LEFT JOIN gazetteer g ON s.id = g.source_id
                WHERE g.source_id IS NULL
                ORDER BY s.canonical_name
            """
                )
            )

            unpopulated = []
            for row in result:
                unpopulated.append(
                    {
                        "id": row.id,
                        "name": row.canonical_name,
                        "city": row.city,
                        "county": row.county,
                        "host": row.host,
                    }
                )

            return total_sources, populated_sources, unpopulated

    def check_status(self) -> None:
        """Check and report gazetteer population status."""
        logger.info("Checking gazetteer population status...")

        total, populated, unpopulated = self.get_gazetteer_status()

        print("Gazetteer Population Status:")
        print(f"  Total sources: {total}")
        print(f"  Populated sources: {populated}")
        print(f"  Unpopulated sources: {len(unpopulated)}")
        print(f"  Coverage: {populated/total*100:.1f}%")

        if unpopulated:
            print("\nUnpopulated sources (showing first 10):")
            for source in unpopulated[:10]:
                location = (
                    f"{source['city']}, {source['county']}"
                    if source["county"]
                    else source["city"]
                )
                print(f"  {source['id'][:8]}... - {source['name']} ({location})")

            if len(unpopulated) > 10:
                print(f"  ... and {len(unpopulated) - 10} more")
        else:
            print("\n✅ All sources have gazetteer data!")

    def trigger_backfill(
        self, limit: int = None, dry_run: bool = False, batch_size: int = 20
    ) -> None:
        """Trigger background gazetteer population for unpopulated sources.

        Args:
            limit: Maximum number of sources to process (for rate limiting)
            dry_run: If True, only show what would be processed
            batch_size: Number of sources to process in each batch (default: 20)
        """
        logger.info("Starting gazetteer backfill process...")

        total, populated, unpopulated = self.get_gazetteer_status()

        if not unpopulated:
            print("✅ No backfill needed - all sources have gazetteer data")
            return

        sources_to_process = unpopulated[:limit] if limit else unpopulated

        # Calculate batches
        total_sources = len(sources_to_process)
        num_batches = (total_sources + batch_size - 1) // batch_size  # Ceiling division

        if dry_run:
            print(
                f"DRY RUN: Would process {total_sources} sources in {num_batches} batches of {batch_size}:"
            )
            for i in range(0, total_sources, batch_size):
                batch = sources_to_process[i : i + batch_size]
                batch_num = (i // batch_size) + 1
                print(f"\n  Batch {batch_num}/{num_batches} ({len(batch)} sources):")
                for source in batch:
                    location = (
                        f"{source['city']}, {source['county']}"
                        if source["county"]
                        else source["city"]
                    )
                    print(f"    {source['id'][:8]}... - {source['name']} ({location})")
            return

        print(
            f"Starting backfill for {total_sources} sources in {num_batches} batches of {batch_size}..."
        )

        # Process in batches
        overall_failed_sources = []

        for batch_num in range(num_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, total_sources)
            batch = sources_to_process[start_idx:end_idx]

            print(
                f"\n🔄 Processing batch {batch_num + 1}/{num_batches} ({len(batch)} sources)..."
            )

            # Track each batch as a separate process
            with ProcessContext(
                process_type="gazetteer_backfill_batch",
                command=f"gazetteer_monitor --backfill --batch {batch_num + 1}/{num_batches}",
                metadata={
                    "batch_number": batch_num + 1,
                    "total_batches": num_batches,
                    "batch_size": len(batch),
                    "total_sources_in_backfill": total_sources,
                    "total_unpopulated": len(unpopulated),
                    "auto_triggered": True,
                    "trigger_time": datetime.utcnow().isoformat(),
                },
            ) as process:

                batch_failed_sources = []

                for i, source in enumerate(batch, 1):
                    source_num_overall = start_idx + i
                    logger.info(
                        f"Processing source {source_num_overall}/{total_sources} "
                        f"(batch {batch_num + 1}/{num_batches}, item {i}/{len(batch)}): {source['name']}"
                    )

                    try:
                        # Trigger gazetteer population for this specific publisher
                        cmd = [
                            sys.executable,
                            "-m",
                            "src.cli.main",
                            "populate-gazetteer",
                            "--publisher",
                            source["id"],
                        ]

                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=300,  # 5 minute timeout per source
                        )

                        if result.returncode == 0:
                            logger.info(f"✅ Successfully processed {source['name']}")
                        else:
                            logger.error(
                                f"❌ Failed to process {source['name']}: {result.stderr}"
                            )
                            batch_failed_sources.append(source)

                        # Update progress for this batch
                        self.tracker.update_progress(
                            process.id,
                            current=i,
                            total=len(batch),
                            message=f"Batch {batch_num + 1}/{num_batches}: Processed {source['name']}",
                        )

                        # Rate limiting - wait between requests to be respectful to OSM API
                        if i < len(batch):  # Don't wait after the last one in batch
                            time.sleep(2)  # 2 second delay between sources

                    except subprocess.TimeoutExpired:
                        logger.error(f"⏰ Timeout processing {source['name']}")
                        batch_failed_sources.append(source)
                    except Exception as e:
                        logger.error(f"💥 Error processing {source['name']}: {e}")
                        batch_failed_sources.append(source)

                # Record batch results
                if batch_failed_sources:
                    failed_count = len(batch_failed_sources)
                    success_count = len(batch) - failed_count
                    logger.warning(
                        f"Batch {batch_num + 1}/{num_batches} completed: "
                        f"{success_count} succeeded, {failed_count} failed"
                    )
                    overall_failed_sources.extend(batch_failed_sources)
                else:
                    logger.info(
                        f"✅ Batch {batch_num + 1}/{num_batches} completed successfully: "
                        f"all {len(batch)} sources processed"
                    )

            # Brief pause between batches (optional, can be removed if not needed)
            if batch_num < num_batches - 1:  # Don't wait after the last batch
                print("⏳ Waiting 15 seconds before starting next batch...")
                time.sleep(15)

        # Final summary
        total_processed = total_sources - len(overall_failed_sources)
        print("\n📊 Backfill Summary:")
        print(f"  Total sources: {total_sources}")
        print(f"  Batches processed: {num_batches}")
        print(f"  Successfully processed: {total_processed}")
        print(f"  Failed: {len(overall_failed_sources)}")

        if overall_failed_sources:
            print("\n❌ Failed sources:")
            for source in overall_failed_sources:
                location = (
                    f"{source['city']}, {source['county']}"
                    if source["county"]
                    else source["city"]
                )
                print(f"  {source['id'][:8]}... - {source['name']} ({location})")

        logger.info(
            f"Backfill process completed: {total_processed}/{total_sources} sources successful"
        )

    def monitor_continuous(self, interval: int = 3600) -> None:
        """Run continuous monitoring, triggering backfill when needed.

        Args:
            interval: Check interval in seconds (default: 1 hour)
        """
        logger.info(
            f"Starting continuous monitoring (checking every {interval} seconds)..."
        )

        while True:
            try:
                total, populated, unpopulated = self.get_gazetteer_status()

                logger.info(
                    f"Monitor check: {populated}/{total} sources populated ({len(unpopulated)} missing)"
                )

                if unpopulated:
                    # Trigger backfill for a small batch to avoid overwhelming OSM API
                    batch_size = min(5, len(unpopulated))  # Process max 5 at a time
                    logger.info(f"Triggering backfill for {batch_size} sources...")

                    self.trigger_backfill(limit=batch_size, dry_run=False)
                else:
                    logger.info("✅ All sources populated - monitoring...")

                time.sleep(interval)

            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(60)  # Wait 1 minute before retrying


def main():
    """Main entry point for the gazetteer monitor."""
    parser = argparse.ArgumentParser(
        description="Monitor and manage gazetteer population",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Check current status
    python scripts/gazetteer_monitor.py --check
    
    # Backfill up to 10 sources
    python scripts/gazetteer_monitor.py --backfill --limit 10
    
    # Dry run to see what would be processed
    python scripts/gazetteer_monitor.py --backfill --dry-run
    
    # Continuous monitoring (check every 30 minutes)
    python scripts/gazetteer_monitor.py --monitor --interval 1800
        """,
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level",
    )

    # Action arguments (mutually exclusive)
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--check", action="store_true", help="Check gazetteer population status"
    )
    action_group.add_argument(
        "--backfill",
        action="store_true",
        help="Trigger backfill for unpopulated sources",
    )
    action_group.add_argument(
        "--monitor", action="store_true", help="Run continuous monitoring"
    )

    # Backfill options
    parser.add_argument(
        "--limit", type=int, help="Maximum sources to process in backfill"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of sources to process in each batch (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without executing",
    )

    # Monitor options
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="Monitoring interval in seconds (default: 1 hour)",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create monitor instance
    monitor = GazetteerMonitor()

    try:
        if args.check:
            monitor.check_status()
        elif args.backfill:
            monitor.trigger_backfill(
                limit=args.limit,
                dry_run=args.dry_run,
                batch_size=getattr(args, "batch_size", 20),
            )
        elif args.monitor:
            monitor.monitor_continuous(interval=args.interval)
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
