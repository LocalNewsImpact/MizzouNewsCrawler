#!/usr/bin/env python3
"""
Backfill wire filtering for existing candidate_links.

Applies the same wire URL pattern detection used in verification
to candidates that were discovered before the current detector version.
Marks matching candidates as 'wire' to prevent unnecessary extraction.
"""
import argparse
import re
import time
from sqlalchemy import text
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector


def backfill_wire_filter(dry_run: bool = True, limit: int | None = None):
    """
    Backfill wire detection on existing candidate_links.

    Args:
        dry_run: If True, show what would be updated without making changes
        limit: Max number of candidates to process (None = all)
    """
    print("=" * 80)
    print("BACKFILL WIRE FILTERING")
    print("=" * 80)
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    print(f"Limit: {limit if limit else 'ALL'}")
    print()

    db = DatabaseManager()

    with db.get_session() as session:
        # Load wire URL patterns once (same as verification does)
        detector = ContentTypeDetector(session=session)
        wire_patterns = detector._get_wire_service_patterns(pattern_type="url")

        print(f"Loaded {len(wire_patterns)} wire URL patterns from database")
        print()

        # Get candidates with article/verified status
        # Note: Some may already be extracted, but we'll mark wire ones anyway
        print("Querying candidate_links...")
        query = text("""
            SELECT id, url, source
            FROM candidate_links
            WHERE status IN ('article', 'verified')
            ORDER BY discovered_at DESC
        """ + (f" LIMIT {limit}" if limit else ""))

        candidates = session.execute(query).fetchall()
        total = len(candidates)

        print(f"Found {total} candidates to check")
        print()

        wire_count = 0
        not_wire = 0
        updated = 0

        start_time = time.time()

        for idx, (cid, url, source) in enumerate(candidates, 1):
            if idx % 100 == 0:
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                remaining = (total - idx) / rate if rate > 0 else 0
                print(
                    f"Progress: {idx}/{total} ({idx*100//total}%) "
                    f"- {rate:.1f} URLs/sec - ETA: {remaining:.0f}s"
                )

            # Check against wire patterns (same logic as verification)
            is_wire = False
            matched_service = None

            for pattern, service_name, case_sensitive in wire_patterns:
                flags = 0 if case_sensitive else re.IGNORECASE
                if re.search(pattern, url, flags):
                    is_wire = True
                    matched_service = service_name
                    break

            if is_wire:
                wire_count += 1

                if wire_count <= 10 or (dry_run and wire_count <= 50):
                    print(f"🔴 WIRE [{wire_count}]: {matched_service}")
                    print(f"   ID: {cid}")
                    print(f"   Source: {source}")
                    print(f"   URL: {url[:70]}...")

                if not dry_run:
                    update_query = text(
                        "UPDATE candidate_links SET status = 'wire' WHERE id = :cid"
                    )
                    session.execute(update_query, {"cid": cid})
                    session.commit()
                    updated += 1
                    if wire_count <= 10:
                        print("   ✅ Updated")
                elif wire_count <= 10 or (dry_run and wire_count <= 50):
                    print("   🔵 Would update (dry-run)")

                if wire_count <= 10 or (dry_run and wire_count <= 50):
                    print()
            else:
                not_wire += 1

        # Summary
        elapsed = time.time() - start_time
        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total processed:  {total}")
        print(f"Wire detected:    {wire_count} ({wire_count*100//total if total else 0}%)")
        print(f"Not wire:         {not_wire} ({not_wire*100//total if total else 0}%)")
        print(f"Time elapsed:     {elapsed:.1f}s")
        print(f"Processing rate:  {total/elapsed if elapsed > 0 else 0:.1f} URLs/sec")

        if dry_run:
            print(f"Would update:     {wire_count} candidates (dry-run)")
        else:
            print(f"Actually updated: {updated} candidates")

        print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill wire filtering for existing candidates"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--limit", type=int, help="Limit number of candidates to process"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all candidates (no limit)",
    )

    args = parser.parse_args()

    if not args.all and args.limit is None:
        parser.error("Must specify --limit N or --all")

    limit = None if args.all else args.limit

    backfill_wire_filter(dry_run=args.dry_run, limit=limit)


if __name__ == "__main__":
    main()
