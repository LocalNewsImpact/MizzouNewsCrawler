#!/usr/bin/env python3
"""
Backfill script to re-classify articles that may use CITY, State dateline formats.
"""

import argparse
import csv
import logging
from collections import Counter
from pathlib import Path

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from src.models import Article, CandidateLink, Source
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MANUAL_BASE_DOMAINS = {
    "abc17news.com",
    "komu.com",
    "krcgtv.com",
    "fox22now.com",
    "zimmerradio.com",
    "fox2now.com",
    "fox4kc.com",
    "kctv5.com",
    "kfvs12.com",
    "kmbc.com",
    "kmov.com",
    "koamnewsnow.com",
    "ksdk.com",
    "ky3.com",
    "ozarksfirst.com",
    "fourstateshomepage.com",
    "kbia.org",
    "kcur.org",
    "ksmu.org",
    "krcu.org",
    "ktts.com",
    "news.stlpublicradio.org",
    "newstalkkzrg.com",
    "929thebeat.com",
    "949kcmo.com",
    "audacy.com",
    "kprs.com",
    "legends1063.fm",
    "mymoinfo.com",
    "northwestmoinfo.com",
    "redlatinastl.com",
    "missouriindependent.com",
    "columbiamissourian.com",
    "columbiatribune.com",
    "stltoday.com",
    "kansascity.com",
    "news-leader.com",
    "joplinglobe.com",
    "newstribune.com",
    "semissourian.com",
}

BROADCAST_TYPES = (
    "video_broadcast",
    "audio_broadcast",
    "television",
    "radio",
)


def _article_has_labels(article: Article) -> bool:
    """Return True if the article already carries an ML label."""

    if getattr(article, "status", None) == "labeled":
        return True

    if getattr(article, "primary_label", None):
        return True

    if getattr(article, "label_version", None):
        return True

    return False


def _determine_local_status(
    article: Article,
    current_status: str | None,
) -> tuple[str | None, str]:
    """Map detector "local" outcome to pipeline status and reason tag."""

    if current_status == "labeled" or _article_has_labels(article):
        return "labeled", "local_already_labeled"

    # Statuses that should revert to cleaned when detector no longer sees wire
    resettable_statuses = {
        "local",
        "wire",
        "wire+local",
        "wire_local",
        "opinion",
        "opinions",
        "obituary",
        "obits",
        None,
    }

    if current_status in resettable_statuses:
        return "cleaned", "local_needs_classification"

    # Leave everything else as-is (e.g., extracted, cleaned already)
    return current_status, "local_no_change"


