"""
Weekly health check for news sources.
Generates diagnostic report showing:
1. Paused/inactive sources
2. Discovery issues
3. Extraction/scraping issues
4. Filtering issues (non-news classification)
"""

from src.models.database import DatabaseManager
from sqlalchemy import text
from datetime import datetime, timedelta
import json
import csv
import os
import subprocess
import shutil
import re
from typing import Optional, Dict, Any, List


def get_all_sources(session, limit=None, host_prefix=None):
    """Return sources (id, host, canonical_name) with optional host filter and limit.

    Args:
        session: SQLAlchemy session
        limit: optional int to cap number of sources
        host_prefix: optional string; filters WHERE host or canonical_name
        starts with this value
    """
    base_sql = """
        SELECT id, host, canonical_name
        FROM sources
    """
    params = {}
    where = []
    # Exclude permanently closed outlets
    where.append("COALESCE(status, '') <> 'retired'")
    if host_prefix:
        where.append(
            "(host ILIKE :hp OR canonical_name ILIKE :hp)"
        )
        params["hp"] = f"{host_prefix}%"
    order_limit = " ORDER BY canonical_name"
    if limit and isinstance(limit, int) and limit > 0:
        order_limit += " LIMIT :lim"
        params["lim"] = int(limit)
    sql = base_sql + (" WHERE " + " AND ".join(where) if where else "") + order_limit
    return session.execute(text(sql), params).fetchall()


