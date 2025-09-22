"""
Extraction command module for the modular CLI.
"""

import logging
import time
import uuid
import json
from datetime import datetime
from sqlalchemy import text
from src.models.database import DatabaseManager
from src.crawler import ContentExtractor
from src.utils.byline_cleaner import BylineCleaner
from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics
)

logger = logging.getLogger(__name__)


def add_extraction_parser(subparsers):
    """Add extraction command parser to CLI."""
    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract content from verified articles"
    )
    extract_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of articles to extract per batch (default: 10)"
    )
    extract_parser.add_argument(
        "--batches",
        type=int,
        default=1,
        help="Number of batches to process (default: 1)"
    )
    extract_parser.add_argument(
        "--articles-only",
        action="store_true",
        default=True,
        help="Only extract URLs with 'article' status (default: True)"
    )
    extract_parser.add_argument(
        "--source",
        type=str,
        help="Extract from specific source only"
    )


def handle_extraction_command(args) -> int:
    """Handle the extraction command with batch processing."""
    try:
        batches = getattr(args, 'batches', 1)
        per_batch = args.limit
        total_articles = batches * per_batch
        
        logger.info(f"Starting extraction: {batches} batches of {per_batch} articles each")
        
        # Overall statistics tracking
        overall_stats = {
            'total_processed': 0,
            'total_successful': 0,
            'total_failed': 0,
            'batches_completed': 0
        }
        
        # Initialize extractor, byline cleaner, and telemetry once for all batches
        extractor = ContentExtractor()
        byline_cleaner = BylineCleaner()
        telemetry = ComprehensiveExtractionTelemetry()
        
        print(f"\\n🚀 Starting batch extraction: {batches} batches × {per_batch} articles")
        print("=" * 60)
        
        for batch_num in range(1, batches + 1):
            print(f"\\n📦 BATCH {batch_num}/{batches}")
            print("-" * 30)
            
            # Process this batch
            batch_stats = _process_batch(
                args, extractor, byline_cleaner, telemetry, per_batch, batch_num
            )
            
            if batch_stats is None:
                print(f"No articles found for batch {batch_num}")
                break
            
            # Update overall statistics
            overall_stats['total_processed'] += batch_stats['processed']
            overall_stats['total_successful'] += batch_stats['successful']
            overall_stats['total_failed'] += batch_stats['failed']
            overall_stats['batches_completed'] += 1
            
            # Show batch summary
            success_rate = (batch_stats['successful'] / batch_stats['processed'] * 100) if batch_stats['processed'] > 0 else 0
            print(f"\\n✅ Batch {batch_num} complete:")
            print(f"   Processed: {batch_stats['processed']}")
            print(f"   Successful: {batch_stats['successful']}")
            print(f"   Failed: {batch_stats['failed']}")
            print(f"   Success Rate: {success_rate:.1f}%")
            
            # Show user agent rotation stats
            rotation_stats = extractor.get_rotation_stats()
            print(f"   Domains accessed: {rotation_stats['total_domains_accessed']}")
            
            # Brief pause between batches
            if batch_num < batches:
                print(f"\\n⏳ Pausing briefly before batch {batch_num + 1}...")
                time.sleep(3)
        
        # Final summary
        print(f"\\n🎯 EXTRACTION COMPLETE")
        print("=" * 60)
        overall_success_rate = (overall_stats['total_successful'] / overall_stats['total_processed'] * 100) if overall_stats['total_processed'] > 0 else 0
        print(f"Batches completed: {overall_stats['batches_completed']}/{batches}")
        print(f"Total articles processed: {overall_stats['total_processed']}")
        print(f"Total successful: {overall_stats['total_successful']}")
        print(f"Total failed: {overall_stats['total_failed']}")
        print(f"Overall success rate: {overall_success_rate:.1f}%")
        
        # Show final rotation statistics
        rotation_stats = extractor.get_rotation_stats()
        print(f"\\nUser Agent Rotation Summary:")
        print(f"  Total domains: {rotation_stats['total_domains_accessed']}")
        print(f"  Active sessions: {rotation_stats['active_sessions']}")
        for domain, count in rotation_stats['request_counts'].items():
            print(f"  {domain}: {count} requests")
        
        return 0
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return 1


