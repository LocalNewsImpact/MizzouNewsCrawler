#!/usr/bin/env python3
"""
News crawler CLI script for discovering and fetching articles.

Usage:
    python scripts/crawl.py --sources sources/mizzou_sites.json --output-db data/mizzou.db --job-id crawl-001
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crawler import NewsCrawler
from models.database import (
    DatabaseManager,
    create_job_record,
    export_to_parquet,
    finish_job_record,
    upsert_candidate_link,
)
from utils.telemetry import OperationMetrics, OperationType, OperationTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/crawl.log")],
)
logger = logging.getLogger(__name__)


def load_sources(sources_file: str) -> list[dict[str, any]]:
    """Load source site configurations from JSON file."""
    try:
        with open(sources_file) as f:
            sources = json.load(f)

        logger.info(f"Loaded {len(sources)} sources from {sources_file}")
        return sources
    except Exception as e:
        logger.error(f"Error loading sources: {e}")
        return []


def crawl_site(
    crawler: NewsCrawler,
    site_config: dict[str, any],
    db_manager: DatabaseManager,
    job_id: str,
) -> dict[str, int]:
    """Crawl a single site and return metrics."""
    site_name = site_config.get("name", "unknown")
    seed_urls = site_config.get("seed_urls", [])
    site_rules = site_config.get("rules", {})

    metrics = {
        "links_discovered": 0,
        "links_filtered": 0,
        "links_saved": 0,
        "errors": 0,
    }

    logger.info(f"Starting crawl of {site_name} with {len(seed_urls)} seed URLs")

    all_internal_links = set()

    # Discover links from all seed URLs
    for seed_url in seed_urls:
        try:
            internal_links, external_links = crawler.discover_links(seed_url)
            all_internal_links.update(internal_links)
            metrics["links_discovered"] += len(internal_links)

        except Exception as e:
            logger.error(f"Error crawling {seed_url}: {e}")
            metrics["errors"] += 1

    # Filter for article URLs
    article_urls = crawler.filter_article_urls(all_internal_links, site_rules)
    metrics["links_filtered"] = len(article_urls)

    # Save candidate links to database
    for url in article_urls:
        try:
            upsert_candidate_link(
                db_manager.session,
                url=url,
                source=site_name,
                discovered_by=job_id,
                crawl_depth=1,
                status="new",
            )
            metrics["links_saved"] += 1

        except Exception as e:
            logger.error(f"Error saving candidate link {url}: {e}")
            metrics["errors"] += 1

    logger.info(f"Completed {site_name}: {metrics}")
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Crawl news sites for article URLs")
    parser.add_argument(
        "--sources", required=True, help="JSON file with site configurations"
    )
    parser.add_argument(
        "--output-db", default="data/mizzou.db", help="SQLite database path"
    )
    parser.add_argument(
        "--job-id",
        default=f"crawl-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        help="Unique job identifier",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Delay between requests (seconds)"
    )
    parser.add_argument(
        "--timeout", type=int, default=20, help="Request timeout (seconds)"
    )
    parser.add_argument(
        "--export-snapshot",
        action="store_true",
        help="Export results to Parquet snapshot",
    )
    parser.add_argument(
        "--artifacts-dir", default="artifacts", help="Directory for output artifacts"
    )

    args = parser.parse_args()

    # Ensure required directories exist
    Path(args.output_db).parent.mkdir(parents=True, exist_ok=True)
    Path(args.artifacts_dir).mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    # Load source configurations
    sources = load_sources(args.sources)
    if not sources:
        logger.error("No sources loaded, exiting")
        return 1

    # Initialize crawler, database, and telemetry tracker
    crawler = NewsCrawler(delay=args.delay, timeout=args.timeout)
    tracker = OperationTracker(database_url=f"sqlite:///{args.output_db}")

    total_metrics = {
        "sites_processed": 0,
        "total_links_discovered": 0,
        "total_links_saved": 0,
        "total_errors": 0,
    }

    try:
        with DatabaseManager(f"sqlite:///{args.output_db}") as db_manager:
            # Create job record
            job = create_job_record(
                db_manager.session,
                job_type="crawler",
                job_name=f"crawl-sites-{len(sources)}",
                params={
                    "sources_file": args.sources,
                    "num_sources": len(sources),
                    "delay": args.delay,
                    "timeout": args.timeout,
                },
            )

            logger.info(f"Started crawl job: {job.id}")

            # Track the crawl operation with telemetry
            with tracker.track_operation(
                OperationType.CRAWL_DISCOVERY,
                job_id=args.job_id,
                sources_file=args.sources,
                num_sources=len(sources),
            ) as operation:
                # Update progress metrics
                progress_metrics = OperationMetrics(
                    total_items=len(sources),
                    processed_items=0,
                )
                operation.update_progress(progress_metrics)

                # Process each site
                for idx, site_config in enumerate(sources, start=1):
                    try:
                        site_metrics = crawl_site(crawler, site_config, db_manager, job.id)

                        total_metrics["sites_processed"] += 1
                        total_metrics["total_links_discovered"] += site_metrics[
                            "links_discovered"
                        ]
                        total_metrics["total_links_saved"] += site_metrics["links_saved"]
                        total_metrics["total_errors"] += site_metrics["errors"]

                    except Exception as e:
                        logger.error(
                            f"Error processing site {site_config.get('name', 'unknown')}: {e}"
                        )
                        total_metrics["total_errors"] += 1
                    
                    # Update progress after each site
                    progress_metrics.processed_items = idx
                    operation.update_progress(progress_metrics)

            # Finish job record
            finish_job_record(
                db_manager.session,
                job.id,
                exit_status=(
                    "success"
                    if total_metrics["total_errors"] == 0
                    else "partial_success"
                ),
                metrics={
                    "records_created": total_metrics["total_links_saved"],
                    "errors_count": total_metrics["total_errors"],
                },
            )

            # Export snapshot if requested
            if args.export_snapshot:
                snapshot_path = (
                    Path(args.artifacts_dir) / f"candidate_links_{args.job_id}.parquet"
                )
                export_to_parquet(
                    db_manager.engine,
                    "candidate_links",
                    str(snapshot_path),
                    filters={"discovered_by": job.id},
                )
                logger.info(f"Exported snapshot to {snapshot_path}")

            logger.info(f"Crawl completed: {total_metrics}")

    except Exception as e:
        logger.error(f"Fatal error during crawl: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
