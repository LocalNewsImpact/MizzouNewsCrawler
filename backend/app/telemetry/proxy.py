"""Proxy telemetry API endpoints.

This module provides REST API endpoints for querying proxy performance metrics,
including success rates, error patterns, authentication tracking, and domain-specific
proxy usage statistics.
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from src.models.database import DatabaseManager

router = APIRouter(prefix="/telemetry/proxy", tags=["telemetry", "proxy"])


@router.get("/summary")
async def get_proxy_summary(
    days: int = Query(7, description="Number of days to look back", ge=1, le=90)
) -> dict[str, Any]:
    """Get overall proxy usage summary.

    Returns aggregate statistics including total requests, proxy usage percentage,
    success rates, and authentication status.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    with DatabaseManager() as db:
        query = text(
            """
            SELECT
                COUNT(*) as total_requests,
            SUM(CASE WHEN proxy_used IS TRUE THEN 1 ELSE 0 END) as proxy_requests,
            SUM(CASE WHEN proxy_used IS FALSE THEN 1 ELSE 0 END) as direct_requests,
            ROUND(100.0 * SUM(CASE WHEN proxy_used IS TRUE THEN 1 ELSE 0 END)
                / COUNT(*), 2) as proxy_percentage,
                SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END)
                    as proxy_successes,
                SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END)
                    as proxy_failures,
                SUM(CASE WHEN proxy_status = 'bypassed' THEN 1 ELSE 0 END)
                    as proxy_bypassed,
                ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success'
                                       THEN 1 ELSE 0 END)
                      / NULLIF(SUM(CASE WHEN proxy_used IS TRUE
                                        THEN 1 ELSE 0 END), 0), 2)
                    as proxy_success_rate,
                SUM(CASE WHEN proxy_authenticated IS TRUE THEN 1 ELSE 0 END)
                    as authenticated_requests,
                SUM(CASE WHEN proxy_authenticated IS FALSE AND proxy_used IS TRUE
                         THEN 1 ELSE 0 END) as missing_auth_requests
            FROM extraction_telemetry_v2
            WHERE created_at >= :cutoff
            """
        )

        result = db.session.execute(query, {"cutoff": cutoff}).fetchone()

        if not result:
            return {
                "total_requests": 0,
                "proxy_requests": 0,
                "direct_requests": 0,
                "proxy_percentage": 0.0,
                "proxy_successes": 0,
                "proxy_failures": 0,
                "proxy_bypassed": 0,
                "proxy_success_rate": 0.0,
                "authenticated_requests": 0,
                "missing_auth_requests": 0,
                "days": days,
            }

        return {
            "total_requests": result[0] or 0,
            "proxy_requests": result[1] or 0,
            "direct_requests": result[2] or 0,
            "proxy_percentage": float(result[3] or 0.0),
            "proxy_successes": result[4] or 0,
            "proxy_failures": result[5] or 0,
            "proxy_bypassed": result[6] or 0,
            "proxy_success_rate": float(result[7] or 0.0),
            "authenticated_requests": result[8] or 0,
            "missing_auth_requests": result[9] or 0,
            "days": days,
        }


@router.get("/trends")
async def get_proxy_trends(
    days: int = Query(30, description="Number of days to look back", ge=1, le=90)
) -> dict[str, Any]:
    """Get daily proxy usage trends.

    Returns time-series data showing proxy usage, success rates, and authentication
    status over time.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = text(
        """
        SELECT
            DATE(created_at) as date,
            COUNT(*) as total_requests,
            SUM(CASE WHEN proxy_used IS TRUE THEN 1 ELSE 0 END) as proxy_requests,
            ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success'
                                   THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN proxy_used IS TRUE
                                    THEN 1 ELSE 0 END), 0), 2)
                as success_rate,
            SUM(CASE WHEN proxy_authenticated IS FALSE AND proxy_used IS TRUE
                     THEN 1 ELSE 0 END) as missing_auth,
            SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) as failures
        FROM extraction_telemetry_v2
        WHERE created_at >= :cutoff
        GROUP BY DATE(created_at)
        ORDER BY date DESC
        """
        )

        results = db.session.execute(query, {"cutoff": cutoff}).fetchall()

        return {
        "days": days,
        "data": [
            {
                "date": str(row[0]),
                "total_requests": row[1] or 0,
                "proxy_requests": row[2] or 0,
                "success_rate": float(row[3] or 0.0),
                "missing_auth": row[4] or 0,
                "failures": row[5] or 0,
            }
            for row in results
        ],
        }


@router.get("/domains")
async def get_proxy_domains(
    days: int = Query(7, description="Number of days to look back", ge=1, le=90),
    limit: int = Query(20, description="Number of domains to return", ge=1, le=100),
    min_requests: int = Query(
        5, description="Minimum requests to include domain", ge=1
    ),
) -> dict[str, Any]:
    """Get proxy statistics by domain.

    Returns per-domain proxy usage, success rates, and failure counts.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = text(
        """
        SELECT
            host,
            COUNT(*) as total_requests,
            SUM(CASE WHEN proxy_used IS TRUE THEN 1 ELSE 0 END) as proxy_requests,
            SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) as successes,
            SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) as failures,
            SUM(CASE WHEN proxy_status = 'bypassed' THEN 1 ELSE 0 END) as bypassed,
            ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success'
                                   THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN proxy_used IS TRUE
                                    THEN 1 ELSE 0 END), 0), 2)
                as success_rate,
            MAX(created_at) as last_request
        FROM extraction_telemetry_v2
                WHERE created_at >= :cutoff
                    AND proxy_used IS TRUE
        GROUP BY host
        HAVING COUNT(*) >= :min_requests
        ORDER BY proxy_requests DESC
        LIMIT :limit
        """
        )

        results = db.session.execute(
        query, {"cutoff": cutoff, "min_requests": min_requests, "limit": limit}
        ).fetchall()

        return {
        "days": days,
        "limit": limit,
        "min_requests": min_requests,
        "domains": [
            {
                "host": row[0],
                "total_requests": row[1] or 0,
                "proxy_requests": row[2] or 0,
                "successes": row[3] or 0,
                "failures": row[4] or 0,
                "bypassed": row[5] or 0,
                "success_rate": float(row[6] or 0.0),
                "last_request": str(row[7]) if row[7] else None,
            }
            for row in results
        ],
        }