def _process_batch(args, extractor, byline_cleaner, telemetry, per_batch,
                   batch_num):
    """Process a single batch of articles."""
    db = DatabaseManager()
    session = db.session
    
    try:
        # Build query for articles to extract with source information
        query = text('''
            SELECT cl.id, cl.url, cl.source, cl.status, s.canonical_name
            FROM candidate_links cl
            LEFT JOIN sources s ON cl.source_id = s.id
            WHERE cl.status = 'article'
            AND cl.id NOT IN (
                SELECT candidate_link_id 
                FROM articles 
                WHERE candidate_link_id IS NOT NULL
            )
        ''')
        
        if hasattr(args, 'source') and args.source:
            query = text(f"{query.text} AND source = '{args.source}'")
            
        query = text(f"{query.text} ORDER BY created_at DESC LIMIT {per_batch}")
        
        result = session.execute(query)
        articles = result.fetchall()
        
        if not articles:
            return None
            
        print(f"Found {len(articles)} articles for batch {batch_num}")
        
        batch_stats = {'processed': 0, 'successful': 0, 'failed': 0}
        
        for i, article in enumerate(articles, 1):
            url_id, url, source, status, canonical_name = article
            batch_stats['processed'] += 1

            print(f"\\n[{i}/{len(articles)}] Processing article from {source}")
            print(f"  URL: {url[:80]}{'...' if len(url) > 80 else ''}")

            # Create telemetry metrics for this extraction
            operation_id = f"extraction_{batch_num}_{i}"
            article_id = str(uuid.uuid4())
            publisher = canonical_name if canonical_name else source
            metrics = ExtractionMetrics(operation_id, article_id, url, publisher)

            try:
                # Extract content with telemetry
                start_time = time.time()
                content_data = extractor.extract_content(url, metrics=metrics)
                extraction_time = time.time() - start_time

                # Finalize telemetry metrics
                metrics.finalize(content_data if content_data else {})

                # Record telemetry
                telemetry.record_extraction(metrics)

                print(f"  Extraction completed in {extraction_time:.1f}s")
                
                if content_data and content_data.get('title'):
                    # Generate unique article ID for each article
                    article_id = str(uuid.uuid4())
                    
                    # Clean the author field if present
                    raw_author = content_data.get('author')
                    cleaned_author_json = None
                    
                    if raw_author:
                        # Get cleaned authors using canonical name for removal
                        source_name = canonical_name if canonical_name else source
                        
                        cleaned_authors_list = byline_cleaner.clean_byline(
                            raw_author, 
                            source_name=source_name,
                            article_id=article_id,
                            candidate_link_id=url_id,
                            source_id=None,  # Not available in current query
                            source_canonical_name=canonical_name
                        )
                        
                        # Convert to JSON string for storage
                        cleaned_author_json = json.dumps(cleaned_authors_list)
                        
                        logger.info(
                            f"Author cleaning: '{raw_author}' → "
                            f"{cleaned_authors_list}")
                    
                    # Save to articles table
                    now = datetime.utcnow()
                    
                    # Properly format metadata as JSON string
                    metadata_json = json.dumps(content_data.get('metadata', {}))
                    
                    # Format dates as strings for SQLite
                    publish_date_str = None
                    if content_data.get('publish_date'):
                        pub_date = content_data.get('publish_date')
                        if isinstance(pub_date, datetime):
                            publish_date_str = pub_date.isoformat()
                        else:
                            publish_date_str = str(pub_date)
                    
                    # Insert into articles table
                    session.execute(
                        text('''
                            INSERT INTO articles 
                            (id, candidate_link_id, url, title, author, publish_date, 
                             content, text, status, metadata, extracted_at, created_at, extraction_version)
                            VALUES 
                            (:id, :candidate_link_id, :url, :title, :author, :publish_date, 
                             :content, :text, :status, :metadata, :extracted_at, :created_at, :extraction_version)
                        '''),
                        {
                            "id": article_id,
                            "candidate_link_id": str(url_id),
                            "url": url,
                            "title": content_data.get('title'),
                            "author": cleaned_author_json,
                            "publish_date": publish_date_str,
                            "content": content_data.get('content'),
                            "text": content_data.get('content'),
                            "status": "extracted",
                            "metadata": metadata_json,
                            "extracted_at": now.isoformat(),
                            "created_at": now.isoformat(),
                            "extraction_version": "v1.0"
                        }
                    )
                    
                    # Update candidate_link status to prevent reprocessing
                    session.execute(
                        text('''UPDATE candidate_links
                             SET status = :status
                             WHERE id = :id'''),
                        {"status": "extracted", "id": str(url_id)}
                    )
                    
                    session.commit()
                    batch_stats['successful'] += 1
                    
                    # Show success status
                    print(f"  ✅ Success: {content_data['title'][:50]}...")
                    
                    # Show extraction methods used if available
                    metadata = content_data.get('metadata', {})
                    extraction_methods = metadata.get('extraction_methods', {})
                    if extraction_methods:
                        methods_summary = []
                        for field, method in extraction_methods.items():
                            methods_summary.append(f"{field}:{method}")
                        if methods_summary:
                            print(f"    Methods: {', '.join(methods_summary)}")
                
                else:
                    print("  ❌ Failed: No title extracted")
                    batch_stats['failed'] += 1
                    # Record failed extraction in telemetry
                    metrics.error_message = "No title extracted"
                    metrics.error_type = "extraction_failure"

            except Exception as e:
                logger.error(f"Failed to extract {url}: {e}")
                print(f"  ❌ Failed: {str(e)[:100]}...")
                batch_stats['failed'] += 1
                session.rollback()
                # Record exception in telemetry
                metrics.error_message = str(e)
                metrics.error_type = "exception"
                metrics.finalize({})
                telemetry.record_extraction(metrics)
        
        return batch_stats
        
    finally:
        session.close()
