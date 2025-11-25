#!/usr/bin/env python3
"""
Verification script for wire detection refactor.

Runs the new tiered detector on a sample of production articles and identifies
changes in wire detection status for manual verification.

Exports:
- wire_to_local.csv: Articles that changed FROM wire TO local
- local_to_wire.csv: Articles that changed FROM local TO wire
"""

import argparse
import csv
import logging

from sqlalchemy import select, func, or_

from src.models import Article, CandidateLink
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def verify_wire_detection(
    *,
    sample_size: int = 1000,
    wire_to_local_csv: str = "wire_to_local.csv",
    local_to_wire_csv: str = "local_to_wire.csv",
    sources: list[str] | None = None,
) -> None:
    """
    Run new detector on sample articles and identify wire status changes.
    
    Args:
        sample_size: Number of articles to sample and re-check
        wire_to_local_csv: Output CSV for articles that changed from wire to local
        local_to_wire_csv: Output CSV for articles that changed from local to wire
        sources: Optional list of specific sources to check (e.g., ['abc17news.com'])
    """
    db = DatabaseManager()
    detector = ContentTypeDetector()
    
    wire_to_local: list[dict] = []
    local_to_wire: list[dict] = []
    
    with db.get_session() as session:
        # Build query
        stmt = (
            select(Article, CandidateLink.url, CandidateLink.source)
            .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
            .where(Article.status.in_(['wire', 'cleaned', 'local', 'labeled']))
            .order_by(Article.extracted_at.desc())
            .limit(sample_size)
        )
        
        # Filter by specific sources if provided
        if sources:
            source_conditions = [
                func.lower(CandidateLink.source).like(f"%{src.lower()}%")
                for src in sources
            ]
            stmt = stmt.where(or_(*source_conditions))
        
        result = session.execute(stmt)
        rows = result.all()
        
        logger.info(f"Processing {len(rows)} articles...")
        
        processed = 0
        unchanged = 0
        
        for article, url, source in rows:
            processed += 1
            
            if processed % 100 == 0:
                logger.info(f"Processed {processed}/{len(rows)} articles...")
            
            # Get current status
            old_status = article.status or 'unknown'
            old_is_wire = old_status == 'wire'
            
            # Run new detector
            metadata = {
                'author': article.author,
                'byline': article.author,
            }
            
            # Use the main detect method
            detection_result = detector.detect(
                url=url,
                content=article.text or article.content,
                metadata=metadata,
                title=article.title,
            )
            
            # Check if result is wire
            new_is_wire = (
                detection_result is not None
                and detection_result.status == 'wire'
            )
            
            # Check for status change
            if old_is_wire and not new_is_wire:
                # Wire → Local
                record = {
                    'article_id': article.id,
                    'url': url,
                    'source': source,
                    'title': article.title or '',
                    'author': article.author or '',
                    'old_status': old_status,
                    'new_status': 'local',
                    'old_evidence': 'N/A (old detector)',
                    'new_evidence': 'None (not detected as wire)',
                }
                wire_to_local.append(record)
                
            elif not old_is_wire and new_is_wire:
                # Local → Wire
                evidence = detection_result.evidence if detection_result else {}
                detected_services = evidence.get('detected_services', [])
                detection_tier = evidence.get('detection_tier', 'unknown')
                
                record = {
                    'article_id': article.id,
                    'url': url,
                    'source': source,
                    'title': article.title or '',
                    'author': article.author or '',
                    'old_status': old_status,
                    'new_status': 'wire',
                    'old_evidence': 'None (not detected as wire)',
                    'new_evidence': (
                        f"Tier: {detection_tier}, "
                        f"Services: {', '.join(detected_services)}"
                    ),
                }
                local_to_wire.append(record)
            else:
                unchanged += 1
        
        # Write CSV files
        fieldnames = [
            'article_id',
            'url',
            'source',
            'title',
            'author',
            'old_status',
            'new_status',
            'old_evidence',
            'new_evidence',
        ]
        
        # Wire → Local
        if wire_to_local:
            with open(wire_to_local_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(wire_to_local)
            logger.info(
                f"Exported {len(wire_to_local)} wire→local changes "
                f"to {wire_to_local_csv}"
            )
        else:
            logger.info("No wire→local changes detected")
        
        # Local → Wire
        if local_to_wire:
            with open(local_to_wire_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(local_to_wire)
            logger.info(
                f"Exported {len(local_to_wire)} local→wire changes "
                f"to {local_to_wire_csv}"
            )
        else:
            logger.info("No local→wire changes detected")
        
        # Summary
        print("\n" + "="*80)
        print("WIRE DETECTION VERIFICATION SUMMARY")
        print("="*80)
        print(f"Total articles processed: {processed}")
        print(f"Unchanged: {unchanged}")
        print(f"Wire → Local: {len(wire_to_local)}")
        print(f"Local → Wire: {len(local_to_wire)}")
        print("\nOutput files:")
        print(f"  - {wire_to_local_csv}")
        print(f"  - {local_to_wire_csv}")
        print("="*80)


def main():
    parser = argparse.ArgumentParser(
        description="Verify wire detection changes on production data"
    )
    parser.add_argument(
        '--sample-size',
        type=int,
        default=1000,
        help='Number of articles to sample (default: 1000)'
    )
    parser.add_argument(
        '--wire-to-local-csv',
        type=str,
        default='wire_to_local.csv',
        help='Output CSV for wire→local changes'
    )
    parser.add_argument(
        '--local-to-wire-csv',
        type=str,
        default='local_to_wire.csv',
        help='Output CSV for local→wire changes'
    )
    parser.add_argument(
        '--sources',
        nargs='+',
        help='Specific sources to check (e.g., abc17news.com komu.com)'
    )
    
    args = parser.parse_args()
    
    verify_wire_detection(
        sample_size=args.sample_size,
        wire_to_local_csv=args.wire_to_local_csv,
        local_to_wire_csv=args.local_to_wire_csv,
        sources=args.sources,
    )


if __name__ == '__main__':
    main()
