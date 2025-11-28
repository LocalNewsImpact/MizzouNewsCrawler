"""Pipeline status command for comprehensive visibility into all stages."""

import argparse
import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from src.models.database import DatabaseManager, safe_session_execute

logger = logging.getLogger(__name__)


def _to_int(value, default=0):
    """Convert PostgreSQL string or SQLite int to int.

    PostgreSQL returns aggregate results as strings, SQLite returns native types.
    This helper ensures consistent int conversion across both databases.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def add_pipeline_status_parser(subparsers) -> argparse.ArgumentParser:
    """Add pipeline-status command parser to subparsers."""
    parser = subparsers.add_parser(
        "pipeline-status",
        help="Show comprehensive status of all pipeline stages",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed breakdown by domain and source",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Show activity in the last N hours (default: 24)",
    )
    parser.set_defaults(func=handle_pipeline_status_command)
    return parser


def handle_pipeline_status_command(args) -> int:
    """Execute pipeline status command logic."""
    detailed = getattr(args, "detailed", False)
    hours = getattr(args, "hours", 24)

    print()
    print("=" * 80)
    print("📊 MIZZOU NEWS CRAWLER - PIPELINE STATUS REPORT")
    print("=" * 80)
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    print(f"Activity window: Last {hours} hours")
    print()

    db = DatabaseManager()

    try:
        with db.get_session() as session:
            # Stage 1: Discovery
            print("━━━ STAGE 1: DISCOVERY ━━━")
            _check_discovery_status(session, hours, detailed)
            print()

            # Stage 2: Verification
            print("━━━ STAGE 2: VERIFICATION ━━━")
            _check_verification_status(session, hours, detailed)
            print()

            # Stage 3: Extraction
            print("━━━ STAGE 3: EXTRACTION ━━━")
            _check_extraction_status(session, hours, detailed)
            print()

            # Stage 4: Entity Extraction
            print("━━━ STAGE 4: ENTITY EXTRACTION ━━━")
            _check_entity_extraction_status(session, hours, detailed)
            print()

            # Stage 5: Analysis/Classification
            print("━━━ STAGE 5: ANALYSIS/CLASSIFICATION ━━━")
            _check_analysis_status(session, hours, detailed)
            print()

            # Overall pipeline health
            print("━━━ OVERALL PIPELINE HEALTH ━━━")
            try:
                _check_overall_health(session, hours)
            except Exception as e:
                session.rollback()
                error_type = type(e).__name__
                print(f"  ⚠️  Could not compute overall health: {error_type}")
            print()

            # Database statistics health (PostgreSQL-only, requires clean transaction)
            print("━━━ DATABASE STATISTICS HEALTH ━━━")
            try:
                # Use a fresh connection for system catalog queries
                db = DatabaseManager()
                with db.get_session() as stats_session:
                    _check_statistics_freshness(stats_session)
            except Exception as e:
                error_type = type(e).__name__
                logger.debug(f"Statistics check error: {e}", exc_info=True)
                print(f"  ⚠️  Statistics monitoring not available ({error_type})")
            print()

        print("=" * 80)
        return 0

    except Exception as exc:
        logger.exception("Pipeline status command failed: %s", exc)
        print(f"❌ Error getting pipeline status: {exc}")
        return 1


def _check_discovery_status(session, hours, detailed):
    """Check discovery pipeline status."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    # Total sources
    result = safe_session_execute(
        session, text("SELECT COUNT(*) FROM sources WHERE host IS NOT NULL")
    )
    total_sources = _to_int(result.scalar(), 0)

    # Sources discovered from recently
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(DISTINCT source_host_id)
            FROM candidate_links
            WHERE discovered_at >= :cutoff
        """
        ),
        {"cutoff": cutoff},
    )
    sources_discovered = _to_int(result.scalar(), 0)

    # Total URLs discovered
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(*)
            FROM candidate_links
            WHERE discovered_at >= :cutoff
        """
        ),
        {"cutoff": cutoff},
    )
    urls_discovered = _to_int(result.scalar(), 0)

    # Sources due for discovery (haven't been processed in last 7 days)
    # Optimized with LEFT JOIN: 1.5s vs 62s NOT IN (40x faster)
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(*)
            FROM sources s
            LEFT JOIN (
                SELECT DISTINCT source_host_id
                FROM candidate_links
                WHERE processed_at >= NOW() - INTERVAL '7 days'
            ) recent ON s.id = recent.source_host_id
            WHERE s.host IS NOT NULL
            AND recent.source_host_id IS NULL
        """
        ),
    )
    sources_due = _to_int(result.scalar(), 0)

    print(f"  Total sources: {total_sources}")
    print(f"  Sources due for discovery: {sources_due}")
    print(f"  Sources discovered from (last {hours}h): {sources_discovered}")
    print(f"  URLs discovered (last {hours}h): {urls_discovered}")

    if sources_discovered == 0 and sources_due > 0:
        print(f"  ⚠️  WARNING: {sources_due} sources due but 0 discovered recently!")
    elif sources_discovered > 0:
        avg_urls = urls_discovered / sources_discovered if sources_discovered > 0 else 0
        print(f"  ✓ Average URLs per source: {avg_urls:.1f}")

    if detailed and sources_discovered > 0:
        result = safe_session_execute(
            session,
            text(
                """
                SELECT s.canonical_name, COUNT(*) as url_count
                FROM candidate_links cl
                JOIN sources s ON cl.source_host_id = s.id
                WHERE cl.discovered_at >= :cutoff
                GROUP BY s.canonical_name
                ORDER BY url_count DESC
                LIMIT 10
            """
            ),
            {"cutoff": cutoff},
        )
        print("\n  Top 10 sources by URLs discovered:")
        for row in result:
            # row[1] is COUNT(*) aggregate - convert to int
            print(f"    • {row[0]}: {_to_int(row[1])} URLs")


def _check_verification_status(session, hours, detailed):
    """Check verification pipeline status."""
    # Pending verification (URLs with status='discovered')
    result = safe_session_execute(
        session,
        text("SELECT COUNT(*) FROM candidate_links WHERE status = 'discovered'"),
    )
    pending = _to_int(result.scalar(), 0)

    # Verified as articles
    result = safe_session_execute(
        session, text("SELECT COUNT(*) FROM candidate_links WHERE status = 'article'")
    )
    articles = _to_int(result.scalar(), 0)

    # Verified recently (any URL with processed_at timestamp)
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(*)
            FROM candidate_links
            WHERE processed_at >= :cutoff
        """
        ),
        {"cutoff": cutoff},
    )
    verified_recent = _to_int(result.scalar(), 0)

    print(f"  Pending verification: {pending}")
    print(f"  Verified as articles (total): {articles}")
    print(f"  URLs verified (last {hours}h): {verified_recent}")

    if pending > 1000:
        print(f"  ⚠️  WARNING: Large backlog of {pending} pending URLs!")
    elif pending > 100:
        print(f"  ℹ️  Note: {pending} URLs waiting for verification")

    if verified_recent > 0:
        print(f"  ✓ Verification active in last {hours}h")
    else:
        print(f"  ⚠️  WARNING: No verification activity in last {hours}h!")


