"""
Extraction command module for the modular CLI.
"""

import json
import logging
import os
import random
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import cast

from sqlalchemy import text

from src.crawler import ContentExtractor, NotFoundError
from src.models import Article, CandidateLink
from src.models.database import (
    DatabaseManager,
    _commit_with_retry,
    calculate_content_hash,
    save_article_entities,
)
from src.pipeline.entity_extraction import (
    ArticleEntityExtractor,
    attach_gazetteer_matches,
    get_gazetteer_rows,
)
from src.utils.byline_cleaner import BylineCleaner
from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics,
)
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner
from src.utils.content_type_detector import ContentTypeDetector

logger = logging.getLogger(__name__)


_ENTITY_EXTRACTOR: ArticleEntityExtractor | None = None
_CONTENT_TYPE_DETECTOR: ContentTypeDetector | None = None


def _get_entity_extractor() -> ArticleEntityExtractor:
    global _ENTITY_EXTRACTOR
    if _ENTITY_EXTRACTOR is None:
        _ENTITY_EXTRACTOR = ArticleEntityExtractor()
    return _ENTITY_EXTRACTOR


def _get_content_type_detector() -> ContentTypeDetector:
    global _CONTENT_TYPE_DETECTOR
    if _CONTENT_TYPE_DETECTOR is None:
        _CONTENT_TYPE_DETECTOR = ContentTypeDetector()
    return _CONTENT_TYPE_DETECTOR


ARTICLE_INSERT_SQL = text(
    "INSERT INTO articles (id, candidate_link_id, url, title, author, "
    "publish_date, content, text, status, metadata, wire, extracted_at, "
    "created_at, text_hash) VALUES (:id, :candidate_link_id, :url, :title, "
    ":author, :publish_date, :content, :text, :status, :metadata, :wire, "
    ":extracted_at, :created_at, :text_hash)"
)

CANDIDATE_STATUS_UPDATE_SQL = text(
    "UPDATE candidate_links SET status = :status WHERE id = :id"
)

PAUSE_CANDIDATE_LINKS_SQL = text(
    "UPDATE candidate_links "
    "SET status = :status, error_message = :error "
    "WHERE url LIKE :host_like OR source = :host"
)

ARTICLE_UPDATE_SQL = text(
    "UPDATE articles SET content = :content, text = :text, "
    "text_hash = :text_hash, text_excerpt = :excerpt, status = :status "
    "WHERE id = :id"
)

ARTICLE_STATUS_UPDATE_SQL = text("UPDATE articles SET status = :status WHERE id = :id")


def _format_cleaned_authors(authors):
    """Convert a list of cleaned author names into a display string."""
    if not authors:
        return None

    normalized = [author.strip() for author in authors if author and author.strip()]
    if not normalized:
        return None

    return ", ".join(normalized)


def add_extraction_parser(subparsers):
    """Add extraction command parser to CLI."""
    extract_parser = subparsers.add_parser(
        "extract", help="Extract content from verified articles"
    )
    extract_parser.add_argument(
        "--limit", type=int, default=10, help="Articles per batch"
    )
    extract_parser.add_argument(
        "--batches",
        type=int,
        default=None,
        help="Number of batches (default: process all available)",
    )
    extract_parser.add_argument("--source", type=str, help="Limit to a specific source")
    extract_parser.add_argument("--dataset", type=str, help="Limit to a specific dataset slug")
    extract_parser.add_argument(
        "--no-exhaust-queue",
        dest="exhaust_queue",
        action="store_false",
        default=True,
        help="Stop after --batches instead of processing all available articles",
    )

    extract_parser.set_defaults(func=handle_extraction_command)