def _write_transition_csv(
    records: list[dict[str, str]],
    target_path: str,
) -> None:
    """Persist collected transition records to CSV on disk."""

    path = Path(target_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "article_id",
        "url",
        "source",
        "title",
        "old_status",
        "new_status",
        "reason",
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    logger.info(
        "Exported %d transition records to %s", len(records), target_path
    )


def _normalize_domain(domain: str) -> str:
    domain = (domain or "").lower().strip()
    if domain.startswith("http://"):
        domain = domain[7:]
    elif domain.startswith("https://"):
        domain = domain[8:]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/")[0]


def _expand_domain_variants(domains: set[str]) -> set[str]:
    variants: set[str] = set()
    for domain in domains:
        base = _normalize_domain(domain)
        if not base:
            continue
        variants.add(base)
        variants.add(f"www.{base}")
    return variants


def load_target_domains(
    session: Session,
    extra_domains: list[str] | None = None,
) -> list[str]:
    domains: set[str] = set(MANUAL_BASE_DOMAINS)

    # Pull additional broadcaster domains from the sources table
    result = session.execute(
        select(Source.host)
        .where(Source.host.is_not(None))
        .where(Source.host != "")
        .where(Source.type.in_(BROADCAST_TYPES))
    )

    for host in result.scalars():
        domains.add(_normalize_domain(host))

    # Include domains derived from ContentTypeDetector callsign map
    callsign_domains = getattr(ContentTypeDetector, "_CALLSIGN_DOMAINS", {})
    for values in callsign_domains.values():
        for host in values:
            domains.add(_normalize_domain(host))

    if extra_domains:
        for host in extra_domains:
            domains.add(_normalize_domain(host))

    # Filter out any empty strings
    return sorted(domain for domain in domains if domain)


def backfill_classification(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    extra_domains: list[str] | None = None,
    sample_size: int = 50,
    batch_size: int = 5000,
    all_sources: bool = False,
    wire_cleaned_export: str | None = None,
    wire_labeled_export: str | None = None,
) -> None:
    db = DatabaseManager()
    detector = ContentTypeDetector()

    wire_cleaned_records: list[dict[str, str]] | None = (
        [] if wire_cleaned_export else None
    )
    wire_labeled_records: list[dict[str, str]] | None = (
        [] if wire_labeled_export else None
    )

    with db.get_session() as session:
        if all_sources:
            target_domains: list[str] = []
            domain_variants: set[str] = set()
            normalized_variants: tuple[str, ...] = ()
            logger.info("Starting backfill for ALL sources (no domain filter)")
        else:
            target_domains = load_target_domains(session, extra_domains)
            if not target_domains:
                logger.warning("No target domains found. Exiting.")
                return

            domain_variants = _expand_domain_variants(set(target_domains))
            normalized_variants = tuple(
                variant.lower() for variant in sorted(domain_variants)
            )

            logger.info(
                "Starting backfill for %d base domains (%d variants)",
                len(target_domains),
                len(normalized_variants),
            )

        if dry_run:
            logger.info("DRY RUN MODE: No changes will be saved")

        stmt = (
            select(Article, CandidateLink.url, CandidateLink.source)
            .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
            .order_by(Article.extracted_at.desc(), Article.id.desc())
        )

        if not all_sources:
            source_condition = func.lower(CandidateLink.source).in_(
                normalized_variants
            )

            url_conditions = [
                CandidateLink.url.ilike(f"%{domain}%")
                for domain in domain_variants
            ]

            if url_conditions:
                stmt = stmt.where(or_(source_condition, or_(*url_conditions)))
            else:
                stmt = stmt.where(source_condition)

        processed_count = 0
        updated_counter: Counter[tuple[str | None, str | None]] = Counter()
        domain_counter: Counter[str] = Counter()
        sample_changes: list[str] = []
        sample_unchanged: list[str] = []
        sample_cap = max(sample_size, 0)
        remaining = limit
        batch_index = 0
        last_cursor: tuple | None = None

        while True:
            if remaining is not None and remaining <= 0:
                break

            current_limit = batch_size
            if remaining is not None:
                current_limit = min(current_limit, remaining)

            batch_stmt = stmt.limit(current_limit)

            if last_cursor is not None:
                last_extracted_at, last_id = last_cursor
                batch_stmt = batch_stmt.where(
                    or_(
                        Article.extracted_at < last_extracted_at,
                        and_(
                            Article.extracted_at == last_extracted_at,
                            Article.id < last_id,
                        ),
                    )
                )

            batch_results = session.execute(
                batch_stmt.execution_options(stream_results=True)
            ).all()

            if not batch_results:
                break

            batch_index += 1
            logger.info(
                "Processing batch %d (%d rows)...",
                batch_index,
                len(batch_results),
            )

            for article, url, source_name in batch_results:
                processed_count += 1

                text_content = (article.text or "").strip()
                metadata = getattr(article, "meta", {}) or {}
                title = getattr(article, "title", None)
                author = getattr(article, "author", None)

                result = detector.detect(
                    url=url,
                    title=title,
                    metadata=metadata,
                    content=text_content,
                    author=author,
                )

                old_status = getattr(article, "status", None)
                new_status: str | None
                reason_tag: str | None

                if result is None:
                    new_status, reason_tag = _determine_local_status(
                        article,
                        old_status,
                    )
                else:
                    new_status = result.status
                    reason_tag = result.reason

                    if not new_status or new_status == "local":
                        fallback_status, fallback_reason = _determine_local_status(
                            article,
                            old_status,
                        )
                        new_status = fallback_status
                        if not reason_tag:
                            reason_tag = fallback_reason

                if not new_status:
                    continue

                if reason_tag is None:
                    reason_tag = "unknown_reason"

                domain_key = _normalize_domain(source_name)

                if new_status and old_status != new_status:
                    updated_counter[(old_status, new_status)] += 1
                    if domain_key:
                        domain_counter[domain_key] += 1

                    if (
                        wire_cleaned_records is not None
                        and old_status == "wire"
                        and new_status == "cleaned"
                    ):
                        wire_cleaned_records.append(
                            {
                                "article_id": getattr(article, "id", ""),
                                "url": url,
                                "source": source_name,
                                "title": getattr(article, "title", "") or "",
                                "old_status": old_status or "",
                                "new_status": new_status,
                                "reason": reason_tag,
                            }
                        )

                    if (
                        wire_labeled_records is not None
                        and old_status == "wire"
                        and new_status == "labeled"
                    ):
                        wire_labeled_records.append(
                            {
                                "article_id": getattr(article, "id", ""),
                                "url": url,
                                "source": source_name,
                                "title": getattr(article, "title", "") or "",
                                "old_status": old_status or "",
                                "new_status": new_status,
                                "reason": reason_tag,
                            }
                        )

                    message = (
                        f"[{source_name}] {url}\n"
                        f"  Old: {old_status or 'None'} -> New: {new_status}"
                        f" | Reason: {reason_tag}"
                    )
                    if dry_run and len(sample_changes) < sample_cap:
                        sample_changes.append(message)

                    if not dry_run:
                        article.status = new_status
                else:
                    if dry_run and len(sample_unchanged) < sample_cap:
                        sample_unchanged.append(
                            f"[{source_name}] {url}\n"
                            f"  Unchanged: {old_status or 'None'}"
                        )

            last_article = batch_results[-1][0]
            last_cursor = (last_article.extracted_at, last_article.id)

            if remaining is not None:
                remaining -= len(batch_results)

            if not dry_run:
                session.commit()

        total_updates = sum(updated_counter.values())

        if dry_run:
            print("\n=== DRY RUN SUMMARY ===")
            print(f"Total articles checked: {processed_count}")
            print(f"Would update: {total_updates}")
            print(f"Unique domains impacted: {len(domain_counter)}")

            if sample_changes:
                print("\n-- Sample Updates --")
                for entry in sample_changes:
                    print(entry)

            if sample_unchanged:
                print("\n-- Sample Unchanged --")
                for entry in sample_unchanged:
                    print(entry)

            if updated_counter:
                print("\n-- Change Breakdown --")
                for (old_type, new_type), count in updated_counter.most_common():
                    print(f"{old_type or 'None'} -> {new_type}: {count}")

            if domain_counter:
                print("\n-- Top Domains --")
                for domain, count in domain_counter.most_common(20):
                    print(f"{domain}: {count}")
        else:
            session.commit()
            logger.info(
                "Backfill complete. Updated %d articles out of %d processed.",
                total_updates,
                processed_count,
            )
            if updated_counter:
                logger.info(
                    "Change breakdown: %s",
                    {
                        f"{old or 'None'}->{new}": count
                        for (old, new), count in updated_counter.most_common()
                    },
                )

        if wire_cleaned_records is not None and wire_cleaned_export:
            _write_transition_csv(wire_cleaned_records, wire_cleaned_export)

        if wire_labeled_records is not None and wire_labeled_export:
            _write_transition_csv(wire_labeled_records, wire_labeled_export)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill article classifications",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving changes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of articles to process",
    )
    parser.add_argument(
        "--sample-size",
        dest="sample_size",
        type=int,
        default=50,
        help=(
            "Number of sample entries to display in dry-run mode "
            "(default: 50)"
        ),
    )
    parser.add_argument(
        "--batch-size",
        dest="batch_size",
        type=int,
        default=5000,
        help=(
            "Number of articles to fetch per batch (default: 5000). "
            "Smaller values reduce query size but increase total batches."
        ),
    )
    parser.add_argument(
        "--extra-domain",
        dest="extra_domains",
        action="append",
        help="Additional domain to include (can be provided multiple times)",
    )
    parser.add_argument(
        "--all-sources",
        action="store_true",
        help="Process all articles regardless of source filters",
    )
    parser.add_argument(
        "--export-wire-cleaned",
        dest="wire_cleaned_export",
        help="Path to write CSV of wire→cleaned transitions",
    )
    parser.add_argument(
        "--export-wire-labeled",
        dest="wire_labeled_export",
        help="Path to write CSV of wire→labeled transitions",
    )

    args = parser.parse_args()

    backfill_classification(
        dry_run=args.dry_run,
        limit=args.limit,
        extra_domains=args.extra_domains,
        sample_size=args.sample_size,
        batch_size=args.batch_size,
        all_sources=args.all_sources,
        wire_cleaned_export=args.wire_cleaned_export,
        wire_labeled_export=args.wire_labeled_export,
    )