def diagnose_source_health(
    session,
    source_id,
    canonical_name,
    lookback_days=30,
    host=None,
    include_samples=True,
    active_tests: bool = False,
    test_options: Optional[Dict[str, Any]] = None,
):
    """Diagnose health metrics for a single source.

    Optimizations:
    - Avoid redundant query for host when provided
    - Merge host+status fetch from sources into single query
    - Optional skipping of sample URL query for faster runs
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
        # 1. Resolve host and status in a single query
        src_row = session.execute(
            text(
                """
                SELECT
                    host,
                    status,
                    rss_consecutive_failures,
                    rss_last_failed_at,
                    rss_missing_at,
                    paused_at
                FROM sources
                WHERE id = :id
                """
            ),
            {"id": source_id},
        ).fetchone()
        resolved_host = host if host is not None else (src_row[0] if src_row else None)
        diagnostics["host"] = resolved_host
        # Paused/inactive details
        source_status = src_row[1:] if src_row else None
        
        if source_status:
            (
                source_db_status,
                rss_failures,
                rss_last_fail,
                rss_missing,
                paused_at,
            ) = source_status
            diagnostics["metrics"]["database_status"] = source_db_status
            diagnostics["metrics"]["rss_consecutive_failures"] = rss_failures
            diagnostics["metrics"]["rss_last_failed_at"] = (
                str(rss_last_fail) if rss_last_fail else None
            )
            diagnostics["metrics"]["rss_missing_since"] = (
                str(rss_missing) if rss_missing else None
            )
            diagnostics["metrics"]["paused_at"] = str(paused_at) if paused_at else None
            
            if paused_at:
                diagnostics["issues"].append("SOURCE_PAUSED")
                diagnostics["status"] = "critical"
            
            if rss_failures and rss_failures >= 3:
                diagnostics["issues"].append("RSS_FAILURES")
                diagnostics["status"] = "warning"
        
        # 2. Check discovery activity
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
        discovery_stats = session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total_discovered,
                    COUNT(CASE WHEN status = 'article' THEN 1 END) AS verified_articles,
                    COUNT(
                        CASE WHEN discovered_at >= :cutoff THEN 1 END
                    ) AS recent_discoveries,
                    MAX(discovered_at) AS last_discovery
                FROM candidate_links
                WHERE source_id = :id
                """
            ),
            {"id": source_id, "cutoff": cutoff_date},
        ).fetchone()
        
        if discovery_stats:
            total_disc, verified, recent, last_disc = discovery_stats
            diagnostics["metrics"]["total_discovered"] = total_disc
            diagnostics["metrics"]["verified_articles"] = verified
            diagnostics["metrics"]["recent_discoveries"] = recent
            diagnostics["metrics"]["last_discovery"] = (
                str(last_disc) if last_disc else None
            )
            
            if recent == 0:
                diagnostics["issues"].append("NO_DISCOVERY")
                if diagnostics["status"] != "critical":
                    diagnostics["status"] = "warning"

        # 2b. Windowed discovery metrics (7d/14d)
        now = datetime.utcnow()
        cutoff_14d = now - timedelta(days=14)
        cutoff_7d = now - timedelta(days=7)
        discovery_window = session.execute(
            text(
                """
                SELECT
                    COUNT(
                        CASE WHEN discovered_at >= :cut14 THEN 1 END
                    ) AS total_discovered_14d,
                    COUNT(CASE WHEN discovered_at >= :cut7 THEN 1 END) AS discovered_7d
                FROM candidate_links
                WHERE source_id = :id
                """
            ),
            {"id": source_id, "cut14": cutoff_14d, "cut7": cutoff_7d},
        ).fetchone()
        if discovery_window:
            td14, d7 = discovery_window
            diagnostics["metrics"]["total_discovered_14d"] = td14 or 0
            diagnostics["metrics"]["discovered_7d"] = d7 or 0
        
        # 3. Check extraction success rate
        extraction_stats = session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT cl.id) AS discovered_count,
                    COUNT(DISTINCT a.id) AS extracted_count,
                    COUNT(
                        DISTINCT CASE WHEN a.extracted_at >= :cutoff THEN a.id END
                    ) AS recent_extracted
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                WHERE cl.source_id = :id
                """
            ),
            {"id": source_id, "cutoff": cutoff_date},
        ).fetchone()
        
        if extraction_stats:
            discovered, extracted, recent_extracted = extraction_stats
            diagnostics["metrics"]["extraction_rate"] = (
                round(100 * extracted / discovered, 1) if discovered > 0 else 0
            )
            recent_val = diagnostics["metrics"].get("recent_discoveries", 0)
            diagnostics["metrics"]["recent_extraction_rate"] = (
                round(100 * recent_extracted / (recent_val or 1), 1)
                if recent_val
                else 0
            )
            diagnostics["metrics"]["extracted_articles"] = extracted
            diagnostics["metrics"]["recent_extracted_articles"] = recent_extracted
            
            if discovered > 0 and extracted == 0:
                diagnostics["issues"].append("EXTRACTION_FAILURE")
                if diagnostics["status"] != "critical":
                    diagnostics["status"] = "warning"

        # 3b. Windowed extraction metrics (7d/14d) and last extraction
        extraction_window = session.execute(
            text(
                """
                SELECT
                    COUNT(
                        CASE WHEN a.extracted_at >= :cut14 THEN 1 END
                    ) AS total_extracted_14d,
                    COUNT(CASE WHEN a.extracted_at >= :cut7 THEN 1 END) AS extracted_7d,
                    MAX(a.extracted_at) AS last_extraction
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE cl.source_id = :id
                """
            ),
            {"id": source_id, "cut14": cutoff_14d, "cut7": cutoff_7d},
        ).fetchone()
        if extraction_window:
            te14, e7, last_ext = extraction_window
            diagnostics["metrics"]["total_extracted_14d"] = te14 or 0
            diagnostics["metrics"]["extracted_7d"] = e7 or 0
            diagnostics["metrics"]["last_extraction"] = (
                str(last_ext) if last_ext else None
            )

        # 4b. Article status counts (14d) for pipeline stages
        article_status = session.execute(
            text(
                """
                SELECT
                    COUNT(
                        CASE WHEN a.status = 'extracted' AND a.extracted_at >= :cut14
                            THEN 1 END
                    ) AS articles_at_extracted,
                    COUNT(
                        CASE WHEN a.status = 'cleaned' AND a.extracted_at >= :cut14
                            THEN 1 END
                    ) AS articles_at_cleaned,
                    COUNT(
                        CASE WHEN a.status = 'labeled' AND a.extracted_at >= :cut14
                            THEN 1 END
                    ) AS articles_at_labeled
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE cl.source_id = :id
                """
            ),
            {"id": source_id, "cut14": cutoff_14d},
        ).fetchone()
        if article_status:
            ae, ac, al = article_status
            diagnostics["metrics"]["articles_at_extracted"] = ae or 0
            diagnostics["metrics"]["articles_at_cleaned"] = ac or 0
            diagnostics["metrics"]["articles_at_labeled"] = al or 0
        
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

        # Optional: perform basic HTTP probes to diagnose scraping/extraction failures
        if active_tests:
            try:
                opts = test_options or {}
                max_samples = int(opts.get("max_samples", 3))
                namespace = str(opts.get("namespace", "production"))
                extraction_pod = opts.get("extraction_pod")
                timeout = int(opts.get("timeout", 20))

                # Build probe target list: host homepage + recent sample URLs
                probe_targets: List[str] = []
                if resolved_host:
                    scheme = "https://" if not resolved_host.startswith("http") else ""
                    probe_targets.append(f"{scheme}{resolved_host}")
                for u in diagnostics.get("sample_urls", [])[:max_samples]:
                    probe_targets.append(u)

                # Run probes
                probe_results: List[Dict[str, Any]] = []
                pod_for_exec = None
                if extraction_pod:
                    pod_for_exec = extraction_pod
                else:
                    pod_for_exec = _select_extraction_pod(namespace)

                for url in probe_targets:
                    if pod_for_exec:
                        res = _http_probe_via_extraction_pod(pod_for_exec, namespace, url, timeout)
                    else:
                        res = _http_probe_via_requests(url, timeout)
                    res["blocked_reason"] = _detect_block_markers(res.get("snippet", ""), res.get("headers", {}))
                    # minimize stored snippet
                    if "snippet" in res and isinstance(res["snippet"], str):
                        res["snippet"] = res["snippet"][:256]
                    probe_results.append({
                        "url": url,
                        "status_code": res.get("status_code"),
                        "content_type": res.get("content_type"),
                        "server": res.get("server"),
                        "final_url": res.get("final_url"),
                        "blocked_reason": res.get("blocked_reason"),
                    })

                diagnostics["active_tests"] = {
                    "namespace": namespace,
                    "extraction_pod": pod_for_exec,
                    "results": probe_results,
                    "summary": {
                        "successful": sum(1 for r in probe_results if (r.get("status_code") or 0) < 400 and not r.get("blocked_reason")),
                        "blocked": sum(1 for r in probe_results if r.get("blocked_reason")),
                        "errors": sum(1 for r in probe_results if (r.get("status_code") or 0) >= 400),
                    }
                }
                # If we see blocking and extraction issues, escalate status to warning
                if diagnostics["active_tests"]["summary"]["blocked"] > 0:
                    if "EXTRACTION_FAILURE" not in diagnostics["issues"]:
                        diagnostics["issues"].append("POSSIBLE_BOT_PROTECTION")
                    diagnostics["status"] = "warning" if diagnostics["status"] != "critical" else diagnostics["status"]
            except Exception as e:
                # Non-fatal; record error in diagnostics
                diagnostics.setdefault("issues", []).append(f"ACTIVE_TEST_ERROR: {str(e)}")

        # 4. Check filtering rate (articles classified as non-news)
        filter_stats = session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total_discovered,
                    COUNT(CASE WHEN status = 'obituary' THEN 1 END) AS obituaries,
                    COUNT(CASE WHEN status = 'opinion' THEN 1 END) AS opinions,
                    COUNT(CASE WHEN status = 'not_article' THEN 1 END) AS not_articles,
                    COUNT(
                        CASE WHEN status IN ('wire', 'weather') THEN 1 END
                    ) AS other_filtered
                FROM candidate_links
                WHERE source_id = :id AND discovered_at >= :cutoff
                """
            ),
            {"id": source_id, "cutoff": cutoff_date},
        ).fetchone()
        
        if filter_stats:
            total, obituaries, opinions, not_articles, other = filter_stats
            filter_rate = (
                round(100 * (obituaries + opinions + not_articles + other) / total, 1)
                if total > 0
                else 0
            )
            
            diagnostics["metrics"]["filter_rate"] = filter_rate
            diagnostics["metrics"]["obituaries_filtered"] = obituaries
            diagnostics["metrics"]["opinions_filtered"] = opinions
            diagnostics["metrics"]["not_articles_filtered"] = not_articles
            diagnostics["metrics"]["other_filtered"] = other
            
            if filter_rate > 50:
                diagnostics["issues"].append("HIGH_FILTER_RATE")
                if diagnostics["status"] != "critical":
                    diagnostics["status"] = "warning"
    
    except Exception as e:
        diagnostics["status"] = "error"
        diagnostics["issues"].append(f"ERROR: {str(e)}")
    
    # Legacy-style health classification using 7d/14d windows
    try:
        td14 = diagnostics["metrics"].get("total_discovered_14d", 0) or 0
        ex14 = diagnostics["metrics"].get("total_extracted_14d", 0) or 0
        d7 = diagnostics["metrics"].get("discovered_7d", 0) or 0
        e7 = diagnostics["metrics"].get("extracted_7d", 0) or 0
        rate14 = 0
        if td14 > 0:
            rate14 = round(100 * (ex14 or 0) / (td14 or 1), 1)
        diagnostics["metrics"]["extraction_success_rate_14d"] = rate14
        health_status = "Healthy"
        issue_details = None
        if ex14 == 0 and td14 == 0:
            health_status = "No Activity"
            issue_details = "No discoveries or extractions in 14 days"
        elif e7 == 0 and td14 > 0:
            health_status = "Extraction Issue"
            issue_details = "No extractions in past 7 days"
        elif d7 == 0 and td14 > 0:
            health_status = "Discovery Issue"
            issue_details = "No recent discoveries (7d)"
        elif td14 > 0 and ex14 > 0 and rate14 < 25.0:
            health_status = "Warning"
            issue_details = "Low extraction success rate (<25%)"
        diagnostics["health_status"] = health_status
        diagnostics["issue_details"] = issue_details
    except Exception:
        pass

    return diagnostics


