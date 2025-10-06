"""Operations telemetry endpoints for real-time pod monitoring.

This module provides endpoints that expose live pod activity:
- Current processing status and queue depths
- Active crawls by source/county
- Recent errors and warnings
- Pod health metrics
"""

from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from src.models.database import DatabaseManager

router = APIRouter(prefix="/api/telemetry/operations", tags=["operations"])


@router.get("/queue-status")
def get_queue_status() -> dict[str, Any]:
    """Get real-time queue depths for all pipeline stages.
    
    Returns counts of items waiting at each processing stage,
    useful for dashboard widgets showing pipeline health.
    """
    with DatabaseManager() as db:
        # Verification queue (discovered URLs awaiting classification)
        verification_pending = db.session.execute(
            text("SELECT COUNT(*) FROM candidate_links WHERE status = 'discovered'")
        ).scalar() or 0
        
        # Extraction queue (classified articles awaiting content extraction)
        extraction_pending = db.session.execute(
            text("SELECT COUNT(*) FROM candidate_links WHERE status = 'article'")
        ).scalar() or 0
        
        # Analysis queue (extracted articles awaiting ML classification)
        analysis_pending = db.session.execute(
            text(
                "SELECT COUNT(*) FROM articles "
                "WHERE primary_label IS NULL AND status != 'error'"
            )
        ).scalar() or 0
        
        # Entity extraction queue (analyzed articles awaiting gazetteer)
        entity_pending = db.session.execute(
            text(
                "SELECT COUNT(*) FROM articles a "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id"
                ") AND a.content IS NOT NULL AND a.status != 'error'"
            )
        ).scalar() or 0
        
        return {
            "verification_pending": verification_pending,
            "extraction_pending": extraction_pending,
            "analysis_pending": analysis_pending,
            "entity_extraction_pending": entity_pending,
            "total_pending": (
                verification_pending + extraction_pending +
                analysis_pending + entity_pending
            ),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }


@router.get("/recent-activity")
def get_recent_activity(minutes: int = 5) -> dict[str, Any]:
    """Get counts of items processed in the last N minutes.
    
    Shows actual throughput and processing velocity across all stages.
    """
    with DatabaseManager() as db:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)
        
        # Articles extracted in timeframe
        articles_extracted = db.session.execute(
            text(
                "SELECT COUNT(*) FROM articles "
                "WHERE created_at >= :cutoff"
            ),
            {"cutoff": cutoff}
        ).scalar() or 0
        
        # URLs verified in timeframe
        urls_verified = db.session.execute(
            text(
                "SELECT COUNT(*) FROM candidate_links "
                "WHERE verified_at >= :cutoff"
            ),
            {"cutoff": cutoff}
        ).scalar() or 0
        
        # ML analysis completed in timeframe
        analysis_completed = db.session.execute(
            text(
                "SELECT COUNT(*) FROM articles "
                "WHERE primary_label IS NOT NULL "
                "AND updated_at >= :cutoff"
            ),
            {"cutoff": cutoff}
        ).scalar() or 0
        
        return {
            "timeframe_minutes": minutes,
            "articles_extracted": articles_extracted,
            "urls_verified": urls_verified,
            "analysis_completed": analysis_completed,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }


@router.get("/sources-being-processed")
def get_active_sources(limit: int = 20) -> dict[str, Any]:
    """Get list of sources currently being crawled/processed.
    
    Returns sources with recent activity (last 15 minutes) showing
    what the crawler pods are actively working on.
    """
    with DatabaseManager() as db:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=15)
        
        # Sources with recent candidate links
        result = db.session.execute(
            text("""
                SELECT
                    cl.source_host_id,
                    cl.source_name,
                    cl.source_county,
                    COUNT(*) as recent_count,
                    MAX(cl.created_at) as last_activity,
                    SUM(CASE WHEN cl.status = 'discovered' THEN 1 ELSE 0 END)
                        as pending,
                    SUM(CASE WHEN cl.status = 'article' THEN 1 ELSE 0 END)
                        as articles
                FROM candidate_links cl
                WHERE cl.created_at >= :cutoff
                GROUP BY cl.source_host_id, cl.source_name, cl.source_county
                ORDER BY last_activity DESC
                LIMIT :limit
            """),
            {"cutoff": cutoff, "limit": limit}
        )
        
        sources = []
        for row in result:
            sources.append({
                "host": row.source_host_id,
                "name": row.source_name,
                "county": row.source_county,
                "recent_urls": row.recent_count,
                "last_activity": (
                    row.last_activity.isoformat()
                    if row.last_activity else None
                ),
                "pending_verification": row.pending,
                "ready_for_extraction": row.articles,
            })
        
        return {
            "active_sources": sources,
            "count": len(sources),
            "timeframe_minutes": 15,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }


@router.get("/recent-errors")
def get_recent_errors(hours: int = 1, limit: int = 50) -> dict[str, Any]:
    """Get recent processing errors from all pipeline stages.
    
    Aggregates errors from:
    - Article extraction failures
    - HTTP errors
    - Verification failures
    """
    with DatabaseManager() as db:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        
        # Articles with extraction errors
        article_errors = db.session.execute(
            text("""
                SELECT
                    url,
                    error_message,
                    updated_at as timestamp,
                    'extraction' as error_type
                FROM articles
                WHERE status = 'error'
                AND updated_at >= :cutoff
                ORDER BY updated_at DESC
                LIMIT :limit
            """),
            {"cutoff": cutoff, "limit": limit}
        )
        
        errors = []
        for row in article_errors:
            errors.append({
                "url": row.url,
                "error": row.error_message,
                "type": row.error_type,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            })
        
        # Group by error type for summary
        error_summary = {}
        for error in errors:
            error_type = error["type"]
            if error_type not in error_summary:
                error_summary[error_type] = 0
            error_summary[error_type] += 1
        
        return {
            "errors": errors[:limit],
            "summary": error_summary,
            "total_errors": len(errors),
            "timeframe_hours": hours,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }


@router.get("/county-progress")
def get_county_progress() -> dict[str, Any]:
    """Get per-county processing statistics.
    
    Shows how many articles have been collected from each county,
    useful for monitoring geographic coverage.
    """
    with DatabaseManager() as db:
        result = db.session.execute(
            text("""
                SELECT
                    cl.source_county as county,
                    COUNT(DISTINCT cl.source_host_id) as source_count,
                    COUNT(*) as total_urls,
                    SUM(CASE WHEN cl.status = 'article' THEN 1 ELSE 0 END) as articles,
                    SUM(CASE WHEN cl.status = 'discovered' THEN 1 ELSE 0 END) as pending
                FROM candidate_links cl
                WHERE cl.source_county IS NOT NULL
                GROUP BY cl.source_county
                ORDER BY articles DESC
            """)
        )
        
        counties = []
        for row in result:
            counties.append({
                "county": row.county,
                "sources": row.source_count,
                "total_urls": row.total_urls,
                "articles": row.articles,
                "pending_verification": row.pending,
            })
        
        return {
            "counties": counties,
            "total_counties": len(counties),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }


@router.get("/health")
def get_pipeline_health() -> dict[str, Any]:
    """Get overall pipeline health indicators.
    
    Returns metrics that indicate if the pipeline is healthy:
    - Recent throughput
    - Error rates
    - Queue growth/shrinkage
    """
    with DatabaseManager() as db:
        # Get error rate over last hour
        hour_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        
        total_recent = db.session.execute(
            text("SELECT COUNT(*) FROM articles WHERE created_at >= :cutoff"),
            {"cutoff": hour_ago}
        ).scalar() or 0
        
        errors_recent = db.session.execute(
            text(
                "SELECT COUNT(*) FROM articles "
                "WHERE status = 'error' AND updated_at >= :cutoff"
            ),
            {"cutoff": hour_ago}
        ).scalar() or 0
        
        error_rate = (errors_recent / total_recent * 100) if total_recent > 0 else 0
        
        # Check if queues are growing or shrinking (compare last hour to previous hour)
        two_hours_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
        
        urls_last_hour = db.session.execute(
            text(
                "SELECT COUNT(*) FROM candidate_links "
                "WHERE created_at >= :cutoff"
            ),
            {"cutoff": hour_ago}
        ).scalar() or 0
        
        urls_prev_hour = db.session.execute(
            text(
                "SELECT COUNT(*) FROM candidate_links "
                "WHERE created_at >= :start AND created_at < :end"
            ),
            {"start": two_hours_ago, "end": hour_ago}
        ).scalar() or 0
        
        # Determine health status
        health_status = "healthy"
        issues = []
        
        if error_rate > 25:
            health_status = "warning"
            issues.append(f"High error rate: {error_rate:.1f}%")
        
        if urls_last_hour < urls_prev_hour * 0.5 and urls_prev_hour > 10:
            health_status = "warning"
            issues.append("Processing rate has dropped significantly")
        
        if total_recent == 0 and hour_ago:
            health_status = "error"
            issues.append("No articles processed in the last hour")
        
        return {
            "status": health_status,
            "issues": issues,
            "metrics": {
                "error_rate_pct": round(error_rate, 2),
                "articles_last_hour": total_recent,
                "errors_last_hour": errors_recent,
                "url_velocity_change_pct": round(
                    ((urls_last_hour - urls_prev_hour) / urls_prev_hour * 100)
                    if urls_prev_hour > 0 else 0,
                    2
                ),
            },
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }
