#!/usr/bin/env python3
"""Slow gazetteer backfill script for large batches.

This script is specifically designed for backfilling gazetteer data across
many sources with conservative rate limiting to be respectful to OSM APIs.

Key differences from populate_gazetteer.py:
- Adds 5 seconds (+ jitter) delay between processing each source
- Provides progress tracking with estimated completion time
- Allows resuming from interruptions
- Includes batch size limits for controlled processing

Usage:
    python scripts/backfill_gazetteer_slow.py --batch-size 10
    python scripts/backfill_gazetteer_slow.py --batch-size 20 \\
        --dataset publinks-2025-09
    python scripts/backfill_gazetteer_slow.py \\
        --resume-from-source "source-uuid-here"
"""

import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from sqlalchemy import text

# Make sure `src` package is importable
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.models import create_database_engine, get_session  # noqa: E402


def estimate_completion_time(remaining_sources: int,
                             seconds_per_source: float) -> str:
    """Estimate completion time for remaining sources."""
    total_seconds = remaining_sources * seconds_per_source
    completion_time = datetime.now() + timedelta(seconds=total_seconds)
    return completion_time.strftime("%Y-%m-%d %H:%M:%S")


def get_sources_needing_gazetteer(session,
                                  dataset_slug: Optional[str] = None
                                  ) -> List[dict]:
    """Get list of sources that need gazetteer population."""

    # Base query to get sources without sufficient gazetteer data
    query = """
    SELECT DISTINCT
        cl.source_id,
        cl.source_name,
        cl.source_city,
        cl.source_county,
        cl.zip_code,
        cl.address
    FROM candidate_links cl
    WHERE cl.source_id IS NOT NULL
    AND cl.source_id NOT IN (
        SELECT DISTINCT g.source_id
        FROM gazetteer g
        WHERE g.source_id IS NOT NULL
        GROUP BY g.source_id
        HAVING COUNT(DISTINCT g.category) >= 3
    )
    ORDER BY cl.source_name
    """

    # Add dataset filter if specified
    if dataset_slug:
        query_with_dataset = """
        SELECT DISTINCT
            cl.source_id,
            cl.source_name,
            cl.source_city,
            cl.source_county,
            cl.zip_code,
            cl.address
        FROM candidate_links cl
        JOIN dataset_sources ds ON cl.source_id = ds.source_id
        JOIN datasets d ON ds.dataset_id = d.id
        WHERE cl.source_id IS NOT NULL
        AND d.slug = :dataset_slug
        AND cl.source_id NOT IN (
            SELECT DISTINCT g.source_id
            FROM gazetteer g
            WHERE g.source_id IS NOT NULL
            GROUP BY g.source_id
            HAVING COUNT(DISTINCT g.category) >= 3
        )
        ORDER BY cl.source_name
        """
        params = {"dataset_slug": dataset_slug}
        result = session.execute(text(query_with_dataset), params).fetchall()
    else:
        result = session.execute(text(query)).fetchall()

    return [dict(row._mapping) for row in result]


