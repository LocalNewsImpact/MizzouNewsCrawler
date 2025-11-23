#!/usr/bin/env python3
"""Populate local_broadcaster_callsigns table from sources in the dataset.

This script analyzes sources in the database to identify local broadcaster
callsigns (TV/radio stations) and populates the local_broadcaster_callsigns
table to prevent false wire detection.
"""

import argparse
import re

from src.models import LocalBroadcasterCallsign, Source
from src.models.database import DatabaseManager


def extract_callsign_from_source(source_name: str, host: str) -> str | None:
    """Extract FCC callsign from source name or host.
    
    FCC callsigns follow pattern: K/W + 3-4 letters
    Examples: KMIZ, KOMU, KRCG, WGBH, WTTW
    """
    # Try source name first
    if source_name:
        match = re.search(r'\b([KW][A-Z]{3,4})\b', source_name, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    # Try host
    if host:
        match = re.search(r'\b([KW][A-Z]{3,4})\b', host, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    return None


def identify_local_broadcasters(
    session, dataset: str = "missouri", dry_run: bool = True
) -> list[dict]:
    """Identify local broadcasters from sources table.
    
    Args:
        session: Database session
        dataset: Dataset identifier
        dry_run: If True, don't write to database
        
    Returns:
        List of identified broadcaster dictionaries
    """
    # Query sources that might be broadcasters
    sources = session.query(Source).filter(
        Source.status == "active"
    ).all()
    
    identified = []
    
    for source in sources:
        callsign = extract_callsign_from_source(source.canonical_name, source.host)
        
        if not callsign:
            continue
        
        # Determine if this is likely a local broadcaster
        # Local indicators: host contains callsign, has city/county metadata
        is_local = False
        market_name = None
        
        if callsign.lower() in source.host.lower():
            is_local = True
        
        if source.city or source.county:
            is_local = True
            if source.city and source.county:
                market_name = f"{source.city}, {source.county} County"
            elif source.city:
                market_name = source.city
            elif source.county:
                market_name = f"{source.county} County"
        
        if is_local:
            identified.append({
                "callsign": callsign,
                "source_id": source.id,
                "dataset": dataset,
                "market_name": market_name,
                "station_type": "TV",  # Assume TV unless otherwise known
                "host": source.host,
                "canonical_name": source.canonical_name,
            })
    
    return identified


def populate_callsigns(
    identified: list[dict],
    session,
    dry_run: bool = True,
) -> None:
    """Populate local_broadcaster_callsigns table.
    
    Args:
        identified: List of broadcaster dictionaries
        session: Database session
        dry_run: If True, don't write to database
    """
    print(f"\nFound {len(identified)} local broadcasters:")
    print("=" * 80)
    
    for item in identified:
        print(f"Callsign: {item['callsign']}")
        print(f"  Host: {item['host']}")
        print(f"  Name: {item['canonical_name']}")
        print(f"  Market: {item['market_name']}")
        print(f"  Dataset: {item['dataset']}")
        print()
        
        if not dry_run:
            # Check if already exists
            existing = session.query(LocalBroadcasterCallsign).filter(
                LocalBroadcasterCallsign.callsign == item["callsign"],
                LocalBroadcasterCallsign.dataset == item["dataset"],
            ).first()
            
            if existing:
                print("  ⚠️  Already exists, skipping")
                continue
            
            # Insert new record
            callsign_record = LocalBroadcasterCallsign(
                callsign=item["callsign"],
                source_id=item["source_id"],
                dataset=item["dataset"],
                market_name=item["market_name"],
                station_type=item["station_type"],
                notes=f"Auto-populated from source: {item['canonical_name']}",
            )
            session.add(callsign_record)
            print("  ✅ Inserted")
    
    if not dry_run:
        session.commit()
        print(f"\n✅ Committed {len(identified)} records to database")
    else:
        print("\n⚠️  DRY RUN - No changes made to database")
        print(f"   Run with --apply to insert {len(identified)} records")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Populate local broadcaster callsigns table"
    )
    parser.add_argument(
        "--dataset",
        default="missouri",
        help="Dataset identifier (default: missouri)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to database (default is dry run)",
    )
    args = parser.parse_args()
    
    dry_run = not args.apply
    
    print("Local Broadcaster Callsign Population")
    print("=" * 80)
    print(f"Dataset: {args.dataset}")
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY CHANGES'}")
    print()
    
    db = DatabaseManager()
    with db.get_session() as session:
        # Identify local broadcasters
        identified = identify_local_broadcasters(
            session,
            dataset=args.dataset,
            dry_run=dry_run,
        )
        
        # Populate table
        populate_callsigns(identified, session, dry_run=dry_run)
    
    print("\n✅ Done")


if __name__ == "__main__":
    main()
