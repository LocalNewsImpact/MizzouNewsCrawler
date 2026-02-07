#!/usr/bin/env python3
import argparse
import subprocess
import sys
import json
import time
from datetime import datetime, timedelta

try:
    import requests
except Exception:
    requests = None

DEFAULT_HOSTS = [
    "newstribune.com",
    "republicmonitor.com",
    "kq2.com",
    "jamesporttricountyweekly.com",
    "comobuz.com",
    "lamardemocrat.com",
    "griffonnews.com",
    "greenfieldvedette.com",
    "missouribusinessalert.com",
]

WAF_HINTS = [
    "perimeterx", "px-captcha", "px-", "akamai", "ak_bmsc", "bm_sv",
    "cloudflare", "cf-chl", "cf-ray", "captcha", "hcaptcha", "recaptcha",
    "access denied", "blocked", "bot", "verify you are human"
]

def find_extraction_pod(namespace: str = "production") -> str | None:
    """Return the name of a running extraction pod in the namespace, if any."""
    try:
        out = subprocess.check_output([
            "kubectl", "get", "pods", "-n", namespace, "-o", "json"
        ], text=True)
        data = json.loads(out)
        for item in data.get("items", []):
            name = (item.get("metadata") or {}).get("name") or ""
            phase = (item.get("status") or {}).get("phase") or ""
            if name.startswith("extraction-") and phase == "Running":
                return name
    except Exception:
        pass
    return None

def run_article_test_in_pod(url: str, namespace: str = "production", pod: str | None = None) -> dict:
    """Run a simple HTTP access + text extraction inside an extraction pod."""
    if not pod:
        pod = find_extraction_pod(namespace)
    if not pod:
        return {"error": "no extraction pod found"}

    inline = r"""
import json, re, time
from urllib.request import Request, urlopen

url = '__URL__'
ua = 'Mozilla/5.0 (Diagnostics)'
result = {}
start = time.time()
try:
    req = Request(url, headers={'User-Agent': ua})
    with urlopen(req, timeout=25) as resp:
        status = getattr(resp, 'status', 200)
        headers = dict(resp.headers.items()) if hasattr(resp, 'headers') else {}
        data = resp.read()
    elapsed = int((time.time() - start) * 1000)
    html = data.decode('utf-8', 'replace')
    lhtml = html.lower()
    wafs = []
    for w in ['perimeterx','px-captcha','akamai','cloudflare','captcha','recaptcha','hcaptcha','verify you are human','access denied']:
        if w in lhtml:
            wafs.append(w)
    # strip script/style and pull <p> text
    tmp = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.I)
    tmp = re.sub(r'<style\b[^>]*>[\s\S]*?</style>', '', tmp, flags=re.I)
    paras = re.findall(r'<p[^>]*>([\s\S]*?)</p>', tmp, flags=re.I)
    texts = [re.sub('<[^>]+>', ' ', p) for p in paras]
    s = ' '.join(texts)
    s = re.sub(r'\s+', ' ', s).strip()
    preview = s[:1000]
    result = {
        'http': {'status': status, 'elapsed_ms': elapsed, 'content_len': len(html), 'waf_hints': wafs},
        'extraction': {'paragraphs': len(texts), 'preview': preview}
    }
except Exception as e:
    result = {'error': str(e)}
print(json.dumps(result))
"""
    py = inline.replace('__URL__', url)
    cmd = [
        "kubectl", "exec", "-n", namespace, pod, "--",
        "python", "-c", py
    ]
    try:
        out = subprocess.check_output(cmd, text=True)
        return json.loads(out.strip())
    except Exception as e:
        return {"error": f"pod exec failed: {e}"}

def local_article_test(url: str) -> dict:
    """Local fallback: simple HTTP + naive text extraction using urllib."""
    try:
        import urllib.request
        import re, time
        start = time.time()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Diagnostics)'})
        with urllib.request.urlopen(req, timeout=25) as resp:
            status = getattr(resp, 'status', 200)
            data = resp.read()
        elapsed = int((time.time() - start) * 1000)
        html = data.decode('utf-8', 'replace')
        lhtml = html.lower()
        wafs = [w for w in WAF_HINTS if w in lhtml]
        tmp = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.I)
        tmp = re.sub(r'<style\b[^>]*>[\s\S]*?</style>', '', tmp, flags=re.I)
        paras = re.findall(r'<p[^>]*>([\s\S]*?)</p>', tmp, flags=re.I)
        texts = [re.sub('<[^>]+>', ' ', p) for p in paras]
        s = ' '.join(texts)
        s = re.sub(r'\s+', ' ', s).strip()
        preview = s[:1000]
        return {
            'http': {'status': status, 'elapsed_ms': elapsed, 'content_len': len(html), 'waf_hints': wafs},
            'extraction': {'paragraphs': len(texts), 'preview': preview}
        }
    except Exception as e:
        return {'error': str(e)}

def run_prod_db_query(hosts, hours=168, namespace="production", deployment="mizzou-api"):
    hosts_json = json.dumps(hosts)
    hours_str = str(hours)
    # First resolve source UUIDs from provided host domains
    resolve_sources_template = """
from src.models.database import DatabaseManager
from sqlalchemy import text
import json
db = DatabaseManager()
out = []
with db.get_session() as s:
    hosts = json.loads('__HOSTS_JSON__')
    mapping = []
    for h in hosts:
        try:
            rows = s.execute(text('''
                SELECT id, host, canonical_name
                FROM sources
                WHERE host = :host OR host = :host_www OR host ILIKE '%' || :host
            '''), {"host": h, "host_www": 'www.' + h}).fetchall()
            if rows:
                for r in rows:
                    mapping.append({"host": h, "source_id": str(r[0]), "matched_host": r[1]})
            else:
                mapping.append({"host": h, "error": "source not found"})
        except Exception as e:
            mapping.append({"host": h, "error": str(e)})
print(json.dumps(mapping))
"""
    py_resolve = resolve_sources_template.replace('__HOSTS_JSON__', hosts_json)
    cmd = [
        "kubectl", "exec", "-n", namespace,
        f"deployment/{deployment}", "--",
        "python", "-c", py_resolve
    ]
    try:
        mapping = json.loads(subprocess.check_output(cmd, text=True).strip())
    except Exception as e:
        return [{"host": h, "error": f"kubectl exec failed resolving sources: {e}"} for h in hosts]

    # Now run aggregated metrics per host (multiple source UUIDs possible)
    metrics_template = """
from src.models.database import DatabaseManager
from sqlalchemy import text
import json
db = DatabaseManager()
out = []
with db.get_session() as s:
    items = json.loads('__ITEMS_JSON__')
    hours = '__HOURS__'
    for it in items:
        host = it.get('host')
        sids = it.get('source_ids') or []
        if not sids:
            errs = it.get('errors') or []
            out.append({"host": host, "error": (errs[0] if errs else 'missing source_ids')})
            continue
        try:
            discovered = 0
            verified_article = 0
            extracted = 0
            cand_status = {}
            art_status = {}
            recent_all = []
            final_status = {}
            for sid in sids:
                agg = s.execute(text('''
                    SELECT
                        COUNT(*) FILTER (WHERE cl.discovered_at >= NOW() - INTERVAL '__HOURS__ hours') AS discovered,
                        COUNT(*) FILTER (WHERE cl.status = 'article' AND cl.discovered_at >= NOW() - INTERVAL '__HOURS__ hours') AS verified_article,
                        COUNT(a.id) FILTER (WHERE a.extracted_at >= NOW() - INTERVAL '__HOURS__ hours') AS extracted
                    FROM candidate_links cl
                    LEFT JOIN articles a ON a.candidate_link_id = cl.id
                    WHERE cl.source_id = :sid
                '''.replace('__HOURS__', hours)), {"sid": sid}).fetchone()
                if agg:
                    discovered += int(agg[0] or 0)
                    verified_article += int(agg[1] or 0)
                    extracted += int(agg[2] or 0)

                status_rows = s.execute(text('''
                    SELECT cl.status, COUNT(*) as cnt
                    FROM candidate_links cl
                    WHERE cl.source_id = :sid AND cl.discovered_at >= NOW() - INTERVAL '__HOURS__ hours'
                    GROUP BY cl.status
                    ORDER BY cnt DESC
                '''.replace('__HOURS__', hours)), {"sid": sid}).fetchall()
                for st, cnt in status_rows:
                    cand_status[st] = cand_status.get(st, 0) + int(cnt or 0)

                recent = s.execute(text('''
                    SELECT cl.url, cl.status, cl.discovered_at
                    FROM candidate_links cl
                    WHERE cl.source_id = :sid AND cl.discovered_at >= NOW() - INTERVAL '__HOURS__ hours'
                    ORDER BY cl.discovered_at DESC
                    LIMIT 5
                '''.replace('__HOURS__', hours)), {"sid": sid}).fetchall()
                recent_all.extend([
                    {"url": str(r[0]), "status": r[1], "is_wire": (r[1] == 'wire'), "discovered_at": str(r[2])}
                    for r in recent
                ])

                art_stats_rows = s.execute(text('''
                    SELECT a.status, COUNT(*) as cnt
                    FROM articles a
                    JOIN candidate_links cl ON a.candidate_link_id = cl.id
                    WHERE cl.source_id = :sid AND a.extracted_at >= NOW() - INTERVAL '__HOURS__ hours'
                    GROUP BY a.status
                    ORDER BY cnt DESC
                '''.replace('__HOURS__', hours)), {"sid": sid}).fetchall()
                for st, cnt in art_stats_rows:
                    art_status[st] = art_status.get(st, 0) + int(cnt or 0)

                fs_rows = s.execute(text('''
                    WITH time_window AS (
                        SELECT NOW() - INTERVAL '__HOURS__ hours' AS cutoff
                    )
                    SELECT
                        CASE
                            WHEN a.status = 'labeled' AND a.wire_check_status IN ('local', 'complete') THEN 'labeled'
                            WHEN a.wire_check_status = 'wire' THEN 'wire'
                            WHEN a.status = 'opinion' THEN 'opinion'
                            WHEN a.status = 'obituary' THEN 'obituary'
                            WHEN cl.status = 'not_article' THEN 'not_article'
                            WHEN cl.status IN ('extraction_failed', 'verification_failed') THEN 'error'
                            ELSE COALESCE(a.status, cl.status, 'unknown')
                        END as final_status,
                        COUNT(*) as count
                    FROM candidate_links cl
                    LEFT JOIN articles a ON a.candidate_link_id = cl.id
                    CROSS JOIN time_window tw
                    WHERE cl.discovered_at >= tw.cutoff AND cl.source_id = :sid
                    GROUP BY final_status
                '''.replace('__HOURS__', hours)), {"sid": sid}).fetchall()
                for st, cnt in fs_rows:
                    final_status[st] = final_status.get(st, 0) + int(cnt or 0)

            # wire_suppressed derived from final_status 'wire'
            wire_suppressed = final_status.get('wire', 0)

            # Sort recent across sids by discovered_at descending and cap 10
            try:
                recent_all.sort(key=lambda x: x.get('discovered_at', ''), reverse=True)
            except Exception:
                pass
            recent_all = recent_all[:10]

            out.append({
                "host": host,
                "metrics": {
                    "discovered": discovered,
                    "verified_article": verified_article,
                    "extracted": extracted,
                    "wire_suppressed": wire_suppressed,
                },
                "candidate_status": sorted([[k, v] for k, v in cand_status.items()], key=lambda x: x[1], reverse=True),
                "article_status": sorted([[k, v] for k, v in art_status.items()], key=lambda x: x[1], reverse=True),
                "final_status": sorted([[k, v] for k, v in final_status.items()], key=lambda x: x[1], reverse=True),
                "recent_candidate_links": recent_all,
            })
        except Exception as e:
            try:
                s.rollback()
            except Exception:
                pass
            out.append({"host": host, "error": str(e)})
print(json.dumps(out))
"""

    # Aggregate mapping by host locally to pass to metrics script
    try:
        mapping_by_host: dict[str, dict] = {}
        for m in mapping:
            h = m.get('host')
            entry = mapping_by_host.setdefault(h, {'host': h, 'source_ids': [], 'errors': []})
            sid = m.get('source_id')
            if sid:
                entry['source_ids'].append(sid)
            elif m.get('error'):
                entry['errors'].append(m.get('error'))
        items = list(mapping_by_host.values())
    except Exception as e:
        items = [{"host": h, "source_ids": [], "errors": [f"mapping aggregation failed: {e}"]} for h in hosts]

    items_json = json.dumps(items)
    py_metrics = metrics_template.replace('__ITEMS_JSON__', items_json).replace('__HOURS__', hours_str)
    cmd_metrics = [
        "kubectl", "exec", "-n", namespace,
        f"deployment/{deployment}", "--",
        "python", "-c", py_metrics
    ]
    try:
        res = subprocess.check_output(cmd_metrics, text=True)
        return json.loads(res.strip())
    except Exception as e:
        return [{"host": it.get('host'), "error": f"kubectl exec failed fetching metrics: {e}"} for it in mapping]

def http_checks(host, timeout=15):
    if requests is None:
        return {"host": host, "error": "requests not available"}

    endpoints = [
        f"https://{host}/", f"http://{host}/",
        f"https://{host}/robots.txt", f"https://{host}/sitemap.xml",
        f"https://{host}/rss", f"https://{host}/rss.xml", f"https://{host}/feed",
    ]
    results = []
    flags = set()
    for url in endpoints:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (Diagnostics)"}, allow_redirects=True)
            text = r.text.lower()[:2000] if r.text else ""
            waf = [w for w in WAF_HINTS if w in text]
            if waf:
                flags.update(waf)
            robots_block = ("robots.txt" in url and ("disallow: /" in text or "user-agent: *\ndisallow:/" in text))
            results.append({
                "url": url,
                "status": r.status_code,
                "final_url": r.url,
                "robots_block_all": robots_block,
                "waf_hints": waf,
                "has_feed_link": ("application/rss+xml" in text or "<rss" in text or "atom" in text),
            })
        except Exception as e:
            results.append({"url": url, "error": str(e)})
    return {"host": host, "http": results, "waf_flags": sorted(list(flags))}

def infer_causes(telemetry, http):
    m = telemetry.get("metrics", {})
    discovered = m.get("discovered", 0)
    verified = m.get("verified_article", 0)
    extracted = m.get("extracted", 0)
    wire_sup = m.get("wire_suppressed", 0)
    fs_list = telemetry.get("final_status") or []
    fs = {k: v for k, v in fs_list}
    labeled = fs.get("labeled", 0)

    hints = []
    fixes = []

    if discovered == 0:
        hints.append("No discovery in last 7 days")
        fixes.append("Verify RSS/sitemap endpoints; add source-specific feeds; increase days-back in discovery")
    elif discovered > 0 and verified == 0:
        hints.append("Discovery present but verification found no articles")
        fixes.append("Tune StorySniffer and verification patterns; add allowlist for article paths")
    elif verified > 0 and extracted == 0:
        hints.append("Verified articles but extraction failed")
        fixes.append("Run extraction diagnostics from extraction pod; adjust bot protection handling; tune rate limits")

    if wire_sup > 0:
        hints.append("URLs suppressed by wire filters")
        fixes.append("Review wire URL patterns and exclude local-only paths")

    # Final status gating alignment
    if extracted > 0 and labeled == 0:
        hints.append("Extracted articles not reaching labeled/local gating")
        fixes.append("Check ML pipeline and wire detection; ensure labeled are gated by wire_check_status IN ('local','complete')")

    wafs = set(http.get("waf_flags") or [])
    if wafs:
        hints.append("WAF/anti-bot detected: " + ", ".join(sorted(wafs)))
        fixes.append("Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment")

    # Robots or feed availability checks (informational only)
    http_items = http.get("http", [])
    if any(item.get("robots_block_all") for item in http_items):
        hints.append("robots.txt reports block-all (informational)")
        # We do limited captures; do not gate extraction on robots. No fix suggested.
    if not any(item.get("has_feed_link") for item in http_items):
        hints.append("No obvious feed endpoints detected")
        fixes.append("Use sitemap-based discovery or section pages + article detectors (robots-agnostic)")

    return hints, fixes