@router.get("/errors")
async def get_proxy_errors(
    days: int = Query(7, description="Number of days to look back", ge=1, le=90),
    limit: int = Query(20, description="Number of errors to return", ge=1, le=100),
) -> dict[str, Any]:
    """Get common proxy errors.

    Returns most frequent proxy error patterns with occurrence counts and
    affected domains.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = text(
        """
        SELECT
            SUBSTR(proxy_error, 1, 150) as error_pattern,
            COUNT(*) as occurrence_count,
            COUNT(DISTINCT host) as affected_domains,
            MAX(created_at) as last_occurrence
        FROM extraction_telemetry_v2
        WHERE proxy_status = 'failed'
          AND proxy_error IS NOT NULL
          AND created_at >= :cutoff
        GROUP BY SUBSTR(proxy_error, 1, 150)
        ORDER BY occurrence_count DESC
        LIMIT :limit
        """
        )

        results = db.session.execute(query, {"cutoff": cutoff, "limit": limit}).fetchall()

        return {
        "days": days,
        "limit": limit,
        "errors": [
            {
                "error_pattern": row[0],
                "occurrence_count": row[1] or 0,
                "affected_domains": row[2] or 0,
                "last_occurrence": str(row[3]) if row[3] else None,
            }
            for row in results
        ],
        }


@router.get("/authentication")
async def get_authentication_stats(
    days: int = Query(7, description="Number of days to look back", ge=1, le=90)
) -> dict[str, Any]:
    """Get proxy authentication statistics.

    Returns comparison of requests with and without authentication credentials,
    including success rates.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = text(
        """
        SELECT
            CASE WHEN proxy_authenticated = 1
                 THEN 'with_auth' ELSE 'without_auth' END as auth_status,
            COUNT(*) as requests,
            SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) as successes,
            ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success'
                                   THEN 1 ELSE 0 END)
                  / COUNT(*), 2) as success_rate,
            AVG(response_time_ms) as avg_response_time_ms
        FROM extraction_telemetry_v2
        WHERE proxy_used = 1
          AND created_at >= :cutoff
        GROUP BY proxy_authenticated
        ORDER BY proxy_authenticated DESC
        """
        )

        results = db.session.execute(query, {"cutoff": cutoff}).fetchall()

        return {
        "days": days,
        "stats": [
            {
                "auth_status": row[0],
                "requests": row[1] or 0,
                "successes": row[2] or 0,
                "success_rate": float(row[3] or 0.0),
                "avg_response_time_ms": float(row[4] or 0.0) if row[4] else None,
            }
            for row in results
        ],
        }