def _select_extraction_pod(namespace: str) -> Optional[str]:
    """Select a ready extraction pod in the given namespace using kubectl.

    Returns pod name or None if kubectl unavailable or no pods found.
    """
    if shutil.which("kubectl") is None:
        return None
    try:
        cmd = [
            "kubectl", "get", "pods", "-n", namespace, "-o", "json"
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
        items = data.get("items", [])
        for item in items:
            name = item.get("metadata", {}).get("name", "")
            if not name.startswith("extraction-"):
                continue
            # Check Ready condition
            conds = item.get("status", {}).get("conditions", [])
            ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds)
            if ready:
                return name
        return None
    except Exception:
        return None


def _http_probe_via_extraction_pod(pod: str, namespace: str, url: str, timeout: int) -> Dict[str, Any]:
    """Run a minimal curl-based probe inside an extraction pod and return parsed details."""
    headers_cmd = (
        "curl -sS -L -m {timeout} -o /dev/null -D - "
        "-w \"HTTP_CODE=%{{http_code}}\nFINAL_URL=%{{url_effective}}\nCONTENT_TYPE=%{{content_type}}\nSERVER=%{{server}}\n\" "
        "\"{url}\""
    ).format(timeout=timeout, url=url)
    body_cmd = "curl -sS -L -m {timeout} \"{url}\" | head -c 4096".format(timeout=timeout, url=url)
    try:
        # Headers
        h_proc = subprocess.run([
            "kubectl", "exec", "-n", namespace, pod, "--", "bash", "-lc", headers_cmd
        ], capture_output=True, text=True, check=True)
        # Body snippet
        b_proc = subprocess.run([
            "kubectl", "exec", "-n", namespace, pod, "--", "bash", "-lc", body_cmd
        ], capture_output=True, text=True, check=True)
        info = {
            "headers_raw": h_proc.stdout,
            "snippet": b_proc.stdout,
        }
        # Parse header metrics
        status_match = re.search(r"HTTP_CODE=(\d+)", h_proc.stdout)
        final_url_match = re.search(r"FINAL_URL=(.*)", h_proc.stdout)
        ctype_match = re.search(r"CONTENT_TYPE=(.*)", h_proc.stdout)
        server_match = re.search(r"SERVER=(.*)", h_proc.stdout)
        info["status_code"] = int(status_match.group(1)) if status_match else None
        info["final_url"] = final_url_match.group(1).strip() if final_url_match else None
        info["content_type"] = ctype_match.group(1).strip() if ctype_match else None
        info["server"] = server_match.group(1).strip() if server_match else None
        info["headers"] = _parse_header_block(h_proc.stdout)
        return info
    except subprocess.CalledProcessError as e:
        return {"error": f"kubectl exec failed: {e}"}