def generate_report(entries):
    lines = []
    lines.append(f"Site Diagnostics Report - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    for e in entries:
        host = e["host"]
        t = e.get("telemetry", {})
        h = e.get("http", {})
        metrics = t.get("metrics", {})
        hints = e.get("hints", [])
        fixes = e.get("fixes", [])

        lines.append(f"[{host}]")
        lines.append(f"- Discovered: {metrics.get('discovered', 0)} | Verified: {metrics.get('verified_article', 0)} | Extracted: {metrics.get('extracted', 0)} | Wire-suppressed: {metrics.get('wire_suppressed', 0)}")
        if t.get("candidate_status"):
            top = ", ".join([f"{s}:{c}" for s, c in t["candidate_status"][:4]])
            lines.append(f"- Candidate status top: {top}")
        if t.get("article_status"):
            atop = ", ".join([f"{s}:{c}" for s, c in t["article_status"][:4]])
            lines.append(f"- Article status top: {atop}")
        if t.get("final_status"):
            ftop = ", ".join([f"{s}:{c}" for s, c in t["final_status"][:6]])
            lines.append(f"- Final status top: {ftop}")
        diag = e.get("article_diagnostics") or {}
        if diag.get("http"):
            lines.append(f"- Article HTTP: status={diag['http'].get('status')} len={diag['http'].get('content_len')}ms={diag['http'].get('elapsed_ms')}")
            if diag['http'].get('waf_hints'):
                lines.append(f"- Article WAF hints: {', '.join(diag['http']['waf_hints'])}")
        if diag.get("extraction"):
            lines.append(f"- Extraction paragraphs: {diag['extraction'].get('paragraphs')}")
        if h.get("waf_flags"):
            lines.append(f"- WAF hints: {', '.join(h['waf_flags'])}")
        http_items = h.get("http", [])
        sample_codes = [str(x.get("status")) for x in http_items if x.get("status")]
        if sample_codes:
            lines.append(f"- HTTP sample codes: {', '.join(sample_codes)}")
        if t.get("recent_candidate_links"):
            sample_urls = [rc["url"] for rc in t["recent_candidate_links"][:3]]
            if sample_urls:
                lines.append(f"- Recent URLs: {', '.join(sample_urls)}")
        if hints:
            lines.append(f"- Possible causes: {'; '.join(hints)}")
        if fixes:
            lines.append(f"- Suggested fixes: {'; '.join(fixes)}")
        lines.append("")
    return "\n".join(lines)

def main():
    p = argparse.ArgumentParser(description="Diagnostics for discovery and extraction failures")
    p.add_argument("--hosts", nargs="*", default=DEFAULT_HOSTS)
    p.add_argument("--hours", type=int, default=168)
    p.add_argument("--namespace", default="production")
    p.add_argument("--deployment", default="mizzou-api")
    p.add_argument("--skip-http", action="store_true")
    p.add_argument("--out", default="reports")
    args = p.parse_args()

    telemetry = run_prod_db_query(args.hosts, hours=args.hours, namespace=args.namespace, deployment=args.deployment)
    entries = []
    for t in telemetry:
        host = t.get("host")
        http = http_checks(host) if not args.skip_http else {"host": host, "http": [], "waf_flags": []}
        hints, fixes = infer_causes(t, http)
        # Conditional article-specific tests: discoveries but no extractions
        ad = None
        try:
            m = (t.get("metrics") or {})
            if m.get("discovered", 0) > 0 and m.get("extracted", 0) == 0:
                # pick recent sample URL verified as 'article'
                sample_url = None
                for rc in (t.get("recent_candidate_links") or []):
                    if rc.get("status") == "article":
                        sample_url = rc.get("url")
                        break
                if sample_url:
                    pod = find_extraction_pod(args.namespace)
                    ad = run_article_test_in_pod(sample_url, args.namespace, pod) if pod else local_article_test(sample_url)
        except Exception:
            ad = None
        entries.append({
            "host": host,
            "telemetry": t,
            "http": http,
            "hints": hints,
            "fixes": fixes,
            "article_diagnostics": ad or {}
        })

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    md_path = f"{args.out}/site_diagnostics_{ts}.md"
    json_path = f"{args.out}/site_diagnostics_{ts}.json"

    try:
        import os
        os.makedirs(args.out, exist_ok=True)
        with open(md_path, "w") as f:
            f.write(generate_report(entries))
        with open(json_path, "w") as f:
            json.dump(entries, f, indent=2)
        print(f"Wrote report: {md_path}\nWrote data: {json_path}")
    except Exception as e:
        print(f"Error writing report: {e}")

if __name__ == "__main__":
    main()