def handle_extraction_command(args) -> int:
    """Execute extraction command logic."""
    batches = getattr(args, "batches", None)  # None means "process all available"
    per_batch = getattr(args, "limit", 10)
    exhaust_queue = getattr(args, "exhaust_queue", True)  # Default to exhausting queue

    # Print to stdout immediately for visibility
    print(f"🚀 Starting content extraction...")
    if batches is None or exhaust_queue:
        print(f"   Mode: Process ALL available articles")
    else:
        print(f"   Batches: {batches}")
    print(f"   Articles per batch: {per_batch}")
    print()

    extractor = ContentExtractor()
    byline_cleaner = BylineCleaner()
    telemetry = ComprehensiveExtractionTelemetry()

    # Track hosts that return 403 responses within this run
    host_403_tracker = {}

    # Create a single DatabaseManager to reuse across all batches
    db = DatabaseManager()

    try:
        domains_for_cleaning = defaultdict(list)
        batch_num = 0
        total_processed = 0
        
        # Continue processing batches until no articles remain (or batch limit reached if specified)
        while True:
            batch_num += 1
            
            # If batches specified and exhaust_queue is False, respect the limit
            if batches is not None and not exhaust_queue and batch_num > batches:
                break
            
            # Apply batch size jitter if configured (e.g., BATCH_SIZE_JITTER=0.33 means ±33%)
            batch_size_jitter = float(os.getenv("BATCH_SIZE_JITTER", "0.0"))
            if batch_size_jitter > 0:
                jitter_amount = int(per_batch * batch_size_jitter)
                batch_size = max(1, per_batch + random.randint(-jitter_amount, jitter_amount))
            else:
                batch_size = per_batch
            
            print(f"📄 Processing batch {batch_num} ({batch_size} articles)...")
            result = _process_batch(
                args,
                extractor,
                byline_cleaner,
                telemetry,
                batch_size,
                batch_num,
                host_403_tracker,
                domains_for_cleaning,
                db=db,
            )
            
            articles_processed = result['processed']
            total_processed += articles_processed
            
            # Query remaining articles for progress visibility
            try:
                # Expire all objects and close transaction to get fresh count
                db.session.expire_all()
                db.session.commit()
                db.session.close()
                
                # Build count query matching the extraction filters
                dataset_slug = getattr(args, "dataset", None)
                if dataset_slug:
                    # Filter by specific dataset
                    query = text(
                        "SELECT COUNT(*) FROM candidate_links cl "
                        "WHERE cl.status = 'article' "
                        "AND cl.dataset_id = "
                        "(SELECT id FROM datasets WHERE slug = :dataset) "
                        "AND cl.id NOT IN "
                        "(SELECT candidate_link_id FROM articles "
                        "WHERE candidate_link_id IS NOT NULL)"
                    )
                    remaining_count = db.session.execute(
                        query, {"dataset": dataset_slug}
                    ).scalar() or 0
                else:
                    # Count across all cron-enabled datasets
                    query = text(
                        "SELECT COUNT(*) FROM candidate_links cl "
                        "WHERE cl.status = 'article' "
                        "AND (cl.dataset_id IS NULL OR cl.dataset_id IN "
                        "(SELECT id FROM datasets WHERE cron_enabled IS TRUE)) "
                        "AND cl.id NOT IN "
                        "(SELECT candidate_link_id FROM articles "
                        "WHERE candidate_link_id IS NOT NULL)"
                    )
                    remaining_count = db.session.execute(query).scalar() or 0
                
                print(
                    f"✓ Batch {batch_num} complete: {articles_processed} "
                    f"articles extracted ({remaining_count} remaining)"
                )
            except Exception:
                # Fallback if query fails
                print(
                    f"✓ Batch {batch_num} complete: "
                    f"{articles_processed} articles extracted"
                )
            
            if result.get('skipped_domains', 0) > 0:
                print(
                    f"  ⚠️  {result['skipped_domains']} domains "
                    f"skipped due to rate limits"
                )
            logger.info(f"Batch {batch_num}: {result}")
            
            # Stop if no articles were processed (queue is empty)
            if articles_processed == 0:
                print(f"📭 No more articles available to extract")
                break
            
            # Smart batch sleep: only pause if we processed articles from same domain repeatedly
            # If we rotated through domains, no pause needed (rate limiting handled per-domain)
            domains_processed = result.get('domains_processed', [])
            same_domain_consecutive = result.get('same_domain_consecutive', 0)
            unique_domains = len(set(domains_processed)) if domains_processed else 0
            skipped_domains = result.get('skipped_domains', 0)
            
            # Apply long batch sleep if:
            # 1. Same domain hit repeatedly (exhausted rotation), OR
            # 2. Only one domain processed AND no domains were skipped (true single-domain dataset)
            max_same_domain = int(os.getenv("MAX_SAME_DOMAIN_CONSECUTIVE", "3"))
            is_single_domain_dataset = unique_domains <= 1 and skipped_domains == 0
            needs_long_pause = (
                same_domain_consecutive >= max_same_domain or is_single_domain_dataset
            )
            
            if needs_long_pause:
                batch_sleep = float(os.getenv("BATCH_SLEEP_SECONDS", "0.1"))
                if batch_sleep > 0:
                    # Apply jitter to batch sleep
                    batch_jitter = float(os.getenv("BATCH_SLEEP_JITTER", "0.0"))
                    if batch_jitter > 0:
                        jitter_amount = batch_sleep * batch_jitter
                        actual_sleep = random.uniform(
                            batch_sleep - jitter_amount,
                            batch_sleep + jitter_amount
                        )
                    else:
                        actual_sleep = batch_sleep
                    
                    reason = (
                        f"same domain hit {same_domain_consecutive} times"
                        if same_domain_consecutive >= max_same_domain
                        else "single-domain dataset"
                    )
                    print(
                        f"   ⏸️  {reason.capitalize()} - "
                        f"waiting {actual_sleep:.0f}s..."
                    )
                    time.sleep(actual_sleep)
            elif unique_domains > 1 or skipped_domains > 0:
                # Rotated through multiple domains OR multiple domains available (but rate-limited)
                # Either way, minimal pause is sufficient
                short_pause = float(os.getenv("INTER_BATCH_MIN_PAUSE", "5.0"))
                if skipped_domains > 0:
                    print(
                        f"   ✓ Multiple domains available "
                        f"({skipped_domains} rate-limited) - "
                        f"minimal {short_pause:.0f}s pause"
                    )
                else:
                    print(
                        f"   ✓ Rotated through {unique_domains} domains - "
                        f"minimal {short_pause:.0f}s pause"
                    )
                time.sleep(short_pause)
            else:
                # Fallback: short pause
                short_pause = float(os.getenv("INTER_BATCH_MIN_PAUSE", "5.0"))
                time.sleep(short_pause)

        if domains_for_cleaning:
            print()
            print(f"🧹 Running post-extraction cleaning for {len(domains_for_cleaning)} domains...")
            _run_post_extraction_cleaning(domains_for_cleaning, db=db)
            print("✓ Cleaning complete")

        # Log driver usage stats before cleanup
        driver_stats = extractor.get_driver_stats()
        if driver_stats["has_persistent_driver"]:
            print()
            print(f"📊 ChromeDriver efficiency: {driver_stats['driver_reuse_count']} reuses, "
                  f"{driver_stats['driver_creation_count']} creations")
            logger.info(
                "ChromeDriver efficiency: %s reuses, %s creations",
                driver_stats["driver_reuse_count"],
                driver_stats["driver_creation_count"],
            )

        print()
        print(f"✅ Extraction completed successfully!")
        print(f"   Total batches processed: {batch_num}")
        print(f"   Total articles extracted: {total_processed}")
        return 0
    except Exception:
        logger.exception("Extraction failed")
        return 1
    finally:
        # Clean up persistent driver when job is complete
        extractor.close_persistent_driver()


def _process_batch(
    args,
    extractor,
    byline_cleaner,
    telemetry,
    per_batch,
    batch_num,
    host_403_tracker,
    domains_for_cleaning,
    db=None,
):
    """Process a single extraction batch with domain-aware rate limiting."""
    if db is None:
        db = DatabaseManager()
    session = db.session

    # Track domain failures and articles processed per domain in this batch
    domain_failures = {}  # domain -> consecutive_failures
    domain_article_count = {}  # domain -> articles_processed_in_batch
    domains_processed = []  # ordered list of domains processed
    last_domain = None
    same_domain_consecutive = 0
    max_failures_per_domain = 2
    max_articles_per_domain = int(os.getenv("MAX_ARTICLES_PER_DOMAIN_PER_BATCH", "3"))

    try:
        # Get articles with domain diversity to avoid rate-limit lockups
        q = """
        SELECT cl.id, cl.url, cl.source, cl.status, s.canonical_name
        FROM candidate_links cl
        LEFT JOIN sources s ON cl.source_id = s.id
        WHERE cl.status = 'article'
        AND cl.id NOT IN (
            SELECT candidate_link_id FROM articles
            WHERE candidate_link_id IS NOT NULL
        )
        ORDER BY RANDOM()  -- Use random order to mix domains
        LIMIT :limit_with_buffer
        """

        # Request more articles than we need to allow for domain skipping
        buffer_multiplier = 3
        params = {"limit_with_buffer": per_batch * buffer_multiplier}
        
        # Add dataset filter if specified
        if getattr(args, "dataset", None):
            q = q.replace(
                "WHERE cl.status = 'article'",
                """WHERE cl.status = 'article' 
                AND cl.dataset_id = (SELECT id FROM datasets WHERE slug = :dataset)""",
            )
            params["dataset"] = args.dataset
        else:
            # No explicit dataset - exclude cron-disabled datasets
            # Protects custom source lists from automated jobs
            q = q.replace(
                "WHERE cl.status = 'article'",
                """WHERE cl.status = 'article'
                AND (cl.dataset_id IS NULL
                     OR cl.dataset_id IN (
                         SELECT id FROM datasets WHERE cron_enabled IS TRUE
                     ))""",
            )
        
        # Add source filter if specified
        if getattr(args, "source", None):
            if "cl.dataset_id" in q:
                q = q.replace(
                    "AND cl.dataset_id",
                    "AND cl.source = :source AND cl.dataset_id",
                )
            else:
                q = q.replace(
                    "WHERE cl.status = 'article'",
                    "WHERE cl.status = 'article' AND cl.source = :source",
                )
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

            # Check if we've already processed max articles from this domain in this batch
            current_domain_count = domain_article_count.get(domain, 0)
            if current_domain_count >= max_articles_per_domain:
                logger.debug(
                    "Skipping %s - domain %s hit max %d articles per batch",
                    url,
                    domain,
                    max_articles_per_domain,
                )
                continue

            # Skip domains that have failed too many times
            if domain in skipped_domains:
                logger.debug(
                    "Skipping %s - domain %s temporarily blocked",
                    url,
                    domain,
                )
                continue

            # Check if domain is currently rate limited by extractor (CAPTCHA backoff)
            if extractor._check_rate_limit(domain):
                logger.info(
                    "Skipping %s - domain %s is rate limited (backoff active)",
                    url,
                    domain,
                )
                skipped_domains.add(domain)
                continue

            operation_id = f"ex_{batch_num}_{url_id}"
            article_id = str(uuid.uuid4())
            publisher = canonical_name or source
            metrics = ExtractionMetrics(
                operation_id,
                article_id,
                url,
                publisher,
            )

            try:
                content = extractor.extract_content(url, metrics=metrics)
                detection_payload = None

                if content and content.get("title"):
                    # Track successful extraction from this domain
                    domain_article_count[domain] = domain_article_count.get(domain, 0) + 1
                    
                    # Track domain rotation
                    if domain != last_domain:
                        if domain not in domains_processed:
                            domains_processed.append(domain)
                        same_domain_consecutive = 0
                        last_domain = domain
                    else:
                        same_domain_consecutive += 1
                    
                    # Reset failure count on success
                    if domain in domain_failures:
                        domain_failures[domain] = 0

                    # Clean author and check for wire services
                    raw_author = content.get("author")
                    cleaned_author = None
                    wire_service_info = None
                    article_status = "extracted"
                    byline_result = None

                    if raw_author:
                        # Get full JSON result with wire service detection
                        byline_result = byline_cleaner.clean_byline(
                            raw_author,
                            return_json=True,
                            source_name=source,
                            candidate_link_id=str(url_id),
                        )

                        # Extract cleaned authors and wire service information
                        cleaned_list = byline_result.get("authors", [])
                        wire_services = byline_result.get("wire_services", [])
                        is_wire_content = byline_result.get(
                            "is_wire_content",
                            False,
                        )

                        # Store cleaned authors as human-readable string
                        cleaned_author = _format_cleaned_authors(cleaned_list)

                        # Handle wire service detection
                        if is_wire_content and wire_services:
                            article_status = "wire"
                            wire_service_info = json.dumps(wire_services)
                            logger.info(
                                "Wire service '%s': authors=%s, wire=%s",
                                raw_author,
                                cleaned_list,
                                wire_services,
                            )
                        else:
                            logger.info(
                                "Author cleaning: '%s' → '%s'",
                                raw_author,
                                cleaned_list,
                            )

                    metadata_value = content.get("metadata") or {}
                    if not isinstance(metadata_value, dict):
                        metadata_value = {}

                    if byline_result:
                        metadata_value["byline"] = byline_result

                    if article_status == "extracted":
                        detector = _get_content_type_detector()
                        detection_result = detector.detect(
                            url=url,
                            title=content.get("title"),
                            metadata=metadata_value,
                            content=content.get("content"),
                        )
                        if detection_result:
                            article_status = detection_result.status
                            detection_payload = {
                                "status": detection_result.status,
                                "confidence": detection_result.confidence,
                                "confidence_score": (detection_result.confidence_score),
                                "reason": detection_result.reason,
                                "evidence": detection_result.evidence,
                                "version": detection_result.detector_version,
                                "detected_at": datetime.utcnow().isoformat(),
                            }
                            metadata_value["content_type_detection"] = detection_payload

                    # Update metadata if we added detection info
                    if metadata_value:
                        content["metadata"] = metadata_value

                    now = datetime.utcnow()
                    content_text = content.get("content", "")
                    text_hash = (
                        calculate_content_hash(content_text) if content_text else None
                    )

                    metrics.set_content_type_detection(detection_payload)
                    metrics.finalize(content or {})

                    session.execute(
                        ARTICLE_INSERT_SQL,
                        {
                            "id": article_id,
                            "candidate_link_id": str(url_id),
                            "url": url,
                            "title": content.get("title"),
                            "author": cleaned_author,
                            "publish_date": content.get("publish_date"),
                            "content": content_text,
                            "text": content_text,  # Same as content
                            "status": article_status,
                            "metadata": json.dumps(content.get("metadata", {})),
                            "wire": wire_service_info,
                            "extracted_at": now.isoformat(),
                            "created_at": now.isoformat(),
                            "text_hash": text_hash,
                        },
                    )
                    session.execute(
                        CANDIDATE_STATUS_UPDATE_SQL,
                        {"status": article_status, "id": str(url_id)},
                    )
                    session.commit()
                    telemetry.record_extraction(metrics)
                    domains_for_cleaning[domain].append(article_id)
                    processed += 1
                else:
                    # Track failure for domain awareness
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1

                    # If domain has failed too many times,
                    # skip it for rest of batch
                    if domain_failures[domain] >= max_failures_per_domain:
                        logger.warning(
                            "Domain %s failed %s times; skipping batch",
                            domain,
                            domain_failures[domain],
                        )
                        skipped_domains.add(domain)

                    # For rate limit errors, also add to skipped domains
                    # immediately
                    error_msg = content.get("error", "") if content else ""
                    if "Rate limited" in error_msg or "429" in error_msg:
                        logger.warning(
                            "Rate limit detected for %s; skipping URLs",
                            domain,
                        )
                        skipped_domains.add(domain)

                    metrics.error_message = "No title extracted"
                    metrics.error_type = "extraction_failure"
                    metrics.set_content_type_detection(detection_payload)
                    metrics.finalize(content or {})
                    telemetry.record_extraction(metrics)

            except NotFoundError as e:
                # 404/410 - permanently mark as not found and continue to next URL
                logger.info("URL not found (404/410): %s", url)
                try:
                    session.execute(
                        CANDIDATE_STATUS_UPDATE_SQL,
                        {"status": "404", "id": str(url_id)},
                    )
                    session.commit()
                except Exception:
                    logger.exception("Failed to mark URL as 404: %s", url)
                    session.rollback()

                metrics.error_message = str(e)
                metrics.error_type = "not_found"
                metrics.finalize({})
                telemetry.record_extraction(metrics)
                # Don't increment domain failures for 404s - it's the URL, not the domain
                continue

            except Exception as e:
                # Check for rate limit in exception
                error_str = str(e)
                if "Rate limited" in error_str or "429" in error_str:
                    logger.warning(
                        "Rate limit exception for %s, skipping remaining URLs",
                        domain,
                    )
                    skipped_domains.add(domain)
                    domain_failures[domain] = max_failures_per_domain
                    # Cap at max failures once rate limited
                else:
                    # Track other failures for domain awareness
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1
                    if domain_failures[domain] >= max_failures_per_domain:
                        logger.warning(
                            "Domain %s failed %s times; skipping batch",
                            domain,
                            domain_failures[domain],
                        )
                        skipped_domains.add(domain)

                metrics.error_message = str(e)
                metrics.error_type = "exception"
                metrics.finalize({})
                telemetry.record_extraction(metrics)
                session.rollback()

                # Check for 404/410 responses and mark them as dead
                status_code = getattr(metrics, "http_status_code", None)
                host = getattr(metrics, "host", None)

                if status_code in (404, 410):
                    # Permanently mark as 404 - page doesn't exist
                    try:
                        session.execute(
                            CANDIDATE_STATUS_UPDATE_SQL,
                            {"status": "404", "id": str(url_id)},
                        )
                        session.commit()
                        logger.info(
                            "Marked URL as 404 (not found): %s",
                            url,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark URL as 404: %s",
                            url,
                        )
                        session.rollback()

                # Check if this was a 403 response and track it
                elif status_code == 403 and host:
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
                                PAUSE_CANDIDATE_LINKS_SQL,
                                {
                                    "status": "paused",
                                    "error": reason,
                                    "host_like": host_like,
                                    "host": host,
                                },
                            )
                            session.commit()
                            logger.warning(
                                "Auto-paused host %s after repeated 403s",
                                host,
                            )
                        except Exception:
                            logger.exception(
                                "Failed to pause candidate links for %s",
                                host,
                            )
                            session.rollback()

        # Log domain skipping summary
        if skipped_domains:
            skipped_list = ", ".join(sorted(skipped_domains))
            logger.info(
                "Batch %s skipped domains due to failures: %s",
                batch_num,
                skipped_list,
            )

        if domain_failures:
            failure_summary = {
                key: value for key, value in domain_failures.items() if value > 0
            }
            if failure_summary:
                logger.info(
                    "Batch %s domain failure counts: %s",
                    batch_num,
                    failure_summary,
                )

        return {
            "processed": processed,
            "skipped_domains": len(skipped_domains),
            "domains_processed": domains_processed,
            "same_domain_consecutive": same_domain_consecutive,
            "domain_article_count": domain_article_count,
        }

    finally:
        session.close()


