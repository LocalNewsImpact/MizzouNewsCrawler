"""Pipeline status command for comprehensive visibility into all stages."""

import argparse
import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)


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
            _check_overall_health(session, hours)
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
    result = session.execute(text("SELECT COUNT(*) FROM sources WHERE host IS NOT NULL"))
    total_sources = result.scalar() or 0
    
    # Sources discovered from recently
    result = session.execute(
        text("""
            SELECT COUNT(DISTINCT source_host_id)
            FROM candidate_links
            WHERE discovered_at >= :cutoff
        """),
        {"cutoff": cutoff}
    )
    sources_discovered = result.scalar() or 0
    
    # Total URLs discovered
    result = session.execute(
        text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE discovered_at >= :cutoff
        """),
        {"cutoff": cutoff}
    )
    urls_discovered = result.scalar() or 0
    
    # Sources due for discovery (last processed > 7 days ago)
    result = session.execute(
        text("""
            SELECT COUNT(DISTINCT s.id)
            FROM sources s
            LEFT JOIN candidate_links cl ON s.id = cl.source_host_id
            WHERE s.host IS NOT NULL
            AND (
                cl.processed_at IS NULL
                OR cl.processed_at < NOW() - INTERVAL '7 days'
                OR NOT EXISTS (
                    SELECT 1 FROM candidate_links cl2
                    WHERE cl2.source_host_id = s.id
                    AND cl2.processed_at >= NOW() - INTERVAL '7 days'
                )
            )
        """)
    )
    sources_due = result.scalar() or 0
    
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
        result = session.execute(
            text("""
                SELECT s.canonical_name, COUNT(*) as url_count
                FROM candidate_links cl
                JOIN sources s ON cl.source_host_id = s.id
                WHERE cl.discovered_at >= :cutoff
                GROUP BY s.canonical_name
                ORDER BY url_count DESC
                LIMIT 10
            """),
            {"cutoff": cutoff}
        )
        print("\n  Top 10 sources by URLs discovered:")
        for row in result:
            print(f"    • {row[0]}: {row[1]} URLs")


def _check_verification_status(session, hours, detailed):
    """Check verification pipeline status."""
    # Pending verification
    result = session.execute(
        text("SELECT COUNT(*) FROM candidate_links WHERE status = 'pending'")
    )
    pending = result.scalar() or 0
    
    # Verified as articles
    result = session.execute(
        text("SELECT COUNT(*) FROM candidate_links WHERE status = 'article'")
    )
    articles = result.scalar() or 0
    
    # Verified recently
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = session.execute(
        text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE status IN ('article', 'not_article', 'error')
            AND verified_at >= :cutoff
        """),
        {"cutoff": cutoff}
    )
    verified_recent = result.scalar() or 0
    
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
    result = session.execute(
        text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE status = 'article'
            AND id NOT IN (
                SELECT candidate_link_id
                FROM articles
                WHERE candidate_link_id IS NOT NULL
            )
        """)
    )
    ready_for_extraction = result.scalar() or 0
    
    # Total extracted articles
    result = session.execute(text("SELECT COUNT(*) FROM articles"))
    total_extracted = result.scalar() or 0
    
    # Extracted recently
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = session.execute(
        text("SELECT COUNT(*) FROM articles WHERE extracted_at >= :cutoff"),
        {"cutoff": cutoff}
    )
    extracted_recent = result.scalar() or 0
    
    # Status breakdown
    result = session.execute(
        text("""
            SELECT status, COUNT(*) as count
            FROM articles
            GROUP BY status
            ORDER BY count DESC
        """)
    )
    status_breakdown = list(result)
    
    print(f"  Ready for extraction: {ready_for_extraction}")
    print(f"  Total extracted: {total_extracted}")
    print(f"  Extracted (last {hours}h): {extracted_recent}")
    
    if ready_for_extraction > 500:
        print(f"  ⚠️  WARNING: Large backlog of {ready_for_extraction} articles!")
    
    if extracted_recent > 0:
        print(f"  ✓ Extraction active in last {hours}h")
    else:
        print(f"  ⚠️  WARNING: No extraction activity in last {hours}h!")
    
    if status_breakdown:
        print("\n  Status breakdown:")
        for status, count in status_breakdown:
            print(f"    • {status}: {count}")


def _check_entity_extraction_status(session, hours, detailed):
    """Check entity extraction pipeline status."""
    # Articles ready for entity extraction (have content but no entities)
    result = session.execute(
        text("""
            SELECT COUNT(*)
            FROM articles a
            WHERE a.content IS NOT NULL
            AND a.text IS NOT NULL
            AND a.status NOT IN ('wire', 'opinion', 'obituary', 'error')
            AND NOT EXISTS (
                SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id
            )
        """)
    )
    ready_for_entities = result.scalar() or 0
    
    # Total articles with entities
    result = session.execute(
        text("SELECT COUNT(DISTINCT article_id) FROM article_entities")
    )
    total_with_entities = result.scalar() or 0
    
    # Entities extracted recently
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = session.execute(
        text("""
            SELECT COUNT(DISTINCT article_id)
            FROM article_entities
            WHERE created_at >= :cutoff
        """),
        {"cutoff": cutoff}
    )
    entities_recent = result.scalar() or 0
    
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
    # Check if article_classifications table exists
    try:
        result = session.execute(
            text("""
                SELECT COUNT(*)
                FROM articles a
                WHERE a.status IN ('extracted', 'cleaned', 'local')
                AND NOT EXISTS (
                    SELECT 1 FROM article_classifications ac WHERE ac.article_id = a.id
                )
            """)
        )
        ready_for_analysis = result.scalar() or 0
        
        result = session.execute(
            text("SELECT COUNT(DISTINCT article_id) FROM article_classifications")
        )
        total_analyzed = result.scalar() or 0
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = session.execute(
            text("""
                SELECT COUNT(DISTINCT article_id)
                FROM article_classifications
                WHERE created_at >= :cutoff
            """),
            {"cutoff": cutoff}
        )
        analyzed_recent = result.scalar() or 0
        
        print(f"  Ready for analysis: {ready_for_analysis}")
        print(f"  Articles analyzed (total): {total_analyzed}")
        print(f"  Analyzed (last {hours}h): {analyzed_recent}")
        
        if ready_for_analysis > 1000:
            print(f"  ⚠️  WARNING: Large backlog of {ready_for_analysis} articles!")
        
        if analyzed_recent > 0:
            print(f"  ✓ Analysis active in last {hours}h")
        else:
            print(f"  ⚠️  WARNING: No analysis activity in last {hours}h!")
            
    except Exception:
        print("  ℹ️  Analysis table not available or error checking status")


def _check_overall_health(session, hours):
    """Check overall pipeline health."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    # Check each stage for recent activity
    stages_active = 0
    stages_total = 5
    
    # Discovery
    result = session.execute(
        text("SELECT COUNT(*) FROM candidate_links WHERE discovered_at >= :cutoff"),
        {"cutoff": cutoff}
    )
    if (result.scalar() or 0) > 0:
        stages_active += 1
    
    # Verification
    result = session.execute(
        text("""
            SELECT COUNT(*) FROM candidate_links
            WHERE verified_at >= :cutoff
        """),
        {"cutoff": cutoff}
    )
    if (result.scalar() or 0) > 0:
        stages_active += 1
    
    # Extraction
    result = session.execute(
        text("SELECT COUNT(*) FROM articles WHERE extracted_at >= :cutoff"),
        {"cutoff": cutoff}
    )
    if (result.scalar() or 0) > 0:
        stages_active += 1
    
    # Entity extraction
    result = session.execute(
        text("""
            SELECT COUNT(DISTINCT article_id) FROM article_entities
            WHERE created_at >= :cutoff
        """),
        {"cutoff": cutoff}
    )
    if (result.scalar() or 0) > 0:
        stages_active += 1
    
    # Analysis
    try:
        result = session.execute(
            text("""
                SELECT COUNT(DISTINCT article_id) FROM article_classifications
                WHERE created_at >= :cutoff
            """),
            {"cutoff": cutoff}
        )
        if (result.scalar() or 0) > 0:
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
