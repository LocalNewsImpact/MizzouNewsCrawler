#!/usr/bin/env python3
"""
Backfill wire detection status in candidate_links table.

This script:
1. Re-runs wire detection on all articles with status='article'
2. Updates candidate_links.status to 'wire' for detected wire content
3. Tracks all articles moved to wire status
4. Generates CSV for BigQuery deletion
"""

import csv
from datetime import datetime
from pathlib import Path

from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text


def backfill_wire_status(
    batch_size: int = 1000,
    dry_run: bool = False,
    output_dir: str = ".",
):
    """
    Backfill wire detection on existing articles.
    
    Args:
        batch_size: Number of articles to process per batch
        dry_run: If True, don't update database
        output_dir: Directory to write output files
    """
    db = DatabaseManager()
    detector = ContentTypeDetector()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir)
    
    # Output files
    wire_articles_csv = output_path / f"wire_articles_to_remove_{timestamp}.csv"
    backfill_log = output_path / f"backfill_log_{timestamp}.txt"
    
    print(f"Starting wire detection backfill...")
    print(f"Dry run: {dry_run}")
    print(f"Output directory: {output_path}")
    print()
    
    total_processed = 0
    total_wire_detected = 0
    total_updated = 0
    
    # Track articles moved to wire
    wire_articles = []
    
    with open(backfill_log, "w") as log_file:
        log_file.write(f"Wire Detection Backfill - {timestamp}\n")
        log_file.write(f"Dry run: {dry_run}\n")
        log_file.write("=" * 80 + "\n\n")
        
        with db.get_session() as session:
            # Get total count - extracted and wire articles
            total_count = session.execute(text("""
                SELECT COUNT(DISTINCT a.id)
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE cl.status IN ('extracted', 'wire')
                AND a.candidate_link_id IS NOT NULL
            """)).scalar()
            
            print(f"Total articles to process: {total_count:,}")
            log_file.write(f"Total articles to process: {total_count:,}\n\n")
            
            offset = 0
            
            while offset < total_count:
                # Get batch of extracted and wire articles
                results = session.execute(text("""
                    SELECT
                        cl.id as candidate_link_id,
                        cl.url,
                        cl.source,
                        a.id as article_id,
                        a.title,
                        a.author,
                        a.text
                    FROM articles a
                    JOIN candidate_links cl ON a.candidate_link_id = cl.id
                    WHERE cl.status IN ('extracted', 'wire')
                    ORDER BY a.id
                    LIMIT :batch_size OFFSET :offset
                """), {"batch_size": batch_size, "offset": offset}).fetchall()
                
                if not results:
                    break
                
                batch_wire_detected = 0
                
                for row in results:
                    total_processed += 1
                    (candidate_link_id, url, source, article_id, 
                     title, author, article_text) = row
                    
                    # Run wire detection
                    result = detector._detect_wire_service(
                        url=url,
                        content=article_text or title or "",
                        metadata={"author": author}
                    )
                    
                    if result and result.status == "wire":
                        total_wire_detected += 1
                        batch_wire_detected += 1
                        
                        services = result.evidence.get("detected_services", [])
                        service = services[0] if services else "Unknown"
                        tier = result.evidence.get("detection_tier", "unknown")
                        confidence = result.confidence
                        
                        # Track for BigQuery removal
                        wire_articles.append({
                            "candidate_link_id": str(candidate_link_id),
                            "article_id": str(article_id),
                            "url": url,
                            "title": (title or "")[:100],
                            "author": author or "",
                            "source": source,
                            "detected_service": service,
                            "detection_tier": tier,
                            "confidence": confidence,
                        })
                        
                        # Update status in database
                        if not dry_run:
                            session.execute(text("""
                                UPDATE candidate_links
                                SET status = 'wire'
                                WHERE id = :candidate_link_id
                            """), {"candidate_link_id": candidate_link_id})
                            total_updated += 1
                
                if not dry_run:
                    session.commit()
                
                offset += batch_size
                
                # Progress update
                progress_pct = 100.0 * offset / total_count
                print(f"Progress: {offset:,}/{total_count:,} "
                      f"({progress_pct:.1f}%) | "
                      f"Batch wire: {batch_wire_detected} | "
                      f"Total wire: {total_wire_detected:,}")
        
        # Write summary to log
        wire_pct = (100.0 * total_wire_detected / total_processed 
                    if total_processed > 0 else 0)
        log_file.write(f"\nBackfill Complete\n")
        log_file.write("=" * 80 + "\n")
        log_file.write(f"Total processed: {total_processed:,}\n")
        log_file.write(f"Wire detected: {total_wire_detected:,} "
                      f"({wire_pct:.2f}%)\n")
        log_file.write(f"Database updated: {total_updated:,}\n")
        log_file.write(f"\nOutput files:\n")
        log_file.write(f"  - {wire_articles_csv}\n")
        log_file.write(f"  - {backfill_log}\n")
    
    # Write BigQuery removal CSV
    with open(wire_articles_csv, "w", newline="") as f:
        if wire_articles:
            writer = csv.DictWriter(f, fieldnames=wire_articles[0].keys())
            writer.writeheader()
            writer.writerows(wire_articles)
    
    print()
    print("=" * 80)
    print("Backfill Summary:")
    print(f"  Total processed: {total_processed:,}")
    wire_pct = (100.0 * total_wire_detected / total_processed 
                if total_processed > 0 else 0)
    print(f"  Wire detected: {total_wire_detected:,} ({wire_pct:.2f}%)")
    print(f"  Database updated: {total_updated:,}")
    print()
    print("Output files:")
    print(f"  - {wire_articles_csv} ({len(wire_articles):,} articles)")
    print(f"  - {backfill_log}")
    print()
    
    if dry_run:
        print("DRY RUN: No database changes were made")
    
    return wire_articles


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Backfill wire detection status"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Articles per batch (default: 1000)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't update database, just report changes"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Output directory (default: current directory)"
    )
    
    args = parser.parse_args()
    
    backfill_wire_status(
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )
