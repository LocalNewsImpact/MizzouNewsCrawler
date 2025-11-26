#!/usr/bin/env python3
"""Filter wire content from eligible candidate links."""

from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text
import sys

def main():
    dry_run = '--dry-run' in sys.argv
    limit = 50
    
    if '--all' in sys.argv:
        limit = None
    elif '--limit' in sys.argv:
        idx = sys.argv.index('--limit')
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])
    
    print("=" * 80)
    print("WIRE CONTENT FILTERING - ELIGIBLE CANDIDATES")
    print("=" * 80)
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Limit: {limit if limit else 'ALL'}")
    print()
    
    db = DatabaseManager()
    with db.get_session() as session:
        # Get eligible candidates
        query = text("""
            SELECT id, url, source
            FROM candidate_links 
            WHERE status IN ('article', 'verified')
            AND id NOT IN (
                SELECT candidate_link_id 
                FROM articles 
                WHERE candidate_link_id IS NOT NULL
            )
            ORDER BY discovered_at DESC
            LIMIT :limit
        """)
        
        params = {"limit": limit if limit else 100000}
        candidates = session.execute(query, params).fetchall()
        total = len(candidates)
        
        print(f"Found {total} eligible candidates")
        print()
        
        if total == 0:
            print("No candidates to process")
            return 0
        
        # Process candidates
        detector = ContentTypeDetector(session=session)
        wire_count = 0
        not_wire = 0
        updated = 0
        
        for idx, row in enumerate(candidates, 1):
            cid, url, source = row[0], row[1], row[2]
            
            if idx % 10 == 0:
                print(f"Progress: {idx}/{total} ({idx*100//total}%)")
            
            try:
                result = detector.detect(
                    url=url,
                    title=None,
                    metadata=None,
                    content=None,
                    author=None
                )
                
                if result and result.get('is_wire'):
                    wire_count += 1
                    ws = result.get('wire_service', 'Unknown')
                    conf = result.get('confidence', 'unknown')
                    
                    print(f"🔴 WIRE [{wire_count}]: {ws} ({conf})")
                    print(f"   ID: {cid}, Source: {source}")
                    print(f"   URL: {url[:70]}...")
                    
                    if not dry_run:
                        update = text("""
                            UPDATE candidate_links 
                            SET status = 'wire'
                            WHERE id = :cid
                        """)
                        session.execute(update, {"cid": cid})
                        session.commit()
                        updated += 1
                        print(f"   ✅ Updated to 'wire' status")
                    else:
                        print(f"   🔵 Would update (dry-run)")
                    print()
                else:
                    not_wire += 1
                    
            except Exception as e:
                print(f"❌ Error processing {cid}: {e}")
                print()
        
        # Summary
        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total processed: {total}")
        print(f"Wire detected:   {wire_count} ({wire_count*100//total if total else 0}%)")
        print(f"Not wire:        {not_wire} ({not_wire*100//total if total else 0}%)")
        
        if not dry_run:
            print(f"Updated:         {updated}")
        else:
            print(f"Would update:    {wire_count} (dry-run)")
        
        print("=" * 80)
        
        return 0

if __name__ == "__main__":
    sys.exit(main())
