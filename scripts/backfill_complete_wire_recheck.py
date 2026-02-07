"""
Re-run COMPLETE wire detection on all ABC 17 and News Press NOW articles.
Uses the FULL BalancedBoundaryContentCleaner logic including:
- Byline detection
- URL pattern detection  
- Content/copyright detection
- Persistent pattern detection
"""
import sys
from datetime import datetime
from src.models.database import DatabaseManager
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner
from sqlalchemy import text

def reprocess_article(session, article, cleaner):
    """Re-run complete cleaning and wire detection on an article."""
    try:
        # Extract domain from URL
        from urllib.parse import urlparse
        domain = urlparse(article.url).netloc if article.url else ""
        
        # Run FULL cleaning process (includes ALL wire detection phases:
        # byline, URL pattern, content/copyright, persistent patterns)
        _, metadata = cleaner.process_single_article(
            text=article.content or article.text or "",
            domain=domain,
            article_id=str(article.id),
            dry_run=False
        )
        
        # Check wire detection result
        wire_detected = metadata.get("wire_detected")
        
        return {
            'is_wire': bool(wire_detected),
            'wire_service': wire_detected.get("provider") if wire_detected else None,
            'detection_method': wire_detected.get("detection_method") if wire_detected else None
        }
        
    except Exception as e:
        print(f"    ⚠️  Error processing: {e}", file=sys.stderr)
        return None

def main():
    db = DatabaseManager()
    cleaner = BalancedBoundaryContentCleaner()
    
    print("=" * 80)
    print("COMPLETE WIRE DETECTION RE-CHECK")
    print("=" * 80)
    print()
    
    with db.get_session() as session:
        # Get ALL ABC 17 and News Press NOW articles with status='cleaned'
        query = text('''
            SELECT 
                a.id,
                a.url,
                a.title,
                a.author,
                a.text,
                a.content,
                a.status,
                a.wire,
                cl.source,
                cl.discovered_at
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE cl.source IN ('ABC 17 KMIZ News', 'News Press Now')
            AND a.status = 'cleaned'
            ORDER BY cl.discovered_at DESC
        ''')
        
        articles = session.execute(query).fetchall()
        total = len(articles)
        
        print(f"Found {total} articles with status='cleaned' to re-check")
        print()
        
        stats = {
            'total': total,
            'confirmed_clean': 0,
            'found_wire': 0,
            'errors': 0
        }
        
        by_source = {
            'ABC 17 KMIZ News': {'clean': 0, 'wire': 0},
            'News Press Now': {'clean': 0, 'wire': 0}
        }
        
        batch_size = 10
        batch_count = 0
        
        for idx, article in enumerate(articles, 1):
            article_id = str(article.id)
            source = article.source
            
            print(f"  [{idx}/{total}] Processing {article_id[:8]}... ({source}, {article.discovered_at.strftime('%Y-%m-%d')})")
            
            # Create article object with all fields
            class ArticleObj:
                def __init__(self, row):
                    self.id = row.id
                    self.url = row.url
                    self.title = row.title
                    self.author = row.author
                    self.text = row.text
                    self.content = row.content
                    self.status = row.status
                    self.wire = row.wire
            
            article_obj = ArticleObj(article)
            
            # Run COMPLETE wire detection
            result = reprocess_article(session, article_obj, cleaner)
            
            if result is None:
                stats['errors'] += 1
                continue
            
            is_wire = result.get('is_wire', False)
            wire_service = result.get('wire_service')
            
            if is_wire and wire_service:
                # Build wire JSON payload
                import json
                wire_json = json.dumps({
                    "provider": wire_service,
                    "detection_method": result.get('detection_method', 'unknown'),
                    "detected_at": datetime.utcnow().isoformat()
                })
                
                # Update to wire status
                update_query = text('''
                    UPDATE articles 
                    SET status = 'wire',
                        wire = :wire_json::jsonb
                    WHERE id = :article_id
                ''')
                session.execute(update_query, {
                    'article_id': article_id,
                    'wire_json': wire_json
                })
                stats['found_wire'] += 1
                by_source[source]['wire'] += 1
                print(f"    ✓ Wire detected: {wire_service}")
            else:
                # Confirm as clean (no wire detected)
                stats['confirmed_clean'] += 1
                by_source[source]['clean'] += 1
                print(f"    ✓ Confirmed clean (no wire)")
            
            batch_count += 1
            if batch_count >= batch_size:
                session.commit()
                print(f"    💾 Committed batch")
                batch_count = 0
        
        # Final commit
        if batch_count > 0:
            session.commit()
            print(f"    💾 Committed final batch")
    
    print()
    print("=" * 80)
    print("RE-CHECK COMPLETE")
    print("=" * 80)
    print(f"Total articles re-checked: {stats['total']}")
    print(f"  Confirmed clean (no wire): {stats['confirmed_clean']}")
    print(f"  Found wire (reclassified): {stats['found_wire']}")
    print(f"  Errors: {stats['errors']}")
    print()
    print("By source:")
    for source, counts in by_source.items():
        print(f"  {source}:")
        print(f"    Clean: {counts['clean']}")
        print(f"    Wire: {counts['wire']}")
    print()
    print("Articles reclassified as wire will NOT be exported to BigQuery.")
    print("Confirmed clean articles need ML analysis:")
    print("  kubectl exec -n production deployment/mizzou-processor -- \\")
    print("    python -m src.cli.cli_modular analyze --batch-size 16")

if __name__ == '__main__':
    main()