def _http_probe_via_requests(url: str, timeout: int) -> Dict[str, Any]:
    """Basic HTTP probe using requests with a desktop UA and redirects allowed."""
    import requests
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        snippet = resp.text[:4096] if resp.text else ""
        return {
            "status_code": resp.status_code,
            "final_url": str(resp.url),
            "content_type": resp.headers.get("Content-Type"),
            "server": resp.headers.get("Server"),
            "headers": dict(resp.headers),
            "snippet": snippet,
        }
    except Exception as e:
        return {"error": str(e)}


def _parse_header_block(block: str) -> Dict[str, str]:
    """Parse raw header block from curl -D - output into a dict."""
    headers: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
    return headers


def _detect_block_markers(body_snippet: str, headers: Dict[str, str]) -> Optional[str]:
    """Detect common bot/anti-scraping blocks in body or headers."""
    if not body_snippet and not headers:
        return None
    patterns = [
        (r"PerimeterX", "PerimeterX"),
        (r"Akamai Bot Manager|akamai(?:-)?bot", "Akamai Bot Manager"),
        (r"Cloudflare|cf-", "Cloudflare"),
        (r"Just a moment\.|Attention Required!", "Cloudflare Challenge"),
        (r"captcha|g-recaptcha|hcaptcha|px-captcha", "Captcha"),
        (r"datadome", "DataDome"),
        (r"shield\s*square", "ShieldSquare"),
        (r"incapsula|imperva", "Imperva/Incapsula"),
        (r"bot\s*protection", "Generic Bot Protection"),
    ]
    text = body_snippet or ""
    # Check headers too (e.g., cf headers)
    hdr_text = " ".join([f"{k}:{v}" for k, v in (headers or {}).items()])
    for regex, label in patterns:
        if re.search(regex, text, re.IGNORECASE) or re.search(regex, hdr_text, re.IGNORECASE):
            return label
    return None


