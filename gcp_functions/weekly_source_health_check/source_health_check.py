from sqlalchemy import text
from datetime import datetime, timedelta
import csv
import io


def get_all_sources(session, limit=None, host_prefix=None):
    """Return sources (id, host, canonical_name) with optional host filter and limit.
    
    Excludes retired sources from health checks.
    """
    base_sql = """
        SELECT id, host, canonical_name
        FROM sources
    """
    params = {}
    where = ["status != 'retired'"]
    if host_prefix:
        where.append("(host ILIKE :hp OR canonical_name ILIKE :hp)")
        params["hp"] = f"{host_prefix}%"
    order_limit = " ORDER BY canonical_name"
    if limit and isinstance(limit, int) and limit > 0:
        order_limit += " LIMIT :lim"
        params["lim"] = int(limit)
    sql = base_sql + " WHERE " + " AND ".join(where) + order_limit
    return session.execute(text(sql), params).fetchall()


def diagnose_source_health(session, source_id, canonical_name, lookback_days=30, host=None, include_samples=True):
    """Diagnose health metrics for a single source (optimized).

    Adds 7d/14d windowed metrics and classification to match legacy CSV.
    """
    diagnostics = {
        "source_id": source_id,
        "source_name": canonical_name,
        "check_date": datetime.utcnow().isoformat(),
        "status": "healthy",
        "issues": [],
        "metrics": {}
    }

    try:
        # Resolve host, status, and discovery_method in one query
        src_row = session.execute(text(
            """
            SELECT host, status, rss_consecutive_failures, rss_last_failed_at, rss_missing_at, paused_at, discovery_method
            FROM sources
            WHERE id = :id
            """
        ), {"id": source_id}).fetchone()
        resolved_host = host if host is not None else (src_row[0] if src_row else None)
        diagnostics["host"] = resolved_host
        source_status = src_row[1:] if src_row else None

        if source_status:
            source_db_status, rss_failures, rss_last_fail, rss_missing, paused_at, discovery_method = source_status
            diagnostics["metrics"]["database_status"] = source_db_status
            diagnostics["metrics"]["discovery_method"] = discovery_method
            diagnostics["metrics"]["rss_consecutive_failures"] = rss_failures
            diagnostics["metrics"]["rss_last_failed_at"] = str(rss_last_fail) if rss_last_fail else None
            diagnostics["metrics"]["rss_missing_since"] = str(rss_missing) if rss_missing else None
            diagnostics["metrics"]["paused_at"] = str(paused_at) if paused_at else None

            if paused_at:
                diagnostics["issues"].append("SOURCE_PAUSED")
                diagnostics["status"] = "critical"

            # Only flag RSS failures if discovery_method is 'rss' (no fallback)
            # Sources with sitemap/homepage discovery don't depend on RSS
            if rss_failures and rss_failures >= 3 and discovery_method == 'rss':
                diagnostics["issues"].append("RSS_FAILURES")
                diagnostics["status"] = "warning" if diagnostics["status"] != "critical" else diagnostics["status"]

        # 2. Discovery activity (7d/14d windows)
        now = datetime.utcnow()
        cutoff_14d = now - timedelta(days=14)
        cutoff_7d = now - timedelta(days=7)
        cutoff_date = now - timedelta(days=lookback_days)
        discovery_stats = session.execute(text(
            """
            SELECT 
                COUNT(CASE WHEN discovered_at >= :cut14 THEN 1 END) AS total_discovered_14d,
                COUNT(CASE WHEN discovered_at >= :cut7 THEN 1 END) AS discovered_7d,
                COUNT(*) AS total_discovered_all,
                COUNT(CASE WHEN status = 'article' THEN 1 END) AS verified_articles,
                COUNT(CASE WHEN discovered_at >= :cutoff THEN 1 END) AS recent_discoveries,
                MAX(discovered_at) AS last_discovery
            FROM candidate_links
            WHERE source_id = :id
            """
        ), {"id": source_id, "cut14": cutoff_14d, "cut7": cutoff_7d, "cutoff": cutoff_date}).fetchone()

        if discovery_stats:
            total_disc_14d, discovered_7d, total_disc_all, verified, recent, last_disc = discovery_stats
            diagnostics["metrics"]["total_discovered_14d"] = total_disc_14d
            diagnostics["metrics"]["discovered_7d"] = discovered_7d
            diagnostics["metrics"]["total_discovered"] = total_disc_all
            diagnostics["metrics"]["verified_articles"] = verified
            diagnostics["metrics"]["recent_discoveries"] = recent
            diagnostics["metrics"]["last_discovery"] = str(last_disc) if last_disc else None
            if recent == 0:
                diagnostics["issues"].append("NO_DISCOVERY")
                diagnostics["status"] = "warning" if diagnostics["status"] != "critical" else diagnostics["status"]

        # 3. Extraction metrics (7d/14d windows) and last extraction
        extraction_stats = session.execute(text(
            """
            SELECT 
                COUNT(DISTINCT cl.id) AS discovered_count_all,
                COUNT(DISTINCT a.id) AS extracted_count_all,
                COUNT(DISTINCT CASE WHEN a.extracted_at >= :cutoff THEN a.id END) AS recent_extracted,
                COUNT(CASE WHEN a.extracted_at >= :cut14 THEN 1 END) AS total_extracted_14d,
                COUNT(CASE WHEN a.extracted_at >= :cut7 THEN 1 END) AS extracted_7d,
                MAX(a.extracted_at) AS last_extraction
            FROM candidate_links cl
            LEFT JOIN articles a ON cl.id = a.candidate_link_id
            WHERE cl.source_id = :id
            """
        ), {"id": source_id, "cutoff": cutoff_date, "cut14": cutoff_14d, "cut7": cutoff_7d}).fetchone()

        if extraction_stats:
            discovered_all, extracted_all, recent_extracted, total_extracted_14d, extracted_7d, last_extraction = extraction_stats
            discovered_14d = diagnostics["metrics"].get("total_discovered_14d", 0) or 0
            extraction_rate_14d = round(100 * (total_extracted_14d or 0) / (discovered_14d or 1), 1) if discovered_14d > 0 else 0
            diagnostics["metrics"]["extraction_rate"] = round(100 * (extracted_all or 0) / (discovered_all or 1), 1) if discovered_all > 0 else 0
            diagnostics["metrics"]["recent_extraction_rate"] = round(100 * (recent_extracted or 0) / (diagnostics["metrics"].get("recent_discoveries") or 1), 1) if diagnostics["metrics"].get("recent_discoveries") else 0
            diagnostics["metrics"]["extracted_articles"] = extracted_all or 0
            diagnostics["metrics"]["recent_extracted_articles"] = recent_extracted or 0
            diagnostics["metrics"]["total_extracted_14d"] = total_extracted_14d or 0
            diagnostics["metrics"]["extracted_7d"] = extracted_7d or 0
            diagnostics["metrics"]["last_extraction"] = str(last_extraction) if last_extraction else None
            diagnostics["metrics"]["extraction_success_rate_14d"] = extraction_rate_14d
            
            if discovered_all > 0 and (extracted_all or 0) == 0:
                diagnostics["issues"].append("EXTRACTION_FAILURE")
                diagnostics["status"] = "warning" if diagnostics["status"] != "critical" else diagnostics["status"]

        # Recent sample URLs (last 5 extracted)
        if include_samples:
            sample_rows = session.execute(text(
                """
                SELECT a.url
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE cl.source_id = :id
                ORDER BY a.extracted_at DESC NULLS LAST
                LIMIT 5
                """
            ), {"id": source_id}).fetchall()
            diagnostics["sample_urls"] = [r[0] for r in sample_rows]

        # 4. Article pipeline status counts (14d) and filter rate (lookback)
        filter_stats = session.execute(text(
            """
            SELECT 
                COUNT(*) AS total_discovered,
                COUNT(CASE WHEN status = 'obituary' THEN 1 END) AS obituaries,
                COUNT(CASE WHEN status = 'opinion' THEN 1 END) AS opinions,
                COUNT(CASE WHEN status = 'not_article' THEN 1 END) AS not_articles,
                COUNT(CASE WHEN status IN ('wire', 'weather') THEN 1 END) AS other_filtered
            FROM candidate_links
            WHERE source_id = :id AND discovered_at >= :cutoff
            """
        ), {"id": source_id, "cutoff": cutoff_date}).fetchone()

        if filter_stats:
            total, obituaries, opinions, not_articles, other = filter_stats
            filter_rate = round(100 * (obituaries + opinions + not_articles + other) / total, 1) if total > 0 else 0
            diagnostics["metrics"]["filter_rate"] = filter_rate
            diagnostics["metrics"]["obituaries_filtered"] = obituaries
            diagnostics["metrics"]["opinions_filtered"] = opinions
            diagnostics["metrics"]["not_articles_filtered"] = not_articles
            diagnostics["metrics"]["other_filtered"] = other

            if filter_rate > 50:
                diagnostics["issues"].append("HIGH_FILTER_RATE")
                diagnostics["status"] = "warning" if diagnostics["status"] != "critical" else diagnostics["status"]

        # Article status counts in last 14d
        article_status = session.execute(text(
            """
            SELECT 
                COUNT(CASE WHEN a.status = 'extracted' AND a.extracted_at >= :cut14 THEN 1 END) AS articles_at_extracted,
                COUNT(CASE WHEN a.status = 'cleaned' AND a.extracted_at >= :cut14 THEN 1 END) AS articles_at_cleaned,
                COUNT(CASE WHEN a.status = 'labeled' AND a.extracted_at >= :cut14 THEN 1 END) AS articles_at_labeled
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE cl.source_id = :id
            """
        ), {"id": source_id, "cut14": cutoff_14d}).fetchone()
        if article_status:
            ae, ac, al = article_status
            diagnostics["metrics"]["articles_at_extracted"] = ae or 0
            diagnostics["metrics"]["articles_at_cleaned"] = ac or 0
            diagnostics["metrics"]["articles_at_labeled"] = al or 0

        # Classification to mimic legacy health_status/issue_details
        # Also update diagnostics["status"] so email summary counts these correctly
        td14 = diagnostics["metrics"].get("total_discovered_14d", 0) or 0
        ex14 = diagnostics["metrics"].get("total_extracted_14d", 0) or 0
        d7 = diagnostics["metrics"].get("discovered_7d", 0) or 0
        e7 = diagnostics["metrics"].get("extracted_7d", 0) or 0
        rate14 = diagnostics["metrics"].get("extraction_success_rate_14d", 0) or 0
        health_status = "Healthy"
        issue_details = None
        if ex14 == 0 and td14 == 0:
            health_status = "No Activity"
            issue_details = "No discoveries or extractions in 14 days"
            diagnostics["status"] = "warning"
            diagnostics["issues"].append("NO_ACTIVITY_14D")
        elif e7 == 0 and td14 > 0:
            health_status = "Extraction Issue"
            issue_details = "No extractions in past 7 days (may indicate scraping failure)"
            diagnostics["status"] = "warning"
            diagnostics["issues"].append("EXTRACTION_STALLED")
        elif d7 == 0 and td14 > 0:
            health_status = "Discovery Issue"
            issue_details = "No recent discoveries (7d); discovery may be paused or misconfigured"
            diagnostics["status"] = "warning"
            diagnostics["issues"].append("DISCOVERY_STALLED")
        elif td14 > 0 and ex14 > 0 and rate14 < 25.0:
            health_status = "Warning"
            issue_details = "Low extraction success rate (<25%)"
            diagnostics["status"] = "warning"
            diagnostics["issues"].append("LOW_EXTRACTION_RATE")
        diagnostics["health_status"] = health_status
        diagnostics["issue_details"] = issue_details

    except Exception as e:
        diagnostics["status"] = "error"
        diagnostics["issues"].append(f"ERROR: {str(e)}")

    return diagnostics


