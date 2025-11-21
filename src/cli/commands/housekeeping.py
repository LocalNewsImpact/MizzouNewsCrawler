"""
Daily housekeeping command for pipeline maintenance.

Checks for records stuck in various pipeline states and decides whether to:
- Expire them (mark as paused with reason)
- Remove them
- Escalate them for manual review

This command should run daily to prevent pipeline accumulation of stale records.
"""

import logging
from datetime import datetime
from typing import TypedDict

from sqlalchemy import text

from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)


class HousekeepingReport(TypedDict):
    """Report of housekeeping actions taken."""

    timestamp: datetime
    null_text_articles_paused: int
    expired_candidates_paused: int
    stuck_extraction_articles_warned: int
    stuck_cleaning_articles_warned: int
    stuck_verification_candidates_warned: int
    total_actions: int


def add_housekeeping_parser(subparsers):
    """Add housekeeping command parser."""
    parser = subparsers.add_parser(
        "housekeeping",
        help=(
            "Daily pipeline housekeeping - "
            "check for stuck records and expire stale ones"
        ),
    )
    parser.add_argument(
        "--candidate-expiration-days",
        type=int,
        default=7,
        help="Mark candidates older than this many days as paused (default: 7)",
    )
    parser.add_argument(
        "--extraction-stall-hours",
        type=int,
        default=24,
        help=(
            "Warn about articles stuck in extraction "
            "for this many hours (default: 24)"
        ),
    )
    parser.add_argument(
        "--cleaning-stall-hours",
        type=int,
        default=24,
        help="Warn about articles stuck in cleaning for this many hours (default: 24)",
    )
    parser.add_argument(
        "--verification-stall-hours",
        type=int,
        default=24,
        help=(
            "Warn about candidates stuck in verification "
            "for this many hours (default: 24)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information about actions taken",
    )
    return parser


def handle_housekeeping_command(args) -> int:
    """
    Handle housekeeping command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        db = DatabaseManager()

        print()
        print("🧹 Pipeline Housekeeping")
        print("=" * 70)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Dry run: {args.dry_run}")
        print()

        report: HousekeepingReport = {
            "timestamp": datetime.now(),
            "null_text_articles_paused": 0,
            "expired_candidates_paused": 0,
            "stuck_extraction_articles_warned": 0,
            "stuck_cleaning_articles_warned": 0,
            "stuck_verification_candidates_warned": 0,
            "total_actions": 0,
        }

        with db.get_session() as session:
            # 1. Find and pause articles with NULL text in 'extracted' status
            report["null_text_articles_paused"] = _handle_null_text_articles(
                session, args.dry_run, args.verbose
            )

            # 2. Find and pause expired candidates
            report["expired_candidates_paused"] = _handle_expired_candidates(
                session,
                args.candidate_expiration_days,
                args.dry_run,
                args.verbose,
            )

            # 3. Check for articles stuck in extraction
            report["stuck_extraction_articles_warned"] = (
                _check_stuck_extraction_articles(
                    session,
                    args.extraction_stall_hours,
                    args.verbose,
                )
            )

            # 4. Check for articles stuck in cleaning
            report["stuck_cleaning_articles_warned"] = _check_stuck_cleaning_articles(
                session,
                args.cleaning_stall_hours,
                args.verbose,
            )

            # 5. Check for candidates stuck in verification
            report["stuck_verification_candidates_warned"] = (
                _check_stuck_verification_candidates(
                    session,
                    args.verification_stall_hours,
                    args.verbose,
                )
            )

        # Print summary
        print()
        print("Summary")
        print("-" * 70)
        print(f"  Null text articles paused: {report['null_text_articles_paused']}")
        print(f"  Expired candidates paused: {report['expired_candidates_paused']}")
        print(
            f"  Stuck extraction articles warned: "
            f"{report['stuck_extraction_articles_warned']}"
        )
        print(
            f"  Stuck cleaning articles warned: "
            f"{report['stuck_cleaning_articles_warned']}"
        )
        print(
            f"  Stuck verification candidates warned: "
            f"{report['stuck_verification_candidates_warned']}"
        )
        report["total_actions"] = sum(
            [
                report["null_text_articles_paused"],
                report["expired_candidates_paused"],
                report["stuck_extraction_articles_warned"],
                report["stuck_cleaning_articles_warned"],
                report["stuck_verification_candidates_warned"],
            ]
        )
        print(f"  Total actions: {report['total_actions']}")
        print()

        return 0

    except Exception as e:
        logger.error(f"Housekeeping failed: {e}", exc_info=True)
        print(f"❌ Error during housekeeping: {e}")
        return 1


def _handle_null_text_articles(session, dry_run: bool, verbose: bool) -> int:
    """
    Find articles with NULL text in 'extracted' status and pause them.

    These are articles where the content extraction failed (paywalls, e-editions,
    JavaScript-rendered pages, etc.) and cannot proceed to cleaning.

    Returns:
        Number of articles paused
    """
    print("1️⃣  Checking for articles with NULL text...")
    print()

    count = session.execute(
        text(
            """
        SELECT COUNT(*) FROM articles
        WHERE status = 'extracted' AND text IS NULL
    """
        )
    ).scalar()

    if count == 0:
        print("   ✓ No articles with NULL text found")
        return 0

    print(f"   Found {count} articles with NULL text in 'extracted' status")

    if verbose:
        # Show sample articles
        samples = session.execute(
            text(
                """
            SELECT a.id, a.url, a.created_at, cl.source
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.status = 'extracted' AND a.text IS NULL
            ORDER BY a.created_at ASC
            LIMIT 5
        """
            )
        ).fetchall()
        for article_id, url, created_at, source in samples:
            age_days = (datetime.now() - created_at).days
            print(f"     - {source} ({age_days}d): {url[:60]}...")

    if dry_run:
        print("   ⏭️  Dry run - no changes made")
        return count

    # Mark as paused with telemetry
    session.execute(
        text(
            """
        UPDATE articles
        SET status = 'paused',
            metadata = jsonb_set(
                COALESCE(metadata::jsonb, '{}'::jsonb),
                '{pause_reason}',
                '"null_text"'
            )
        WHERE status = 'extracted' AND text IS NULL
    """
        )
    )
    session.commit()

    print(f"   ✅ Marked {count} articles as paused")
    print()

    return count


def _handle_expired_candidates(
    session, days_threshold: int, dry_run: bool, verbose: bool
) -> int:
    """
    Find candidates in 'article' status older than threshold and pause them.

    These are candidates that have been waiting for extraction for too long,
    indicating they've been tried multiple times and hit transient failures
    or domain backoff.

    Returns:
        Number of candidates paused
    """
    print(f"2️⃣  Checking for expired candidates (older than {days_threshold} days)...")
    print()

    count = session.execute(
        text(
            f"""
        SELECT COUNT(*) FROM candidate_links
        WHERE status = 'article'
        AND created_at < NOW() - INTERVAL '{days_threshold} days'
    """
        )
    ).scalar()

    if count == 0:
        print(f"   ✓ No candidates older than {days_threshold} days found")
        return 0

    print(f"   Found {count} candidates older than {days_threshold} days")

    if verbose:
        # Show breakdown by source
        breakdown = session.execute(
            text(
                f"""
            SELECT source, COUNT(*) as cnt,
                MIN(EXTRACT(EPOCH FROM (NOW() - created_at))/86400)::INT as oldest_days
            FROM candidate_links
            WHERE status = 'article'
            AND created_at < NOW() - INTERVAL '{days_threshold} days'
            GROUP BY source
            ORDER BY cnt DESC
            LIMIT 10
        """
            )
        ).fetchall()
        for source, cnt, oldest_days in breakdown:
            print(f"     - {source}: {cnt} (oldest {oldest_days}d)")

    if dry_run:
        print("   ⏭️  Dry run - no changes made")
        return count

    # Mark as paused
    session.execute(
        text(
            f"""
        UPDATE candidate_links
        SET status = 'paused'
        WHERE status = 'article'
        AND created_at < NOW() - INTERVAL '{days_threshold} days'
    """
        )
    )
    session.commit()

    print(f"   ✅ Marked {count} candidates as paused")
    print()

    return count


def _check_stuck_extraction_articles(session, stall_hours: int, verbose: bool) -> int:
    """
    Check for articles stuck in 'extracted' status without further progress.

    These articles have been successfully extracted but are not moving to
    'cleaned' status, which could indicate a cleaning pipeline bottleneck
    or error.

    Returns:
        Number of articles stuck (for reporting)
    """
    print(f"3️⃣  Checking for articles stuck in extraction ({stall_hours}h+)...")
    print()

    count = session.execute(
        text(
            f"""
        SELECT COUNT(*) FROM articles
        WHERE status = 'extracted'
        AND extracted_at < NOW() - INTERVAL '{stall_hours} hours'
    """
        )
    ).scalar()

    if count == 0:
        print("   ✓ No articles stuck in extraction found")
        return 0

    print(f"   ⚠️  Found {count} articles stuck in 'extracted' status")

    if verbose:
        # Show sample articles and their age
        samples = session.execute(
            text(
                f"""
            SELECT a.id, a.url, a.extracted_at, cl.source,
                EXTRACT(EPOCH FROM (NOW() - a.extracted_at))/3600::INT as hours_stuck
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.status = 'extracted'
            AND a.extracted_at < NOW() - INTERVAL '{stall_hours} hours'
            ORDER BY a.extracted_at ASC
            LIMIT 5
        """
            )
        ).fetchall()
        for article_id, url, extracted_at, source, hours_stuck in samples:
            print(f"     - {source} ({hours_stuck}h): " f"{url[:50]}...")

    print("   → This usually indicates a cleaning pipeline bottleneck")
    print()

    return count


def _check_stuck_cleaning_articles(session, stall_hours: int, verbose: bool) -> int:
    """
    Check for articles stuck in 'cleaned' status without further progress.

    These articles have been successfully cleaned but are not moving to
    'local' or label status, which could indicate a later pipeline bottleneck.

    Returns:
        Number of articles stuck (for reporting)
    """
    print(f"4️⃣  Checking for articles stuck in cleaning ({stall_hours}h+)...")
    print()

    count = session.execute(
        text(
            f"""
        SELECT COUNT(*) FROM articles
        WHERE status = 'cleaned'
        AND extracted_at < NOW() - INTERVAL '{stall_hours} hours'
    """
        )
    ).scalar()

    if count == 0:
        print("   ✓ No articles stuck in cleaning found")
        return 0

    print(f"   ⚠️  Found {count} articles stuck in 'cleaned' status")

    if verbose:
        # Show sample articles and their age
        samples = session.execute(
            text(
                f"""
            SELECT a.id, a.url, a.extracted_at, cl.source,
                EXTRACT(EPOCH FROM (NOW() - a.extracted_at))/3600::INT as hours_stuck
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.status = 'cleaned'
            AND a.extracted_at < NOW() - INTERVAL '{stall_hours} hours'
            ORDER BY a.extracted_at ASC
            LIMIT 5
        """
            )
        ).fetchall()
        for article_id, url, extracted_at, source, hours_stuck in samples:
            print(f"     - {source} ({hours_stuck}h): " f"{url[:50]}...")

    print("   → This usually indicates a labeling pipeline bottleneck")
    print()

    return count


def _check_stuck_verification_candidates(
    session, stall_hours: int, verbose: bool
) -> int:
    """
    Check for candidates stuck in 'verified' status without further progress.

    These candidates have been verified but are not moving to 'article'
    status for extraction, which could indicate a queue management issue.

    Returns:
        Number of candidates stuck (for reporting)
    """
    print(f"5️⃣  Checking for candidates stuck in verification ({stall_hours}h+)...")
    print()

    count = session.execute(
        text(
            f"""
        SELECT COUNT(*) FROM candidate_links
        WHERE status = 'verified'
        AND fetched_at < NOW() - INTERVAL '{stall_hours} hours'
    """
        )
    ).scalar()

    if count == 0:
        print("   ✓ No candidates stuck in verification found")
        return 0

    print(f"   ⚠️  Found {count} candidates stuck in 'verified' status")

    if verbose:
        # Show sample candidates and their age
        samples = session.execute(
            text(
                f"""
            SELECT source, url, fetched_at,
                EXTRACT(EPOCH FROM (NOW() - fetched_at))/3600::INT as hours_stuck
            FROM candidate_links
            WHERE status = 'verified'
            AND fetched_at < NOW() - INTERVAL '{stall_hours} hours'
            ORDER BY fetched_at ASC
            LIMIT 5
        """
            )
        ).fetchall()
        for source, url, fetched_at, hours_stuck in samples:
            print(f"     - {source} ({hours_stuck}h): " f"{url[:50]}...")

    print("   → This usually indicates an extraction queue bottleneck")
    print()

    return count