def _check_extraction_status(session, hours, detailed):
    """Check extraction pipeline status."""
    # Articles ready for extraction (verified but not extracted)
    # Optimized query: NOT EXISTS is 20x faster than LEFT JOIN (0.26s vs 5.23s)
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(*)
            FROM candidate_links cl
            WHERE cl.status = 'article'
            AND NOT EXISTS (
                SELECT 1 FROM articles a
                WHERE a.candidate_link_id = cl.id
            )
        """
        ),
    )
    ready_for_extraction = _to_int(result.scalar(), 0)

    # Total extracted articles - use pg_class estimate for 10x speedup (11s -> 0.5s)
    result = safe_session_execute(
        session,
        text("SELECT reltuples::bigint FROM pg_class WHERE relname = 'articles'"),
    )
    total_extracted = _to_int(result.scalar(), 0)

    # Extracted recently
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = safe_session_execute(
        session,
        text("SELECT COUNT(*) FROM articles WHERE extracted_at >= :cutoff"),
        {"cutoff": cutoff},
    )
    extracted_recent = _to_int(result.scalar(), 0)

    print(f"  Ready for extraction: {ready_for_extraction}")
    print(f"  Total extracted: {total_extracted}")
    print(f"  Extracted (last {hours}h): {extracted_recent}")

    if ready_for_extraction > 500:
        print(f"  ⚠️  WARNING: Large backlog of {ready_for_extraction} articles!")

    if extracted_recent > 0:
        print(f"  ✓ Extraction active in last {hours}h")
    else:
        print(f"  ⚠️  WARNING: No extraction activity in last {hours}h!")

    # Status breakdown - optimized with IS NOT NULL for 7x speedup (22s -> 3s)
    if detailed:
        # Enable parallel query for GROUP BY aggregation (16s -> 2s)
        safe_session_execute(session, text("SET LOCAL max_parallel_workers_per_gather = 4"))
        safe_session_execute(session, text("SET LOCAL parallel_setup_cost = 1"))
        safe_session_execute(session, text("SET LOCAL min_parallel_table_scan_size = 0"))
        
        result = safe_session_execute(
            session,
            text(
                """
                SELECT status, COUNT(*) as count
                FROM articles
                WHERE status IS NOT NULL
                GROUP BY status
                ORDER BY count DESC
            """
            ),
        )
        status_breakdown = list(result)
        if status_breakdown:
            print("\n  Status breakdown:")
            for status, count in status_breakdown:
                # count is aggregate - convert to int
                print(f"    • {status}: {_to_int(count)}")


def _check_entity_extraction_status(session, hours, detailed):
    """Check entity extraction pipeline status."""
    # Articles ready for entity extraction (extracted or classified)
    # Optimized query: NOT EXISTS is 4x faster than LEFT JOIN (0.23s vs 1.01s)
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(*)
            FROM articles a
            WHERE a.status IN ('extracted', 'classified')
            AND a.content IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM article_entities ae
                WHERE ae.article_id = a.id
            )
        """
        ),
    )
    ready_for_entities = _to_int(result.scalar(), 0)

    # Articles with entities - use fast estimate from table statistics
    # Total articles (estimate) minus articles ready for entities
    result = safe_session_execute(
        session,
        text("SELECT reltuples::bigint FROM pg_class WHERE relname = 'articles'"),
    )
    total_articles_estimate = _to_int(result.scalar(), 0)
    total_with_entities = max(0, total_articles_estimate - ready_for_entities)

    # Articles processed recently - uses composite index for fast lookup (~1s)
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(DISTINCT article_id)
            FROM article_entities
            WHERE created_at >= :cutoff
        """
        ),
        {"cutoff": cutoff},
    )
    entities_recent = _to_int(result.scalar(), 0)

    print(f"  Ready for entity extraction: {ready_for_entities}")
    print(f"  Articles with entities (total): {total_with_entities}")
    print(f"  Articles processed (last {hours}h): {entities_recent}")

    if ready_for_entities > 1000:
        print(f"  ⚠️  WARNING: Large backlog of {ready_for_entities} articles!")

    if entities_recent > 0:
        print(f"  ✓ Entity extraction active in last {hours}h")
    else:
        print(f"  ⚠️  WARNING: No entity extraction activity in last {hours}h!")


def _check_analysis_status(session, hours, detailed):
    """Check analysis/classification pipeline status."""
    # Query the article_labels table (the actual classification results table)
    try:
        # Count articles eligible for classification (only status='extracted' are ready)
        # Optimized query: NOT EXISTS is 12x faster than LEFT JOIN (0.24s vs 3.01s)
        result = safe_session_execute(
            session,
            text(
                """
                SELECT COUNT(*)
                FROM articles a
                WHERE a.status = 'extracted'
                AND NOT EXISTS (
                    SELECT 1 FROM article_labels al
                    WHERE al.article_id = a.id
                )
            """
            ),
        )
        ready_for_analysis = _to_int(result.scalar(), 0)

        # Count total articles with classification labels
        result = safe_session_execute(
            session, text("SELECT COUNT(DISTINCT article_id) FROM article_labels")
        )
        total_analyzed = _to_int(result.scalar(), 0)

        # Count recent classifications
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = safe_session_execute(
            session,
            text(
                """
                SELECT COUNT(DISTINCT article_id)
                FROM article_labels
                WHERE applied_at >= :cutoff
            """
            ),
            {"cutoff": cutoff},
        )
        analyzed_recent = _to_int(result.scalar(), 0)

        print(f"  Ready for classification: {ready_for_analysis}")
        print(f"  Articles classified (total): {total_analyzed}")
        print(f"  Classified (last {hours}h): {analyzed_recent}")

        if ready_for_analysis > 1000:
            print(f"  ⚠️  WARNING: Large backlog of {ready_for_analysis} articles!")

        if analyzed_recent > 0:
            print(f"  ✓ Classification active in last {hours}h")
        else:
            print(f"  ⚠️  WARNING: No classification activity in last {hours}h!")

    except Exception as e:
        session.rollback()
        msg = str(e).lower()
        if "does not exist" in msg or "no such table" in msg:
            print("  ℹ️  Classification status not available (table missing)")
        else:
            print(f"  ℹ️  Error checking classification status: {type(e).__name__}")


def _check_overall_health(session, hours):
    """Check overall pipeline health."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    # Check each stage for recent activity
    stages_active = 0
    stages_total = 5

    # Discovery
    result = safe_session_execute(
        session,
        text("SELECT COUNT(*) FROM candidate_links WHERE discovered_at >= :cutoff"),
        {"cutoff": cutoff},
    )
    if _to_int(result.scalar(), 0) > 0:
        stages_active += 1

    # Verification
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(*) FROM candidate_links
            WHERE processed_at >= :cutoff
        """
        ),
        {"cutoff": cutoff},
    )
    if _to_int(result.scalar(), 0) > 0:
        stages_active += 1

    # Extraction
    result = safe_session_execute(
        session,
        text("SELECT COUNT(*) FROM articles WHERE extracted_at >= :cutoff"),
        {"cutoff": cutoff},
    )
    if _to_int(result.scalar(), 0) > 0:
        stages_active += 1

    # Entity extraction
    result = safe_session_execute(
        session,
        text(
            """
            SELECT COUNT(DISTINCT article_id) FROM article_entities
            WHERE created_at >= :cutoff
        """
        ),
        {"cutoff": cutoff},
    )
    if _to_int(result.scalar(), 0) > 0:
        stages_active += 1

    # Analysis
    try:
        result = safe_session_execute(
            session,
            text(
                """
                SELECT COUNT(DISTINCT article_id) FROM article_labels
                WHERE created_at >= :cutoff
            """
            ),
            {"cutoff": cutoff},
        )
        if _to_int(result.scalar(), 0) > 0:
            stages_active += 1
    except Exception:
        stages_total = 4  # Analysis stage not available

    health_pct = (stages_active / stages_total * 100) if stages_total > 0 else 0

    print(f"  Pipeline stages active: {stages_active}/{stages_total}")
    print(f"  Health score: {health_pct:.0f}%")

    if health_pct >= 80:
        print("  ✅ Pipeline is healthy!")
    elif health_pct >= 60:
        print("  ⚠️  Pipeline is partially active")
    elif health_pct >= 40:
        print("  ⚠️  Pipeline has multiple stalled stages")
    else:
        print("  ❌ Pipeline appears stalled or blocked!")


def _check_statistics_freshness(session):
    """Check freshness of database statistics.
    
    Stale statistics can cause poor query plans and slow performance.
    This monitors tables with high write volume.
    """
    # Use direct execute for PostgreSQL system tables (not compatible with SQLite)
    result = session.execute(
        text("""
            SELECT 
                schemaname || '.' || relname as table_name,
                n_tup_ins + n_tup_upd + n_tup_del as modifications,
                last_analyze,
                last_autoanalyze,
                GREATEST(last_analyze, last_autoanalyze) as last_stats_update,
                EXTRACT(epoch FROM now() - GREATEST(last_analyze, last_autoanalyze))/3600 as hours_since_analyze,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) as size
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            AND relname IN ('article_entities', 'candidate_links', 'articles', 'sources')
            ORDER BY modifications DESC
        """)
    )
    
    rows = result.fetchall()
    if not rows:
        print("  ⚠️  No statistics data available")
        return
    
    stale_count = 0
    high_mod_count = 0
    
    print("  High-write tables:")
    for row in rows:
        table_name = row[0]
        modifications = _to_int(row[1], 0)
        hours_since = float(row[5]) if row[5] is not None else None
        size = row[6]
        
        # Determine status
        status = "✓"
        if hours_since is None:
            status = "⚠️  NEVER"
            stale_count += 1
        elif hours_since > 24:
            status = f"⚠️  {hours_since:.0f}h ago"
            stale_count += 1
        elif hours_since > 12:
            status = f"⚡ {hours_since:.0f}h ago"
        else:
            status = f"✓ {hours_since:.0f}h ago"
        
        if modifications > 10000:
            high_mod_count += 1
            mod_str = f"{modifications:,} changes"
        else:
            mod_str = f"{modifications:,} changes"
        
        print(f"    {table_name:20} {size:>10} {mod_str:>15} {status}")
    
    print()
    if stale_count > 0:
        print(f"  ⚠️  {stale_count} table(s) with stale statistics (>24h)")
        print("  💡 Consider running: ANALYZE <table_name>")
    elif high_mod_count > 0:
        print(f"  ✓ Statistics fresh ({high_mod_count} high-activity tables)")
    else:
        print("  ✓ All statistics up to date")