def generate_health_report(
    session,
    lookback_days=30,
    limit=None,
    host_prefix=None,
    include_samples=True,
    active_tests: bool = False,
    test_options: Optional[Dict[str, Any]] = None,
):
    """Generate health report for all or filtered sources with optional limit."""
    sources = get_all_sources(session, limit=limit, host_prefix=host_prefix)
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_sources": len(sources),
        "sources": []
    }
    for source_id, host, canonical_name in sources:
        diagnostics = diagnose_source_health(
            session,
            source_id,
            canonical_name,
            lookback_days=lookback_days,
            host=host,
            include_samples=include_samples,
            active_tests=active_tests,
            test_options=test_options,
        )
        report["sources"].append(diagnostics)
    
    # Summarize
    critical_count = sum(1 for s in report["sources"] if s["status"] == "critical")
    warning_count = sum(1 for s in report["sources"] if s["status"] == "warning")
    error_count = sum(1 for s in report["sources"] if s["status"] == "error")
    
    healthy_count = (
        len(report["sources"]) - critical_count - warning_count - error_count
    )
    report["summary"] = {
        "healthy": healthy_count,
        "warning": warning_count,
        "critical": critical_count,
        "error": error_count,
    }
    
    return report


def export_report_csv(report, output_path):
    """Export report to CSV (legacy path-based export)."""
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # Header
        writer.writerow([
            'Source UUID',
            'Host',
            'Source Name',
            'Status',
            'Issues',
            'Last Discovery',
            'Recent Discoveries',
            'Extracted Articles',
            'Extraction Rate (%)',
            'Filter Rate (%)',
            'Sample URLs'
        ])
        # Data rows
        for source in report["sources"]:
            sample_urls = source.get('sample_urls', [])
            writer.writerow([
                source.get("source_id"),
                source.get("host"),
                source.get("source_name"),
                source.get("status"),
                "; ".join(source.get("issues", [])) if source.get("issues") else "None",
                source.get("metrics", {}).get("last_discovery", "N/A"),
                source.get("metrics", {}).get("recent_discoveries", 0),
                source.get("metrics", {}).get("extracted_articles", 0),
                source.get("metrics", {}).get("extraction_rate", "N/A"),
                source.get("metrics", {}).get("filter_rate", "N/A"),
                "; ".join(sample_urls)
            ])