def process_source_with_delay(source: dict, session,
                              dry_run: bool = False) -> bool:
    """Process a single source with gazetteer population."""
    source_id = source['source_id']
    source_name = source['source_name']
    
    print(f"  Processing: {source_name} ({source_id})")
    
    if dry_run:
        print("    DRY-RUN: Would populate gazetteer data")
        return True
    
    try:
        # Import the populate_gazetteer main function
        scripts_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(scripts_dir))
        
        from populate_gazetteer import main as populate_main
        
        # Get database URL
        engine = session.get_bind()
        database_url = str(engine.url)
        
        # Call populate_gazetteer for this specific source/publisher
        populate_main(
            database_url=database_url,
            dataset_slug=None,  # Process specific publisher, not dataset
            address=None,
            radius_miles=None,
            dry_run=False,
            publisher=source_id  # Use publisher UUID mode
        )
        
        print(f"    ✅ Successfully processed {source_name}")
        return True
        
    except Exception as e:
        print(f"    ❌ Error processing {source_name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Slow gazetteer backfill with conservative rate limiting"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of sources to process in this batch (default: 10)"
    )
    parser.add_argument(
        "--dataset",
        help="Dataset slug to process (optional, processes all sources)"
    )
    parser.add_argument(
        "--resume-from-source",
        help="Source UUID to resume from (skips sources until this one)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without making changes"
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=5.0,
        help="Minimum delay between sources in seconds (default: 5.0)"
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=8.0,
        help="Maximum delay between sources in seconds (default: 8.0)"
    )
    
    args = parser.parse_args()
    
    # Database connection
    engine = create_database_engine()
    session = get_session(engine)
    
    print("🐌 SLOW GAZETTEER BACKFILL")
    print("=" * 50)
    print(f"Batch size: {args.batch_size}")
    print(f"Dataset filter: {args.dataset or 'ALL'}")
    print(f"Delay per source: {args.min_delay}-{args.max_delay} seconds")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()
    
    # Get sources needing gazetteer data
    sources_needing_gazetteer = get_sources_needing_gazetteer(
        session, args.dataset)

    print(f"📊 Found {len(sources_needing_gazetteer)} sources "
          f"needing gazetteer data")
    
    if not sources_needing_gazetteer:
        print("✅ All sources already have sufficient gazetteer data!")
        return
    
    # Handle resume functionality
    start_index = 0
    if args.resume_from_source:
        for i, source in enumerate(sources_needing_gazetteer):
            if source['source_id'] == args.resume_from_source:
                start_index = i
                print(f"📍 Resuming from source: {source['source_name']} "
                      f"(index {i})")
                break
        else:
            print(f"⚠️  Resume source UUID not found: "
                  f"{args.resume_from_source}")
            return

    # Process batch
    end_index = start_index + args.batch_size
    batch_sources = sources_needing_gazetteer[start_index:end_index]
    remaining_after_batch = (len(sources_needing_gazetteer) - start_index -
                             len(batch_sources))

    print(f"🎯 Processing batch of {len(batch_sources)} sources")
    print(f"📈 {remaining_after_batch} sources will remain after this batch")
    
    # Estimate time
    avg_delay = (args.min_delay + args.max_delay) / 2
    estimated_seconds_per_source = avg_delay + 10  # Include processing time
    estimated_batch_time = len(batch_sources) * estimated_seconds_per_source
    completion_time = estimate_completion_time(
        len(batch_sources), estimated_seconds_per_source)

    print(f"⏱️  Estimated batch completion: {completion_time}")
    print(f"⏱️  Estimated batch duration: "
          f"{estimated_batch_time/60:.1f} minutes")
    print()
    
    if not args.dry_run:
        response = input("Continue with processing? (y/N): ")
        if response.lower() != 'y':
            print("Aborted by user")
            return
    
    # Process sources
    start_time = datetime.now()
    processed_count = 0
    failed_count = 0
    
    for i, source in enumerate(batch_sources, 1):
        print(f"\n[{i}/{len(batch_sources)}] Processing source...")
        
        # Process the source
        success = process_source_with_delay(source, session, args.dry_run)
        
        if success:
            processed_count += 1
        else:
            failed_count += 1
        
        # Progress update
        remaining_in_batch = len(batch_sources) - i
        if remaining_in_batch > 0:
            estimated_remaining_time = (
                remaining_in_batch * estimated_seconds_per_source)
            estimated_completion = (
                datetime.now() + timedelta(seconds=estimated_remaining_time))
            
            print(f"    📊 Progress: {i}/{len(batch_sources)} sources")
            print(f"    📊 Success: {processed_count}, Failed: {failed_count}")
            print(f"    ⏰ Estimated completion: "
                  f"{estimated_completion.strftime('%H:%M:%S')}")
        
        # Inter-source delay (except for last source)
        if i < len(batch_sources):
            delay = (args.min_delay +
                     random.random() * (args.max_delay - args.min_delay))
            print(f"    😴 Waiting {delay:.1f} seconds before next source...")
            
            if not args.dry_run:
                time.sleep(delay)
    
    # Final summary
    elapsed_time = datetime.now() - start_time
    print("\n🎉 BATCH COMPLETE")
    print("=" * 50)
    print(f"Sources processed: {processed_count}")
    print(f"Sources failed: {failed_count}")
    print(f"Batch duration: {elapsed_time}")
    print(f"Remaining sources: {remaining_after_batch}")
    
    if remaining_after_batch > 0:
        print("\n📋 To continue with next batch:")
        print(f"python scripts/backfill_gazetteer_slow.py "
              f"--batch-size {args.batch_size}")
        if args.dataset:
            print(f"    --dataset {args.dataset}")
        if len(batch_sources) > 0:
            last_processed = batch_sources[-1]
            print(f"    --resume-from-source {last_processed['source_id']}")
    
    session.close()


if __name__ == "__main__":
    main()