def _run_post_extraction_cleaning(domains_to_articles, db=None):
    """Trigger content cleaning for recently extracted articles."""
    if db is None:
        db = DatabaseManager()
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=True, db=db)
    session = db.session
    articles_for_entities: set[str] = set()

    try:
        for domain, article_ids in domains_to_articles.items():
            if not article_ids:
                continue

            try:
                cleaner.analyze_domain(domain)
            except Exception as e:
                # Domain analysis is optional optimization - skip if tables don't exist
                error_str = str(e)
                if "no such table: articles" in error_str:
                    logger.debug(
                        "Skipping domain analysis for %s (table doesn't exist)",
                        domain
                    )
                else:
                    logger.warning(
                        "Domain analysis failed for %s: %s", domain, error_str
                    )
                # Continue with cleaning even if analysis fails

            for article_id in article_ids:
                try:
                    row = session.execute(
                        text("SELECT content, status FROM articles WHERE id = :id"),
                        {"id": article_id},
                    ).fetchone()

                    if not row:
                        continue

                    original_content = row[0] or ""
                    current_status = row[1] or "extracted"
                    if not original_content.strip():
                        continue

                    cleaned_content, metadata = cleaner.process_single_article(
                        text=original_content,
                        domain=domain,
                        article_id=article_id,
                    )

                    wire_detected = metadata.get("wire_detected")
                    locality_assessment = metadata.get("locality_assessment") or {}
                    is_local_wire = bool(
                        wire_detected
                        and locality_assessment
                        and locality_assessment.get("is_local")
                    )

                    new_status = current_status

                    if is_local_wire:
                        if current_status in {"wire", "cleaned", "extracted"}:
                            new_status = "local"
                    elif wire_detected:
                        if current_status == "extracted":
                            new_status = "wire"
                    elif current_status == "extracted":
                        new_status = "cleaned"

                    status_changed = new_status != current_status

                    article_updated = False

                    if cleaned_content != original_content:
                        new_hash = (
                            calculate_content_hash(cleaned_content)
                            if cleaned_content
                            else None
                        )
                        excerpt = cleaned_content[:500] if cleaned_content else None

                        session.execute(
                            ARTICLE_UPDATE_SQL,
                            {
                                "content": cleaned_content,
                                "text": cleaned_content,
                                "text_hash": new_hash,
                                "excerpt": excerpt,
                                "status": new_status,
                                "id": article_id,
                            },
                        )

                        logger.info(
                            "Cleaning removed %s chars for article %s (%s)",
                            metadata.get("chars_removed"),
                            article_id,
                            domain,
                        )

                        if status_changed:
                            logger.info(
                                "Updated article %s (%s) status: %s -> %s",
                                article_id,
                                domain,
                                current_status,
                                new_status,
                            )

                        article_updated = True
                    elif status_changed:
                        session.execute(
                            ARTICLE_STATUS_UPDATE_SQL,
                            {"status": new_status, "id": article_id},
                        )
                        logger.info(
                            "Updated article %s (%s) status: %s -> %s",
                            article_id,
                            domain,
                            current_status,
                            new_status,
                        )
                        article_updated = True

                    if article_updated:
                        _commit_with_retry(session)

                    status_for_entities = (new_status or "").lower()
                    disallowed_statuses = {"wire", "opinion", "obituary"}
                    if status_for_entities not in disallowed_statuses:
                        # Always queue non-wire articles for entity
                        # extraction so locality comparison data stays fresh
                        # even when content hashes remain unchanged.
                        articles_for_entities.add(article_id)
                except Exception:
                    session.rollback()
                    logger.exception(
                        "Failed to clean article %s for domain %s",
                        article_id,
                        domain,
                    )

    except Exception:
        session.rollback()
        logger.exception("Failed to complete post-extraction content cleaning")
    finally:
        session.close()

    if articles_for_entities:
        _run_article_entity_extraction(articles_for_entities, db=db)


