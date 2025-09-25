#!/usr/bin/env python3
"""
Extraction script with comprehensive telemetry tracking.
"""

import argparse
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import text

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from src.utils.telemetry_extractor import TelemetryContentExtractor
from src.utils.extraction_telemetry import ExtractionTelemetry


def setup_logging():
    """Configure logging for the extraction process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/extraction_telemetry.log")
        ]
    )
    return logging.getLogger(__name__)


def get_candidates_for_extraction(db: DatabaseManager, limit: int = None,
                                  candidate_id: str = None,
                                  source_name: str = None):
    """Get candidate links that need content extraction."""
    
    if candidate_id:
        query = """
            SELECT id, url, source_name, source_host_id, dataset_id, source_id,
                   source_city, source_county, priority, publish_date
            FROM candidate_links
            WHERE id = :candidate_id
        """
        params = {"candidate_id": candidate_id}
    else:
        query = """
            SELECT id, url, source_name, source_host_id, dataset_id, source_id,
                   source_city, source_county, priority, publish_date
            FROM candidate_links
            WHERE (status IS NULL OR status != 'extracted')
        """
        params = {}
        
        if source_name:
            query += " AND source_name = :source_name"
            params["source_name"] = source_name
            
        query += " ORDER BY priority DESC, created_at ASC"
        
        if limit:
            query += f" LIMIT {limit}"
    
    with db.engine.connect() as conn:
        result = conn.execute(text(query), params)
        candidates = result.fetchall()
    
    return candidates
def create_article_from_candidate(db: DatabaseManager, candidate: dict,
                                extraction_result):
    """Create article record from extraction result."""
    extracted_content = extraction_result.extracted_content or {}
    
    content = extracted_content.get('content', '')
    title = extracted_content.get('title', '')
    author = extracted_content.get('author', '')
    publish_date = extracted_content.get('publish_date', '')
    
    # TODO: Persist article data once schema is finalized.
    return candidate['id']
    
def update_candidate_status(db: DatabaseManager, candidate_id: str, status: str,
                            publish_date: Optional[str] = None,
                            error_message: Optional[str] = None):
    """Update candidate_links status after extraction attempt."""
    update_data = {
        'candidate_id': candidate_id,
        'status': status,
        'processed_at': datetime.now().isoformat()
    }
    
    # Build dynamic update query based on provided fields
    set_clauses = ['status = :status', 'processed_at = :processed_at']
    
    if publish_date:
        set_clauses.append('publish_date = :publish_date')
        update_data['publish_date'] = publish_date
        
    if error_message:
        set_clauses.append('error_message = :error_message')
        update_data['error_message'] = error_message
    
    update_query = f"""
        UPDATE candidate_links 
        SET {', '.join(set_clauses)}
        WHERE id = :candidate_id
    """
    
    with db.engine.connect() as conn:
        conn.execute(text(update_query), update_data)
        conn.commit()


def main():
    """Main extraction function with telemetry."""
    parser = argparse.ArgumentParser(
        description="Extract content with telemetry"
    )
    parser.add_argument(
        "--limit", type=int, help="Limit number of candidates to process"
    )
    parser.add_argument(
        "--candidate-id", type=str, help="Extract specific candidate by ID"
    )
    parser.add_argument(
        "--source", type=str, default="ABC 17 KMIZ News",
        help="Source name to filter candidates (default: ABC 17 KMIZ News)"
    )
    parser.add_argument(
        "--timeout", type=int, default=20, help="Request timeout in seconds"
    )
    
    args = parser.parse_args()
    
    logger = setup_logging()
    logger.info("Starting content extraction with telemetry")
    
    # Generate operation ID for tracking this extraction run
    operation_id = str(uuid.uuid4())
    logger.info(f"Operation ID: {operation_id}")
    
    # Initialize components
    db = DatabaseManager()
    extractor = TelemetryContentExtractor(timeout=args.timeout)
    telemetry = ExtractionTelemetry()
    
    # Get candidates to process
    try:
        candidates = get_candidates_for_extraction(
            db, args.limit, args.candidate_id, args.source
        )
        logger.info(f"Found {len(candidates)} candidates for extraction from {args.source}")
    except Exception as e:
        logger.error(f"Failed to query candidates: {e}")
        return 1
    
    if not candidates:
        logger.info("No candidates found for extraction")
        return 0
    
    # Process each candidate
    results_summary = {
        'total': len(candidates),
        'successful': 0,
        'failed': 0,
        'outcomes': {}
    }
    
    for i, candidate_row in enumerate(candidates, 1):
        candidate = dict(candidate_row._mapping) if hasattr(candidate_row, "_mapping") else dict(candidate_row)
        
        logger.info(f"[{i}/{len(candidates)}] Processing candidate {candidate['id']}: {candidate['url']}")
        
        try:
            # Extract content with telemetry
            extraction_result = extractor.extract_content_with_telemetry(
                url=candidate['url'],
                article_id=None,  # Will be set after article creation
                operation_id=operation_id
            )
            
            # Create article from candidate and extraction result
            article_id = create_article_from_candidate(
                db, candidate, extraction_result
            )
            
            # Update extraction result with article_id and record telemetry
            extraction_result.article_id = article_id
            telemetry.record_extraction_outcome(
                operation_id=operation_id,
                article_id=article_id,
                url=candidate['url'],
                extraction_result=extraction_result
            )
            
            # Update result summary
            outcome = extraction_result.outcome.value
            results_summary['outcomes'][outcome] = results_summary['outcomes'].get(outcome, 0) + 1
            
            if extraction_result.is_success:
                results_summary['successful'] += 1
                logger.info(f"✓ Successfully extracted content (quality score: {extraction_result.content_quality_score:.2f})")
                
                # Update candidate status to 'extracted' with publish date if available
                extracted_publish_date = None
                if extraction_result.extracted_content:
                    extracted_publish_date = extraction_result.extracted_content.get('publish_date')
                
                update_candidate_status(
                    db=db,
                    candidate_id=candidate['id'],
                    status='extracted',
                    publish_date=extracted_publish_date
                )
            else:
                results_summary['failed'] += 1
                logger.warning(f"✗ Extraction failed: {outcome} - {extraction_result.error_message}")
                
                # Update candidate status to 'failed' with error message
                update_candidate_status(
                    db=db,
                    candidate_id=candidate['id'],
                    status='failed',
                    error_message=extraction_result.error_message
                )
                
        except Exception as e:
            results_summary['failed'] += 1
            logger.error(f"✗ Unexpected error processing candidate {candidate['id']}: {e}")
    
    # Print summary
    print("\n" + "="*60)
    print("EXTRACTION SUMMARY")
    print("="*60)
    print(f"Operation ID: {operation_id}")
    print(f"Total candidates: {results_summary['total']}")
    print(f"Successful: {results_summary['successful']}")
    print(f"Failed: {results_summary['failed']}")
    print(f"Success rate: {(results_summary['successful'] / results_summary['total'] * 100):.1f}%")
    print("\nOutcome breakdown:")
    for outcome, count in sorted(results_summary['outcomes'].items()):
        print(f"  {outcome}: {count}")
    
    # Get and display telemetry stats
    try:
        stats = telemetry.get_extraction_stats(operation_id)
        if stats:
            print("\nDetailed telemetry:")
            for stat in stats:
                print(f"  {stat['outcome']}: {stat['count']} articles, "
                      f"avg time: {stat['avg_time_ms']:.1f}ms, "
                      f"avg quality: {stat['avg_quality_score']:.2f}")
    except Exception as e:
        logger.warning(f"Failed to retrieve telemetry stats: {e}")
    
    logger.info("Content extraction completed")
    return 0


if __name__ == "__main__":
    exit(main())