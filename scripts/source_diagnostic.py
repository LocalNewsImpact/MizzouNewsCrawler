#!/usr/bin/env python3
"""
Source Health Diagnostic Tool
Comprehensive health check for any news source in the pipeline
"""

from src.models.database import DatabaseManager
from sqlalchemy import text
from datetime import datetime, timedelta
import json
import sys

def diagnose_source(hostname):
    """Run comprehensive diagnostics on a source"""
    
    db = DatabaseManager()
    sess = db.get_session().__enter__()
    
    # Normalize hostname (remove http/https, www, trailing slash)
    hostname = hostname.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
    
    # Find source by matching the URL extraction logic used in BigQuery report
    # The report extracts hostname from URLs: REGEXP_EXTRACT(url, r'https?://([^/]+)')
    # So we need to match this carefully
    result = sess.execute(text(f"""
        SELECT id, host, canonical_name, extraction_method, bot_protection_type, status
        FROM sources 
        WHERE host = '{hostname}' OR host = 'www.{hostname}' OR canonical_name ILIKE '%{hostname}%'
        LIMIT 1
    """)).fetchone()
    
    if not result:
        print(f"❌ Source not found for: {hostname}")
        return False
    
    source_id, host, canonical_name, extraction_method, bot_protection, source_status = result
    
    print("\n" + "="*80)
    print(f"SOURCE DIAGNOSTIC REPORT: {canonical_name}")
    print("="*80)
    
    # ===== CONFIGURATION =====
    print("\n[CONFIGURATION]")
    print(f"  Hostname:           {host}")
    print(f"  Canonical Name:     {canonical_name}")
    print(f"  Source ID:          {source_id}")
    print(f"  Extraction Method:  {extraction_method}")
    print(f"  Bot Protection:     {bot_protection if bot_protection else '(none)'}")
    print(f"  Source Status:      {source_status if source_status else '(inactive)'}")
    
    # ===== DISCOVERY CONFIGURATION =====
    src_config = sess.execute(text(f"""
        SELECT discovered_sections, section_discovery_enabled, rss_feeds
        FROM sources 
        WHERE id = '{source_id}'
    """)).fetchone()
    
    print("\n[DISCOVERY CONFIGURATION]")
    if src_config[0]:
        print(f"  Discovery Enabled:  {src_config[1]}")
        print(f"  Configured Sections ({len(src_config[0]['urls'])}):")
        for url in src_config[0]['urls']:
            print(f"    - {url}")
    else:
        print(f"  Discovery Enabled:  {src_config[1]}")
        print(f"  Configured Sections: (none)")
    
    if src_config[2]:
        print(f"  RSS Feeds:")
        for feed in src_config[2]:
            print(f"    - {feed}")
    
    # ===== PIPELINE METRICS =====
    # Match EXACT logic from BigQuery weekly health report:
    # - Discovery: 14d and 7d counts from candidate_links table
    # - Extraction: 14d and 7d counts from articles table (not candidate_links)
    
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)
    
    # Discovery: Count URLs discovered in past 14/7 days from candidate_links
    discovery_stats = sess.execute(text(f"""
        SELECT 
            COUNT(*) as total_discovered_14d,
            SUM(CASE WHEN discovered_at >= '{week_ago}' THEN 1 ELSE 0 END) as discovered_7d,
            MAX(discovered_at) as last_discovered
        FROM candidate_links
        WHERE source_id = '{source_id}'
          AND discovered_at >= '{fourteen_days_ago}'
    """)).fetchone()
    
    total_disc_14d, disc_7d, last_disc = discovery_stats
    
    # Extraction: Count ARTICLES extracted in past 14/7 days from articles table
    # This matches the BigQuery report logic exactly
    extraction_stats = sess.execute(text(f"""
        SELECT 
            COUNT(*) as total_extracted_14d,
            SUM(CASE WHEN extracted_at >= '{week_ago}' THEN 1 ELSE 0 END) as extracted_7d,
            MAX(extracted_at) as last_extracted
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE cl.source_id = '{source_id}'
          AND a.extracted_at >= '{fourteen_days_ago}'
    """)).fetchone()
    
    total_ext_14d, ext_7d, last_ext = extraction_stats
    
    print("\n[DISCOVERY METRICS]")
    print(f"  Total discovered (14 days):   {total_disc_14d if total_disc_14d else 0}")
    print(f"  Discovered (7 days):          {disc_7d if disc_7d else 0}")
    print(f"  Last discovered:              {last_disc if last_disc else '(never)'}")
    
    print("\n[EXTRACTION METRICS]")
    print(f"  Total extracted (14 days):    {total_ext_14d if total_ext_14d else 0}")
    print(f"  Extracted (7 days):           {ext_7d if ext_7d else 0}")
    print(f"  Last extracted:               {last_ext if last_ext else '(never)'}")
    
    # Candidate links status breakdown
    cl_statuses = sess.execute(text(f"""
        SELECT status, COUNT(*) as cnt
        FROM candidate_links
        WHERE source_id = '{source_id}'
        GROUP BY status
        ORDER BY cnt DESC
    """)).fetchall()
    
    print("\n[CANDIDATE LINKS STATUS]")
    for status, count in cl_statuses:
        print(f"  {status:20} {count}")
    
    # Article statuses
    article_statuses = sess.execute(text(f"""
        SELECT a.status, COUNT(*) as cnt
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE cl.source_id = '{source_id}'
        GROUP BY a.status
        ORDER BY cnt DESC
    """)).fetchall()
    
    print("\n[ARTICLE STATUS]")
    for status, count in article_statuses:
        print(f"  {status:20} {count}")
    
    # Filtered content (last 14 days to match report period)
    fourteen_days_ago = now - timedelta(days=14)
    filtered_14d = sess.execute(text(f"""
        SELECT status, COUNT(*) as cnt
        FROM candidate_links
        WHERE source_id = '{source_id}'
          AND discovered_at >= '{fourteen_days_ago}'
          AND status IN ('wire', 'obituary', 'opinion', 'weather', 'not_article', 'paused')
        GROUP BY status
        ORDER BY cnt DESC
    """)).fetchall()
    
    print("\n[FILTERED CONTENT (14 days)]")
    if filtered_14d:
        for status, count in filtered_14d:
            print(f"  {status:20} {count}")
    else:
        print(f"  (none filtered)")
    
    # Extraction success rate for 14 days
    if (total_disc_14d or 0) > 0:
        success_rate = ((total_ext_14d or 0) / (total_disc_14d or 1)) * 100
        print("\n[EXTRACTION SUCCESS RATE (14 days)]")
        print(f"  Discovered: {total_disc_14d or 0}, Extracted: {total_ext_14d or 0}, Success Rate: {success_rate:.1f}%")
    else:
        print("\n[EXTRACTION SUCCESS RATE (14 days)]")
        print(f"  No discovery in past 14 days")
    
    # Health assessment - using BigQuery report logic
    print("\n[HEALTH ASSESSMENT]")
    issues = []
    
    if not source_status:
        issues.append("⚠️  Source status is inactive")
    
    if (total_ext_14d or 0) == 0 and (total_disc_14d or 0) == 0:
        issues.append("⚠️  NO ACTIVITY - No discoveries or extractions in 14 days")
    elif (ext_7d or 0) == 0 and (total_disc_14d or 0) > 0:
        issues.append("⚠️  EXTRACTION ISSUE - URLs found but no extractions in past 7 days")
    elif (disc_7d or 0) == 0 and (total_disc_14d or 0) > 0:
        issues.append("⚠️  DISCOVERY ISSUE - No new discoveries in past 7 days")
    
    if issues:
        for issue in issues:
            print(f"  {issue}")
    else:
        print(f"  ✅ Source appears healthy")
    
    # Recent samples
    print("\n[RECENT ARTICLES]")
    recent = sess.execute(text(f"""
        SELECT a.url, a.status, a.extracted_at
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE cl.source_id = '{source_id}'
        ORDER BY a.extracted_at DESC
        LIMIT 5
    """)).fetchall()
    
    if recent:
        for url, status, extracted_at in recent:
            url_part = url.split('/')[-1][:50]
            print(f"  [{status:10}] {url_part}")
            print(f"              {extracted_at}")
    else:
        print(f"  (no articles)")
    
    print("\n" + "="*80 + "\n")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: source_diagnostic.py <hostname_or_url>")
        print("Example: source_diagnostic.py greenfieldvedette.com")
        print("Example: source_diagnostic.py https://www.greenfieldvedette.com/")
        sys.exit(1)
    
    hostname = sys.argv[1]
    success = diagnose_source(hostname)
    sys.exit(0 if success else 1)