@router.get("/comparison")
async def get_proxy_vs_direct_comparison(
    days: int = Query(7, description="Number of days to look back", ge=1, le=90)
) -> dict[str, Any]:
    """Compare proxy vs direct connection performance.

    Returns side-by-side comparison of proxy and direct connections including
    success rates, response times, and HTTP status code distributions.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = text(
        """
        SELECT
            CASE WHEN proxy_used = 1
                 THEN 'proxy' ELSE 'direct' END as connection_type,
            COUNT(*) as total_requests,
            SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END)
                as successful_extractions,
            SUM(CASE WHEN http_status_code = 200 THEN 1 ELSE 0 END) as http_200s,
            SUM(CASE WHEN http_status_code IN (403, 503)
                     THEN 1 ELSE 0 END) as bot_detections,
            ROUND(100.0 * SUM(CASE WHEN is_success = 1
                                   THEN 1 ELSE 0 END)
                  / COUNT(*), 2) as extraction_success_rate,
            ROUND(AVG(total_duration_ms), 2) as avg_duration_ms,
            ROUND(AVG(response_time_ms), 2) as avg_response_time_ms
        FROM extraction_telemetry_v2
        WHERE created_at >= :cutoff
        GROUP BY proxy_used
        ORDER BY connection_type
        """
        )

        results = db.session.execute(query, {"cutoff": cutoff}).fetchall()

        return {
        "days": days,
        "comparison": [
            {
                "connection_type": row[0],
                "total_requests": row[1] or 0,
                "successful_extractions": row[2] or 0,
                "http_200s": row[3] or 0,
                "bot_detections": row[4] or 0,
                "extraction_success_rate": float(row[5] or 0.0),
                "avg_duration_ms": float(row[6] or 0.0) if row[6] else None,
                "avg_response_time_ms": float(row[7] or 0.0) if row[7] else None,
            }
            for row in results
        ],
        }


@router.get("/status-distribution")
async def get_proxy_status_distribution(
    days: int = Query(7, description="Number of days to look back", ge=1, le=90)
) -> dict[str, Any]:
    """Get distribution of proxy status values.

    Returns breakdown of proxy_status values (success, failed, bypassed, disabled)
    with counts and percentages.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = text(
        """
        SELECT
            COALESCE(proxy_status, 'null') as status,
            COUNT(*) as count,
            COUNT(DISTINCT host) as unique_hosts
        FROM extraction_telemetry_v2
        WHERE created_at >= :cutoff
        GROUP BY proxy_status
        ORDER BY count DESC
        """
        )

        results = db.session.execute(query, {"cutoff": cutoff}).fetchall()
        total = sum(row[1] for row in results)

        return {
        "days": days,
        "total_requests": total,
        "distribution": [
            {
                "status": row[0],
                "count": row[1] or 0,
                "percentage": (
                    round(100.0 * (row[1] or 0) / total, 2) if total > 0 else 0.0
                ),
                "unique_hosts": row[2] or 0,
            }
            for row in results
        ],
        }


@router.get("/recent-failures")
async def get_recent_proxy_failures(
    hours: int = Query(24, description="Hours to look back", ge=1, le=168),
    limit: int = Query(50, description="Number of failures to return", ge=1, le=200),
) -> dict[str, Any]:
    """Get recent proxy failures with details.

    Returns detailed information about recent proxy failures including URLs,
    error messages, and HTTP status codes.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        query = text(
        """
        SELECT
            created_at,
            host,
            url,
            http_status_code,
            proxy_url,
            proxy_authenticated,
            SUBSTR(proxy_error, 1, 250) as error_preview
        FROM extraction_telemetry_v2
        WHERE proxy_status = 'failed'
          AND created_at >= :cutoff
        ORDER BY created_at DESC
        LIMIT :limit
        """
        )

        results = db.session.execute(query, {"cutoff": cutoff, "limit": limit}).fetchall()

        return {
        "hours": hours,
        "limit": limit,
        "failures": [
            {
                "timestamp": str(row[0]) if row[0] else None,
                "host": row[1],
                "url": row[2],
                "http_status_code": row[3],
                "proxy_url": row[4],
                "proxy_authenticated": bool(row[5]),
                "error_preview": row[6],
            }
            for row in results
        ],
        }


@router.get("/bot-detection")
async def get_bot_detection_analysis(
    days: int = Query(7, description="Number of days to look back", ge=1, le=90),
    limit: int = Query(20, description="Number of domains to return", ge=1, le=100),
) -> dict[str, Any]:
    """Get bot detection patterns by domain.

    Returns domains with high bot detection rates, comparing proxy vs direct
    connection effectiveness.
    """
    with DatabaseManager() as db:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = text(
        """
        SELECT
            host,
            SUM(CASE WHEN proxy_used = 1 AND http_status_code = 403
                     THEN 1 ELSE 0 END) as proxy_403s,
            SUM(CASE WHEN proxy_used = 0 AND http_status_code = 403
                     THEN 1 ELSE 0 END) as direct_403s,
            SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as proxy_total,
            SUM(CASE WHEN proxy_used = 0 THEN 1 ELSE 0 END) as direct_total,
            ROUND(100.0 * SUM(CASE WHEN proxy_used = 1
                                   AND http_status_code = 403
                                   THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN proxy_used = 1
                                    THEN 1 ELSE 0 END), 0), 2)
                as proxy_403_rate,
            ROUND(100.0 * SUM(CASE WHEN proxy_used = 0
                                   AND http_status_code = 403
                                   THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN proxy_used = 0
                                    THEN 1 ELSE 0 END), 0), 2)
                as direct_403_rate
        FROM extraction_telemetry_v2
        WHERE created_at >= :cutoff
          AND http_status_code IN (403, 503)
        GROUP BY host
        HAVING (proxy_total + direct_total) >= 5
        ORDER BY direct_403_rate DESC, direct_total DESC
        LIMIT :limit
        """
        )

        results = db.session.execute(query, {"cutoff": cutoff, "limit": limit}).fetchall()

        return {
        "days": days,
        "limit": limit,
        "domains": [
            {
                "host": row[0],
                "proxy_403s": row[1] or 0,
                "direct_403s": row[2] or 0,
                "proxy_total": row[3] or 0,
                "direct_total": row[4] or 0,
                "proxy_403_rate": float(row[5] or 0.0),
                "direct_403_rate": float(row[6] or 0.0),
            }
            for row in results
        ],
        }
