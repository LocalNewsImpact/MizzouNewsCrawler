"""
Extraction command module for the modular CLI.
"""

import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import text

from src.crawler import ContentExtractor
from src.models.database import DatabaseManager, safe_session_execute
from src.utils.byline_cleaner import BylineCleaner

logger = logging.getLogger(__name__)


def add_extraction_parser(subparsers):
    """Add extraction command parser to CLI."""
    extract_parser = subparsers.add_parser(
        "extract", help="Extract content from verified articles"
    )
    extract_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Limit number of articles to extract per batch",
    )
    extract_parser.add_argument(
        "--batches",
        type=int,
        default=1,
        help="Number of batches to process (default: 1)",
    )
    extract_parser.add_argument(
        "--articles-only",
        action="store_true",
        default=True,
        help="Only extract URLs with 'article' status (default: True)",
    )
    extract_parser.add_argument(
        "--source", type=str, help="Extract from specific source only"
    )


def handle_extraction_command(args) -> int:
    """Handle the extraction command."""
    try:
        batches = getattr(args, "batches", 1)
        per_batch = args.limit
        total_articles = batches * per_batch

        logger.info(
            "Starting extraction: %s batches of %s articles each (total: %s)",
            batches,
            per_batch,
            total_articles,
        )

        # Overall statistics tracking
        overall_stats = {
            "total_processed": 0,
            "total_successful": 0,
            "total_failed": 0,
            "batches_completed": 0,
        }

        db = DatabaseManager()

        # Initialize extractor and byline cleaner once for all batches
        extractor = ContentExtractor()
        byline_cleaner = BylineCleaner()

        print(
            f"\n🚀 Starting batch extraction: {batches} batches × {per_batch} articles"
        )
        print("=" * 60)

        for batch_num in range(1, batches + 1):
            print(f"\n📦 BATCH {batch_num}/{batches}")
            print("-" * 30)

            session = db.session

            # Build query for articles to extract
            query = text(
                """
                SELECT id, url, source, status
                FROM candidate_links
                WHERE status = 'article'
                AND id NOT IN (
                    SELECT candidate_link_id
                    FROM articles
                    WHERE candidate_link_id IS NOT NULL
                )
                """
            )

            if hasattr(args, "source") and args.source:
                query = text(f"{query.text} AND source = '{args.source}'")

            query = text(f"{query.text} ORDER BY created_at DESC LIMIT {per_batch}")

            result = safe_session_execute(session, query)
            articles = result.fetchall()

            if not articles:
                print(f"No articles found for batch {batch_num}")
                session.close()
                break

            print(f"Found {len(articles)} articles for batch {batch_num}")

            # Process this batch
            batch_stats = _process_batch(
                articles, extractor, byline_cleaner, session, batch_num
            )

            # Update overall statistics
            overall_stats["total_processed"] += batch_stats["processed"]
            overall_stats["total_successful"] += batch_stats["successful"]
            overall_stats["total_failed"] += batch_stats["failed"]
            overall_stats["batches_completed"] += 1

            session.close()

            # Show batch summary
            success_rate = (
                (batch_stats["successful"] / batch_stats["processed"]) * 100
                if batch_stats["processed"] > 0
                else 0
            )
            print(f"\n✅ Batch {batch_num} complete:")
            print(f"   Processed: {batch_stats['processed']}")
            print(f"   Successful: {batch_stats['successful']}")
            print(f"   Failed: {batch_stats['failed']}")
            print(f"   Success Rate: {success_rate:.1f}%")

            # Show user agent rotation stats
            rotation_stats = extractor.get_rotation_stats()
            print(f"   Domains accessed: {rotation_stats['total_domains_accessed']}")

            # Brief pause between batches
            if batch_num < batches:
                print(f"\n⏳ Pausing briefly before batch {batch_num + 1}...")
                time.sleep(2)

        # Final summary
        print("\n🎯 EXTRACTION COMPLETE")
        print("=" * 60)
        overall_success_rate = (
            (overall_stats["total_successful"] / overall_stats["total_processed"]) * 100
            if overall_stats["total_processed"] > 0
            else 0
        )
        print(f"Batches completed: {overall_stats['batches_completed']}/{batches}")
        print(f"Total articles processed: {overall_stats['total_processed']}")
        print(f"Total successful: {overall_stats['total_successful']}")
        print(f"Total failed: {overall_stats['total_failed']}")
        print(f"Overall success rate: {overall_success_rate:.1f}%")

        # Show final rotation statistics
        rotation_stats = extractor.get_rotation_stats()
        print("\nUser Agent Rotation Summary:")
        print(f"  Total domains: {rotation_stats['total_domains_accessed']}")
        print(f"  Active sessions: {rotation_stats['active_sessions']}")
        for domain, count in rotation_stats["request_counts"].items():
            print(f"  {domain}: {count} requests")

        return 0

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return 1


def _process_batch(articles, extractor, byline_cleaner, session, batch_num):
    """Process a single batch of articles."""

    print(f"Found {len(articles)} articles for extraction")

    extracted_count = 0
    failed_count = 0
    partial_count = 0

    # Track field completion for quality reporting
    field_stats = {
        "title": {"present": 0, "total": 0},
        "content": {"present": 0, "total": 0},
        "author": {"present": 0, "total": 0},
        "publish_date": {"present": 0, "total": 0},
        "metadata": {"present": 0, "total": 0},
    }

    # Track extraction method usage
    method_stats = {
        "newspaper4k": {"used": 0, "fields_extracted": 0},
        "beautifulsoup": {"used": 0, "fields_extracted": 0},
        "selenium": {"used": 0, "fields_extracted": 0},
    }

    for index, article in enumerate(articles, 1):
        url_id, url, source, status = article

        print(f"\n[{index}/{len(articles)}] Processing article from {source}")
        print(f"  URL: {url[:80]}{'...' if len(url) > 80 else ''}")
        print("  Starting extraction with three-tier fallback system...")

        try:
            start_time = time.time()
            content_data = extractor.extract_content(url)
            extraction_time = time.time() - start_time

            print(f"  Extraction completed in {extraction_time:.1f}s")

            if content_data and content_data.get("title"):
                # Track field completion for quality reporting
                field_stats["title"]["total"] += 1
                field_stats["content"]["total"] += 1
                field_stats["author"]["total"] += 1
                field_stats["publish_date"]["total"] += 1
                field_stats["metadata"]["total"] += 1

                fields_present = 0
                total_fields = 5

                if content_data.get("title"):
                    field_stats["title"]["present"] += 1
                    fields_present += 1
                if (
                    content_data.get("content")
                    and content_data.get("content", "").strip()
                ):
                    field_stats["content"]["present"] += 1
                    fields_present += 1
                if content_data.get("author"):
                    field_stats["author"]["present"] += 1
                    fields_present += 1
                if content_data.get("publish_date"):
                    field_stats["publish_date"]["present"] += 1
                    fields_present += 1
                if content_data.get("metadata"):
                    field_stats["metadata"]["present"] += 1
                    fields_present += 1

                completion_percentage = (fields_present / total_fields) * 100

                if completion_percentage == 100.0:
                    status_icon = "✅ Success"
                    status_text = "Complete"
                else:
                    status_icon = "⚠️  Partial"
                    status_text = f"{completion_percentage:.0f}% complete"

                print(
                    f"  {status_icon}: {content_data['title'][:50]}... ({status_text})"
                )

                metadata = content_data.get("metadata", {}) or {}
                extraction_methods = metadata.get("extraction_methods", {})
                if extraction_methods:
                    for field_name, method in extraction_methods.items():
                        if method in method_stats:
                            method_stats[method]["fields_extracted"] += 1

                    for method in set(extraction_methods.values()):
                        if method in method_stats:
                            method_stats[method]["used"] += 1

                    methods_summary = [
                        f"{field_name}:{method}"
                        for field_name, method in extraction_methods.items()
                    ]
                    if methods_summary:
                        print(f"    Methods: {', '.join(methods_summary)}")

                try:
                    raw_author = content_data.get("author")
                    cleaned_author = None
                    if raw_author:
                        cleaned_author = byline_cleaner.clean_byline(raw_author)
                        logger.info(
                            "Author cleaning: '%s' → '%s'",
                            raw_author,
                            cleaned_author,
                        )

                    article_id = str(uuid.uuid4())
                    now = datetime.utcnow()

                    safe_session_execute(
                        session,
                        text(
                            """
                            INSERT INTO articles (
                                id,
                                candidate_link_id,
                                url,
                                title,
                                author,
                                publish_date,
                                content,
                                text,
                                status,
                                metadata,
                                extracted_at,
                                created_at,
                                extraction_version
                            ) VALUES (
                                :id,
                                :candidate_link_id,
                                :url,
                                :title,
                                :author,
                                :publish_date,
                                :content,
                                :text,
                                :status,
                                :metadata,
                                :extracted_at,
                                :created_at,
                                :extraction_version
                            )
                            """
                        ),
                        {
                            "id": article_id,
                            "candidate_link_id": str(url_id),
                            "url": url,
                            "title": content_data.get("title"),
                            "author": cleaned_author,
                            "publish_date": content_data.get("publish_date"),
                            "content": content_data.get("content"),
                            "text": content_data.get("content"),
                            "status": "extracted",
                            "metadata": str(metadata),
                            "extracted_at": now.isoformat(),
                            "created_at": now.isoformat(),
                            "extraction_version": "v1.0",
                        },
                    )

                    safe_session_execute(
                        session,
                        text(
                            "UPDATE candidate_links SET status = 'extracted' "
                            "WHERE id = :url_id"
                        ),
                        {"url_id": url_id},
                    )

                    session.commit()

                    if completion_percentage == 100.0:
                        extracted_count += 1
                    else:
                        partial_count += 1

                except Exception as db_error:
                    session.rollback()
                    print(f"  ❌ Database error: {db_error}")
                    failed_count += 1

            else:
                print("  ❌ Failed: No content extracted")
                failed_count += 1

        except Exception as exc:  # pragma: no cover - log and continue
            print(f"  ❌ Error: {exc}")
            failed_count += 1

    total_processed = extracted_count + partial_count + failed_count

    print("\nExtraction complete:")
    print(f"  ✅ Successfully extracted: {extracted_count}")
    print(f"  ⚠️  Partially extracted: {partial_count}")
    print(f"  ❌ Failed: {failed_count}")
    print(f"  📊 Total processed: {total_processed}")

    if extracted_count > 0:
        print("\n📊 Field Completion Report:")
        print("=" * 40)
        for field, stats in field_stats.items():
            if stats["total"] > 0:
                percentage = (stats["present"] / stats["total"]) * 100
                print(
                    f"  {field.capitalize():>12}: "
                    f"{stats['present']:>3}/{stats['total']:<3} "
                    f"({percentage:>5.1f}%)"
                )

        total_fields = sum(stats["total"] for stats in field_stats.values())
        total_present = sum(stats["present"] for stats in field_stats.values())
        overall_percentage = (
            (total_present / total_fields) * 100 if total_fields > 0 else 0
        )
        print("-" * 40)
        print(
            f"  {'Overall Quality':>12}: "
            f"{total_present:>3}/{total_fields:<3} "
            f"({overall_percentage:>5.1f}%)"
        )

        print("\n🔧 Extraction Method Usage:")
        print("=" * 40)
        for method, stats in method_stats.items():
            if stats["used"] > 0:
                avg_fields = (
                    stats["fields_extracted"] / stats["used"]
                    if stats["used"] > 0
                    else 0
                )
                print(
                    f"  {method.capitalize():>12}: "
                    f"{stats['used']:>2} URLs, "
                    f"{stats['fields_extracted']:>2} fields "
                    f"({avg_fields:.1f} avg/URL)"
                )

    return {
        "processed": total_processed,
        "successful": extracted_count,
        "failed": failed_count,
        "partial": partial_count,
    }