def export_diagnostics_csv(diagnostics):
    """Export diagnostics list to CSV content string (Cloud Function usage)."""
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Source UUID', 'Host', 'Source Name', 'Status', 'Issues',
        'Last Discovery', 'Recent Discoveries', 'Extracted Articles',
        'Extraction Rate (%)', 'Filter Rate (%)', 'Sample URLs'
    ])
    for d in diagnostics:
        sample_urls = d.get('sample_urls', [])
        writer.writerow([
            d.get('source_id'),
            d.get('host'),
            d.get('source_name'),
            d.get('status'),
            '; '.join(d.get('issues', [])) if d.get('issues') else 'None',
            d.get('metrics', {}).get('last_discovery', 'N/A'),
            d.get('metrics', {}).get('recent_discoveries', 0),
            d.get('metrics', {}).get('extracted_articles', 0),
            d.get('metrics', {}).get('extraction_rate', 'N/A'),
            d.get('metrics', {}).get('filter_rate', 'N/A'),
            '; '.join(sample_urls)
        ])
    return output.getvalue()


def export_diagnostics_legacy_csv(diagnostics):
    """Export diagnostics to legacy-friendly CSV (matches CF attachment)."""
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Rank', 'Hostname', 'Health Status', 'Issue Details', 'Source Status',
        'Discovered (14d)', 'Discovered (7d)', 'Extracted (14d)', 'Extracted (7d)',
        'Extraction Success Rate (%)', 'Last Discovery', 'Last Extraction',
        'Articles at Extracted', 'Articles at Cleaned', 'Articles at Labeled'
    ])
    order = {
        'Extraction Issue': 0,
        'Discovery Issue': 1,
        'No Activity': 2,
        'Warning': 3,
        'Healthy': 4,
    }
    sorted_diags = sorted(
        diagnostics,
        key=lambda d: order.get(d.get('health_status') or 'Healthy', 5),
    )
    for rank, d in enumerate(sorted_diags, 1):
        m = d.get('metrics', {})
        # Compute rate if not present
        td14 = m.get('total_discovered_14d', 0) or 0
        ex14 = m.get('total_extracted_14d', 0) or 0
        rate = m.get('extraction_success_rate_14d')
        if rate is None:
            rate = round(100 * (ex14 or 0) / (td14 or 1), 1) if td14 > 0 else 0
        writer.writerow([
            rank,
            d.get('host') or d.get('source_name') or '',
            d.get('health_status') or 'Healthy',
            d.get('issue_details') or '',
            m.get('database_status') or 'active',
            td14,
            m.get('discovered_7d', 0) or 0,
            ex14,
            m.get('extracted_7d', 0) or 0,
            rate,
            m.get('last_discovery') or '',
            m.get('last_extraction') or '',
            m.get('articles_at_extracted', 0) or 0,
            m.get('articles_at_cleaned', 0) or 0,
            m.get('articles_at_labeled', 0) or 0,
        ])
    return output.getvalue()


