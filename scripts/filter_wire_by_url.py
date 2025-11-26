#!/usr/bin/env python3
"""
Filter candidate links by URL patterns only.
Fast pre-extraction wire detection based solely on URL structure.
Reduces unnecessary extractions by ~30% by catching nation/world/wire content.
"""
import re
from sqlalchemy import text
from src.models.database import DatabaseManager


# Common wire service URL patterns (fast, no DB lookup needed)
WIRE_URL_PATTERNS = [
    # National/World sections
    (r'/national/', 'national-section'),
    (r'/world/', 'world-section'),
    (r'/nation/', 'national-section'),
    (r'/nation-world/', 'nation-world-section'),
    (r'/nationworld/', 'nation-world-section'),
    (r'/us-news/', 'us-news-section'),
    
    # AP content paths
    (r'/ap/', 'ap'),
    (r'/apnews/', 'ap'),
    (r'-ap-', 'ap'),
    (r'/associated-press/', 'ap'),
    
    # Other wire services
    (r'/reuters/', 'reuters'),
    (r'/cnn/', 'cnn'),
    (r'/fox-news/', 'fox'),
    (r'/usa-today/', 'usa-today'),
    (r'/washington-post/', 'washington-post'),
    (r'/nyt/', 'nyt'),
]


def check_wire_url(url: str) -> tuple[bool, str | None]:
    """Check if URL matches wire patterns. Returns (is_wire, service_name)."""
    url_lower = url.lower()
    
    for pattern, service in WIRE_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True, service
    
    return False, None


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Filter candidates by wire URL patterns')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated')
    parser.add_argument('--limit', type=int, help='Limit number of candidates to process')
    parser.add_argument('--all', action='store_true', help='Process all candidates (no limit)')
    
    args = parser.parse_args()
    
    if not args.all and args.limit is None:
        parser.error('Must specify --limit N or --all')
    
    dry_run = args.dry_run
    limit = args.limit if not args.all else 999999
    
    print("=" * 80)
    print("WIRE URL FILTERING - FAST PRE-EXTRACTION CHECK")
    print("=" * 80)
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    print(f"Limit: {limit if not args.all else 'ALL'}")
    print()
    
    db = DatabaseManager()
    with db.get_session() as session:
        # Get eligible candidates
        query = text("""
            SELECT id, url, source
            FROM candidate_links
            WHERE status IN ('article', 'verified')
            AND id NOT IN (
                SELECT candidate_link_id FROM articles WHERE candidate_link_id IS NOT NULL
            )
            ORDER BY discovered_at DESC
            LIMIT :limit
        """)
        
        candidates = session.execute(query, {"limit": limit}).fetchall()
        total = len(candidates)
        print(f"Found {total} eligible candidates")
        print()
        
        wire_count = 0
        not_wire = 0
        updated = 0
        
        for idx, (cid, url, source) in enumerate(candidates, 1):
            if idx % 100 == 0:
                print(f"Progress: {idx}/{total} ({idx*100//total}%)")
            
            is_wire, service = check_wire_url(url)
            
            if is_wire:
                wire_count += 1
                
                if wire_count <= 10 or dry_run:  # Show first 10 or all in dry-run
                    print(f"🔴 WIRE [{wire_count}]: {service}")
                    print(f"   ID: {cid}, Source: {source}")
                    print(f"   URL: {url[:70]}...")
                
                if not dry_run:
                    update = text("UPDATE candidate_links SET status = 'wire' WHERE id = :cid")
                    session.execute(update, {"cid": cid})
                    session.commit()
                    updated += 1
                    if wire_count <= 10:
                        print("   ✅ Updated")
                elif wire_count <= 10:
                    print("   🔵 Would update (dry-run)")
                
                if wire_count <= 10 or dry_run:
                    print()
            else:
                not_wire += 1
        
        # Summary
        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total processed:  {total}")
        print(f"Wire detected:    {wire_count} ({wire_count*100//total if total else 0}%)")
        print(f"Not wire:         {not_wire} ({not_wire*100//total if total else 0}%)")
        
        if dry_run:
            print(f"Would update:     {wire_count} (dry-run)")
        else:
            print(f"Actually updated: {updated}")
        
        print("=" * 80)


if __name__ == "__main__":
    main()