def _run_article_entity_extraction(article_ids: Iterable[str], db=None) -> None:
    ids = {article_id for article_id in article_ids if article_id}
    if not ids:
        return

    extractor = _get_entity_extractor()
    logger.info("Running entity extraction for %d articles", len(ids))

    if db is None:
        db = DatabaseManager()
    session = db.session

    try:
        articles = (
            session.query(Article)
            .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
            .filter(Article.id.in_(ids))
            .all()
        )

        skip_statuses = {"wire", "opinion", "obituary"}

        for article in articles:
            status_value = (article.status or "").lower()
            if status_value in skip_statuses:
                continue

            candidate = article.candidate_link
            if candidate:
                source_id = cast(str | None, candidate.source_id)
                dataset_id = cast(str | None, candidate.dataset_id)
            else:
                source_id = None
                dataset_id = None

            raw_text = article.text or article.content
            text_value = raw_text if isinstance(raw_text, str) else None
            gazetteer_rows = get_gazetteer_rows(
                session,
                source_id,
                dataset_id,
            )
            entities = extractor.extract(
                text_value,
                gazetteer_rows=gazetteer_rows,
            )
            entities = attach_gazetteer_matches(
                session,
                source_id,
                dataset_id,
                entities,
                gazetteer_rows=gazetteer_rows,
            )
            save_article_entities(
                session,
                cast(str, article.id),
                entities,
                extractor.extractor_version,
                cast(str | None, article.text_hash),
            )
    except Exception:
        session.rollback()
        logger.exception("Entity extraction pipeline failed")
    finally:
        session.close()