def export_report_json(report, output_path):
    """Export full report as JSON for archival and analysis."""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)


def main():
    db = DatabaseManager()
    import argparse
    p = argparse.ArgumentParser(
        description="Generate weekly source health report"
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N sources",
    )
    p.add_argument(
        "--host",
        type=str,
        default=None,
        help="Filter sources by host/canonical_name prefix",
    )
    p.add_argument(
        "--days",
        type=int,
        default=30,
        help="Lookback window in days for discovery/extraction metrics",
    )
    p.add_argument(
        "--no-samples",
        action="store_true",
        help="Skip sample URL queries for faster runs",
    )
    p.add_argument(
        "--active-tests",
        action="store_true",
        help="Run basic HTTP probes for sample URLs to detect bot protection",
    )
    p.add_argument(
        "--extraction-pod",
        type=str,
        default=None,
        help="Explicit extraction pod name to exec into for HTTP probes",
    )
    p.add_argument(
        "--namespace",
        type=str,
        default="production",
        help="Kubernetes namespace for extraction pods (default: production)",
    )
    p.add_argument(
        "--max-sample-tests",
        type=int,
        default=3,
        help="Max number of sample URLs to probe per source",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP probe timeout in seconds",
    )
    args = p.parse_args()

    print("Generating source health report...")
    with db.get_session() as session:
        report = generate_health_report(
            session,
            lookback_days=args.days,
            limit=args.limit,
            host_prefix=args.host,
            include_samples=(not args.no_samples),
            active_tests=args.active_tests,
            test_options={
                "max_samples": args.max_sample_tests,
                "namespace": args.namespace,
                "extraction_pod": args.extraction_pod,
                "timeout": args.timeout,
            },
        )

        os.makedirs("reports", exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        csv_path = f"reports/source_health_{timestamp}.csv"
        legacy_csv_path = f"reports/source_health_legacy_{timestamp}.csv"
        json_path = f"reports/source_health_{timestamp}.json"
        export_report_csv(report, csv_path)
        # Also export legacy-aligned CSV matching Cloud Function format
        legacy_csv = export_diagnostics_legacy_csv(report["sources"])
        with open(legacy_csv_path, 'w', encoding='utf-8') as f:
            f.write(legacy_csv)
        export_report_json(report, json_path)

        print("Report generated:")
        print(f"  CSV: {csv_path}")
        print(f"  Legacy CSV: {legacy_csv_path}")
        print(f"  JSON: {json_path}")
        print()
        print("Summary:")
        print(f"  Healthy: {report['summary']['healthy']}")
        print(f"  Warnings: {report['summary']['warning']}")
        print(f"  Critical: {report['summary']['critical']}")
        print(f"  Errors: {report['summary']['error']}")
        print()
        print("Sources with issues:")
        for source in report["sources"]:
            if source.get("issues"):
                issues_str = ", ".join(source["issues"]) if source["issues"] else ""
                print(
                    f"  {source['source_name']}: {source['status']} - {issues_str}"
                )


if __name__ == "__main__":
    main()
