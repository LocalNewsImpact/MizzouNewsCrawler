#!/usr/bin/env python3
"""
Backfill script to fix ABC17 and News-Press NOW articles incorrectly marked as wire.

This script:
1. Identifies articles marked as wire for ABC17 and News-Press NOW
2. Re-runs cleaning with the fixed wire detection logic
3. Updates article status appropriately
4. Triggers BigQuery export via database updates
"""

import sys
import os
from datetime import datetime
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models.database import DatabaseManager
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def get_wire_articles_to_backfill(session, source_patterns):
    """Get articles marked as wire for the given source patterns."""
    source_filter = " OR ".join([f"cl.source LIKE '%{pattern}%'" for pattern in source_patterns])
    
    query = text(f"""
        SELECT 
            a.id,
            a.content,
            cl.source,
            a.wire,
            a.status,
            a.extracted_at
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE ({source_filter})
        AND a.status = 'wire'
        AND a.content IS NOT NULL
        ORDER BY a.extracted_at DESC
    """)
    
    return session.execute(query).fetchall()


def reprocess_article(session, article_id, content, source):
    """Re-run cleaning on an article with fixed wire detection logic."""
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=True)
    
    # Use source directly as domain
    domain = source.lower().replace(" ", "")
    
    # Process the article content
    cleaned_content, metadata = cleaner.process_single_article(
        text=content,
        domain=domain,
        article_id=article_id,
        dry_run=False
    )
    
    # Extract wire detection result
    wire_detected = metadata.get("wire_detected")
    
    return {
        "cleaned_content": cleaned_content,
        "wire_detected": wire_detected,
        "metadata": metadata
    }


def update_article_status(session, article_id, wire_detected, cleaned_content):
    """Update article status and wire payload."""
    if wire_detected:
        # Still wire after reprocessing
        update_query = text("""
            UPDATE articles
            SET 
                wire = :wire_payload,
                content = :cleaned_content
            WHERE id = :article_id
        """)
        session.execute(update_query, {
            "article_id": article_id,
            "wire_payload": wire_detected,
            "cleaned_content": cleaned_content
        })
        return "wire"
    else:
        # No longer wire - update to cleaned
        update_query = text("""
            UPDATE articles
            SET 
                status = 'cleaned',
                wire = NULL,
                content = :cleaned_content
            WHERE id = :article_id
        """)
        session.execute(update_query, {
            "article_id": article_id,
            "cleaned_content": cleaned_content
        })
        return "cleaned"


def main():
    """Main backfill process."""
    # Search by source name patterns
    source_patterns = ["ABC 17", "News Press"]
    
    db = DatabaseManager()
    
    with db.get_session() as session:
        print("=" * 80)
        print("ABC17 & News-Press NOW Wire Detection Backfill")
        print("=" * 80)
        print()
        
        # Get articles to backfill
        print(f"Fetching articles marked as wire for sources matching: {', '.join(source_patterns)}")
        articles = get_wire_articles_to_backfill(session, source_patterns)
        
        print(f"Found {len(articles)} articles to reprocess")
        print()
        
        if not articles:
            print("No articles to backfill. Exiting.")
            return
        
        # Statistics
        stats = {
            "total": len(articles),
            "still_wire": 0,
            "fixed_to_cleaned": 0,
            "errors": 0,
            "by_source": {}
        }
        
        # Process each article
        for i, article in enumerate(articles, 1):
            article_id = article[0]
            content = article[1]
            source = article[2]
            current_wire = article[3]
            extracted_at = article[5]
            
            # Track by source
            if source not in stats["by_source"]:
                stats["by_source"][source] = {
                    "total": 0,
                    "still_wire": 0,
                    "fixed_to_cleaned": 0
                }
            
            stats["by_source"][source]["total"] += 1
            
            try:
                print(f"  [{i}/{len(articles)}] Processing {article_id} ({source}, {extracted_at})")
                
                # Reprocess article
                result = reprocess_article(session, article_id, content, source)
                wire_detected = result["wire_detected"]
                cleaned_content = result["cleaned_content"]
                
                # Update article
                new_status = update_article_status(session, article_id, wire_detected, cleaned_content)
                
                if new_status == "wire":
                    stats["still_wire"] += 1
                    stats["by_source"][source]["still_wire"] += 1
                    print(f"    ✓ Still wire: {wire_detected.get('provider') if wire_detected else 'unknown'}")
                else:
                    stats["fixed_to_cleaned"] += 1
                    stats["by_source"][source]["fixed_to_cleaned"] += 1
                    print(f"    ✓ Fixed: wire → cleaned")
                
                # Commit every 10 articles
                if i % 10 == 0:
                    session.commit()
                    print(f"    💾 Committed batch")
                
            except Exception as e:
                print(f"    ✗ Error: {e}")
                stats["errors"] += 1
                session.rollback()
                continue
        
        # Final commit
        session.commit()
        
        # Print statistics
        print()
        print("=" * 80)
        print("BACKFILL COMPLETE")
        print("=" * 80)
        print(f"Total articles processed: {stats['total']}")
        print(f"  Still wire (legitimate): {stats['still_wire']}")
        print(f"  Fixed (wire → cleaned): {stats['fixed_to_cleaned']}")
        print(f"  Errors: {stats['errors']}")
        print()
        
        for source, source_stats in stats["by_source"].items():
            print(f"{source}:")
            print(f"  Total: {source_stats['total']}")
            print(f"  Still wire: {source_stats['still_wire']}")
            print(f"  Fixed: {source_stats['fixed_to_cleaned']}")
        
        print()
        print("Next steps:")
        print("1. Datastream CDC will automatically sync changes to BigQuery")
        print("2. Fixed articles (now status='cleaned') need ML analysis:")
        print("   kubectl exec -n production deployment/mizzou-processor -- \\")
        print("     python -m src.cli.cli_modular analyze --batch-size 16")
        print("3. After ML analysis, articles will be status='labeled' and exported to BigQuery")
        print()


if __name__ == "__main__":
    main()
