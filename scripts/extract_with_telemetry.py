#!/usr/bin/env python3
"""
Enhanced content extraction command with comprehensive telemetry.

This script provides content extraction with detailed outcome tracking,
error categorization, and performance metrics for analysis and monitoring.

Usage:
    python scripts/extract_with_telemetry.py --limit 10
    python scripts/extract_with_telemetry.py --article-id 123
"""

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from sqlalchemy import text

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.database import DatabaseManager
from utils.telemetry_extractor import TelemetryContentExtractor
from utils.extraction_telemetry import ExtractionTelemetry


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
                                  extraction_result) -> int:
    """Create an article from a candidate link with extraction results."""
    
    # Prepare article data
    content = extraction_result.extracted_content.get('content', '') if extraction_result.extracted_content else ''
    title = extraction_result.extracted_content.get('title', '') if extraction_result.extracted_content else ''
    author = extraction_result.extracted_content.get('author', '') if extraction_result.extracted_content else ''
    # Extract publish_date from extraction result, not candidate link
    publish_date = (extraction_result.extracted_content.get('publish_date')
                    if extraction_result.extracted_content else None)
    
    # Create metadata with source information and quality metrics
    metadata = {
        'source_name': candidate['source_name'],
        'source_host_id': candidate['source_host_id'],
        'dataset_id': candidate['dataset_id'],
        'source_id': candidate['source_id'],
        'source_city': candidate.get('source_city'),
        'source_county': candidate.get('source_county'),
        'content_quality_score': extraction_result.content_quality_score,
        'extraction_outcome': extraction_result.outcome.value,
        'extraction_time_ms': extraction_result.extraction_time_ms,
        'error_message': extraction_result.error_message if not extraction_result.is_success else None
    }
    
    article_data = {
        'id': str(uuid.uuid4()),  # Generate UUID for article ID
        'candidate_link_id': candidate['id'],
        'url': candidate['url'],
        'title': title,
        'content': content,
        'text': content,  # Use content for both content and text fields
        'author': author,
        'publish_date': publish_date,
        'status': 'extracted' if extraction_result.is_success else 'failed',
        'metadata': json.dumps(metadata),
        'extracted_at': datetime.now().isoformat(),
        'extraction_version': '1.0'
    }
    
    # Insert article
    insert_query = """
        INSERT INTO articles (
            id, candidate_link_id, url, title, content, text, author, publish_date,
            status, metadata, extracted_at, extraction_version, created_at
        ) VALUES (
            :id, :candidate_link_id, :url, :title, :content, :text, :author, :publish_date,
            :status, :metadata, :extracted_at, :extraction_version, datetime('now')
        )
    """
    
    with db.engine.connect() as conn:
        result = conn.execute(text(insert_query), article_data)
        conn.commit()
        return article_data['id']  # Return the UUID we generated


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
            else:
                results_summary['failed'] += 1
                logger.warning(f"✗ Extraction failed: {outcome} - {extraction_result.error_message}")
                
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