def export_diagnostics_csv(diagnostics):
    """Export diagnostics list to CSV content string (legacy-friendly format)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Rank', 'Hostname', 'Health Status', 'Issue Details', 'Source Status',
        'Discovered (14d)', 'Discovered (7d)', 'Extracted (14d)', 'Extracted (7d)',
        'Extraction Success Rate (%)', 'Last Discovery', 'Last Extraction',
        'Articles at Extracted', 'Articles at Cleaned', 'Articles at Labeled'
    ])
    order = {'Extraction Issue': 0, 'Discovery Issue': 1, 'No Activity': 2, 'Warning': 3, 'Healthy': 4}
    sorted_diags = sorted(diagnostics, key=lambda d: order.get(d.get('health_status') or 'Healthy', 5))
    for rank, d in enumerate(sorted_diags, 1):
        m = d.get('metrics', {})
        writer.writerow([
            rank,
            d.get('host') or d.get('source_name'),
            d.get('health_status') or 'Healthy',
            d.get('issue_details') or '',
            m.get('database_status') or 'active',
            m.get('total_discovered_14d', 0) or 0,
            m.get('discovered_7d', 0) or 0,
            m.get('total_extracted_14d', 0) or 0,
            m.get('extracted_7d', 0) or 0,
            m.get('extraction_success_rate_14d', 0) or 0,
            m.get('last_discovery') or '',
            m.get('last_extraction') or '',
            m.get('articles_at_extracted', 0) or 0,
            m.get('articles_at_cleaned', 0) or 0,
            m.get('articles_at_labeled', 0) or 0,
        ])
    return output.getvalue()
