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
        help="Articles per batch"
    )
    extract_parser.add_argument(
        "--batches",
        type=int,
        default=1,
        help="Number of batches"
    )
    extract_parser.add_argument(
        "--source",
        type=str,
        help="Limit to a specific source"
    )


def handle_extraction_command(args) -> int:
    """Execute extraction command logic."""
    batches = getattr(args, "batches", 1)
    per_batch = getattr(args, "limit", 10)

    extractor = ContentExtractor()
    byline_cleaner = BylineCleaner()
    telemetry = ComprehensiveExtractionTelemetry()
    
    # Track hosts that return 403 responses within this run
    host_403_tracker = {}

    try:
        for batch_num in range(1, batches + 1):
            result = _process_batch(
                args, 
                extractor, 
                byline_cleaner, 
                telemetry, 
                per_batch, 
                batch_num,
                host_403_tracker
            )
            logger.info(f"Batch {batch_num}: {result}")
            if batch_num < batches:
                time.sleep(0.1)
        
        # Log driver usage stats before cleanup
        driver_stats = extractor.get_driver_stats()
        if driver_stats['has_persistent_driver']:
            logger.info(f"ChromeDriver efficiency: {driver_stats['driver_reuse_count']} reuses, "
                       f"{driver_stats['driver_creation_count']} creations")
        
        return 0
    except Exception:
        logger.exception("Extraction failed")
        return 1
    finally:
        # Clean up persistent driver when job is complete
        extractor.close_persistent_driver()


def _process_batch(args, extractor, byline_cleaner, telemetry, per_batch, batch_num, host_403_tracker):
    """Process a single extraction batch with domain-aware rate limit handling."""
    db = DatabaseManager()
    session = db.session

    # Track domain failures in this batch
    domain_failures = {}  # domain -> consecutive_failures
    max_failures_per_domain = 2
    
    try:
        # Get articles with domain diversity to avoid getting stuck on rate-limited domains
        q = """
        SELECT cl.id, cl.url, cl.source, cl.status, s.canonical_name
        FROM candidate_links cl
        LEFT JOIN sources s ON cl.source_id = s.id
        WHERE cl.status = 'article'
        AND cl.id NOT IN (SELECT candidate_link_id FROM articles WHERE candidate_link_id IS NOT NULL)
        ORDER BY RANDOM()  -- Use random order to mix domains
        LIMIT :limit_with_buffer
        """

        # Request more articles than we need to allow for domain skipping
        buffer_multiplier = 3
        params = {"limit_with_buffer": per_batch * buffer_multiplier}
        if getattr(args, "source", None):
            q = q.replace("WHERE cl.status = 'article'", "WHERE cl.status = 'article' AND cl.source = :source")
            params["source"] = args.source

        result = session.execute(text(q), params)
        rows = result.fetchall()
        if not rows:
            return {"processed": 0}

        processed = 0
        skipped_domains = set()
        
        for row in rows:
            # Stop if we've processed enough articles
            if processed >= per_batch:
                break
                
            url_id, url, source, status, canonical_name = row
            
            # Extract domain for failure tracking
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            
            # Skip domains that have failed too many times
            if domain in skipped_domains:
                logger.debug(f"Skipping {url} - domain {domain} temporarily blocked")
                continue
                
            # Check if domain is currently rate limited by extractor
            if extractor._check_rate_limit(domain):
                logger.info(f"Skipping {url} - domain {domain} is rate limited")
                skipped_domains.add(domain)
                continue
            
            operation_id = f"ex_{batch_num}_{url_id}"
            article_id = str(uuid.uuid4())
            publisher = canonical_name or source
            metrics = ExtractionMetrics(operation_id, article_id, url, publisher)

            try:
                content = extractor.extract_content(url, metrics=metrics)
                metrics.finalize(content or {})
                telemetry.record_extraction(metrics)

                if content and content.get("title"):
                    # Reset failure count on success
                    if domain in domain_failures:
                        domain_failures[domain] = 0
                        
                    # Clean the author field if present
                    raw_author = content.get("author")
                    cleaned_author = None
                    if raw_author:
                        cleaned_list = byline_cleaner.clean_byline(raw_author)
                        # Convert list to JSON string for database storage
                        cleaned_author = json.dumps(cleaned_list)
                        logger.info(
                            f"Author cleaning: '{raw_author}' → "
                            f"'{cleaned_list}'"
                        )
                    
                    now = datetime.utcnow()
                    session.execute(
                        text(
                            "INSERT INTO articles (id, candidate_link_id, url, title, "
                            "author, publish_date, content, text, status, metadata, "
                            "extracted_at, created_at) "
                            "VALUES (:id, :candidate_link_id, :url, :title, "
                            ":author, :publish_date, :content, :text, :status, :metadata, "
                            ":extracted_at, :created_at)"
                        ),
                        {
                            "id": article_id,
                            "candidate_link_id": str(url_id),
                            "url": url,
                            "title": content.get("title"),
                            "author": cleaned_author,
                            "publish_date": content.get("publish_date"),
                            "content": content.get("content"),
                            "text": content.get("content"),  # Same as content
                            "status": "extracted",
                            "metadata": json.dumps(content.get("metadata", {})),
                            "extracted_at": now.isoformat(),
                            "created_at": now.isoformat(),
                        },
                    )
                    session.execute(
                        text("UPDATE candidate_links SET status = :status WHERE id = :id"),
                        {"status": "extracted", "id": str(url_id)},
                    )
                    session.commit()
                    processed += 1
                else:
                    # Track failure for domain awareness
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1
                    
                    # If domain has failed too many times, skip it for rest of batch
                    if domain_failures[domain] >= max_failures_per_domain:
                        logger.warning(f"Domain {domain} failed "
                                     f"{domain_failures[domain]} times, "
                                     f"skipping for remainder of batch")
                        skipped_domains.add(domain)
                    
                    # For rate limit errors, also add to skipped domains immediately
                    error_msg = content.get("error", "") if content else ""
                    if "Rate limited" in error_msg or "429" in error_msg:
                        logger.warning(f"Rate limit detected for {domain}, "
                                     f"skipping remaining URLs")
                        skipped_domains.add(domain)
                    
                    metrics.error_message = "No title extracted"
                    metrics.error_type = "extraction_failure"
                    telemetry.record_extraction(metrics)

            except Exception as e:
                # Check for rate limit in exception
                error_str = str(e)
                if "Rate limited" in error_str or "429" in error_str:
                    logger.warning(f"Rate limit exception for {domain}, "
                                 f"skipping remaining URLs")
                    skipped_domains.add(domain)
                    domain_failures[domain] = max_failures_per_domain  # Max out
                else:
                    # Track other failures for domain awareness
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1
                    if domain_failures[domain] >= max_failures_per_domain:
                        logger.warning(f"Domain {domain} failed "
                                     f"{domain_failures[domain]} times, "
                                     f"skipping for remainder of batch")
                        skipped_domains.add(domain)
                
                metrics.error_message = str(e)
                metrics.error_type = "exception"
                metrics.finalize({})
                telemetry.record_extraction(metrics)
                session.rollback()
                
                # Check if this was a 403 response and track it
                status_code = getattr(metrics, "http_status_code", None)
                host = getattr(metrics, "host", None)
                
                if status_code == 403 and host:
                    # Track this host's 403 errors
                    seen = host_403_tracker.setdefault(host, set())
                    seen.add(str(url_id))
                    
                    # If we've seen multiple 403s from this host in this run,
                    # mark all candidate links from this host as paused
                    if len(seen) >= 2:
                        reason = "Auto-paused: multiple HTTP 403 responses"
                        host_like = f"%{host}%"
                        try:
                            session.execute(
                                text(
                                    "UPDATE candidate_links SET status = :status, error_message = :error "
                                    "WHERE url LIKE :host_like OR source = :host"
                                ),
                                {"status": "paused", "error": reason, "host_like": host_like, "host": host},
                            )
                            session.commit()
                            logger.warning(f"Auto-paused candidate links for host {host} after multiple 403 responses")
                        except Exception:
                            logger.exception(f"Failed to pause candidate links for {host}")
                            session.rollback()

        # Log domain skipping summary
        if skipped_domains:
            logger.info(f"Batch {batch_num} skipped domains due to failures: "
                       f"{', '.join(skipped_domains)}")
        
        if domain_failures:
            failure_summary = {k: v for k, v in domain_failures.items() if v > 0}
            if failure_summary:
                logger.info(f"Batch {batch_num} domain failure counts: "
                           f"{failure_summary}")

        return {"processed": processed, "skipped_domains": len(skipped_domains)}

    finally:
        session.close()
