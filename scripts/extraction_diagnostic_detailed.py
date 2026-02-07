#!/usr/bin/env python3
"""
Live extraction issue diagnostic - queries actual database for real-time stats.
Provides discovery sections, filtering stats, and extraction counts per source.
"""
import sys
sys.path.insert(0, '/app')

from src.models.database import DatabaseManager
from sqlalchemy import text
from datetime import datetime

WINDOW_DAYS = 30
EXCLUDED_ARTICLE_STATUSES = ("wire", "opinion", "obituary")

print(f"\n{'='*140}")
print(f"LIVE EXTRACTION DIAGNOSTIC REPORT")
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Window: last {WINDOW_DAYS} days | Excluding article statuses: {', '.join(EXCLUDED_ARTICLE_STATUSES)}")
print(f"{'='*140}\n")

db = DatabaseManager()

with db.get_session() as session:
    print("Running aggregate query…")
    # Get all sources with discovery + extraction stats in ONE query
    results = session.execute(text(f"""
        SELECT 
            cl.source,
            COUNT(DISTINCT cl.id) FILTER (WHERE cl.discovered_at >= NOW() - INTERVAL '{WINDOW_DAYS} days') as disc_window,
            COUNT(DISTINCT cl.id) FILTER (WHERE cl.discovered_at >= NOW() - INTERVAL '7 days') as disc_7d,
            COUNT(DISTINCT a.id) FILTER (WHERE a.extracted_at >= NOW() - INTERVAL '{WINDOW_DAYS} days') as ext_total_window,
            COUNT(DISTINCT a.id) FILTER (
                WHERE a.extracted_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
                AND a.status IN ('wire','opinion','obituary')
            ) as ext_filtered_window,
            COUNT(DISTINCT a.id) FILTER (
                WHERE a.extracted_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
                AND a.status NOT IN ('wire','opinion','obituary')
            ) as ext_valid_window,
            COUNT(DISTINCT a.id) FILTER (WHERE a.extracted_at >= NOW() - INTERVAL '7 days') as ext_7d
        FROM candidate_links cl
        LEFT JOIN articles a ON cl.id = a.candidate_link_id
        WHERE cl.discovered_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
        GROUP BY cl.source
        ORDER BY cl.source
    """)).fetchall()
    
    sources_data = []
    for source, disc_window, disc_7d, ext_total_window, ext_filtered_window, ext_valid_window, ext_7d in results:
        disc_window = disc_window or 0
        disc_7d = disc_7d or 0
        ext_total_window = ext_total_window or 0
        ext_filtered_window = ext_filtered_window or 0
        ext_valid_window = ext_valid_window or 0
        ext_7d = ext_7d or 0
        success_rate = (
            (ext_valid_window / disc_window * 100) if disc_window > 0 else 0
        )
        
        sources_data.append({
            'source': source,
            'disc_window': disc_window,
            'disc_7d': disc_7d,
            'ext_total_window': ext_total_window,
            'ext_filtered_window': ext_filtered_window,
            'ext_valid_window': ext_valid_window,
            'ext_7d': ext_7d,
            'success_rate': success_rate
        })
    
    # Sort by success rate (lowest first)
    sources_data.sort(key=lambda x: x['success_rate'])
    
    for data in sources_data:
        source = data['source']
        disc_window = data['disc_window']
        disc_7d = data['disc_7d']
        ext_total_window = data['ext_total_window']
        ext_filtered_window = data['ext_filtered_window']
        ext_valid_window = data['ext_valid_window']
        ext_7d = data['ext_7d']
        success_rate = data['success_rate']
        
        # Skip sources with no discovery
        if disc_window == 0:
            continue
        
        print(f"\n{'─'*140}")
        print(f"📰 {source.upper()}")
        print(
            f"   Discovered ({WINDOW_DAYS}d/7d): {disc_window}/{disc_7d} | "
            f"Extracted valid ({WINDOW_DAYS}d): {ext_valid_window} | "
            f"Filtered ({WINDOW_DAYS}d): {ext_filtered_window} | "
            f"Total extracted ({WINDOW_DAYS}d/7d): {ext_total_window}/{ext_7d} | "
            f"Valid success rate: {success_rate:.1f}%"
        )
        print(f"{'─'*140}")
        
        try:
            # Get discovery sections and extraction method
            source_result = session.execute(text("""
                SELECT discovered_sections, extraction_method
                FROM sources
                WHERE host = :hostname OR canonical_name = :hostname
                LIMIT 1
            """), {'hostname': source}).fetchone()
            
            if source_result:
                import json
                sections_raw = source_result[0]
                extraction_method = source_result[1] or 'not configured'
                
                # Parse sections if JSON string
                if isinstance(sections_raw, str):
                    try:
                        sections = json.loads(sections_raw)
                    except:
                        sections = []
                else:
                    sections = sections_raw if isinstance(sections_raw, list) else []
                
                print(f"\n   📍 EXTRACTION METHOD: {extraction_method}")
                if sections:
                    print(f"   📍 DISCOVERY SECTIONS ({len(sections)}):")
                    for i, section in enumerate(sections[:8], 1):
                        print(f"      {i}. {section}")
                    if len(sections) > 8:
                        print(f"      ... and {len(sections) - 8} more")
                else:
                    print(f"   📍 DISCOVERY SECTIONS: none configured")
            else:
                print(f"\n   📍 EXTRACTION METHOD: not in sources table")
                print(f"   📍 DISCOVERY SECTIONS: not in sources table")
            
            # Get filtering stats
            filtering_stats = session.execute(text(f"""
                SELECT status, COUNT(*) as cnt
                FROM candidate_links
                WHERE source = :source
                AND status IN ('opinion', 'obituary', 'not_article', 'wire')
                AND discovered_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
                GROUP BY status
                ORDER BY cnt DESC
            """), {'source': source}).fetchall()
            
            print(f"\n   ❌ FILTERED OUT (Opinion/Obituary/Not-Article/Wire - {WINDOW_DAYS}d):")
            if filtering_stats:
                for status, count in filtering_stats:
                    print(f"      {status.upper():20s}: {count:5d}")
            else:
                print(f"      (none filtered)")
            
            # Check extracted articles
            print(f"\n   ✅ EXTRACTED ARTICLES (valid, {WINDOW_DAYS}d): {ext_valid_window}")
            
            # Analysis
            print(f"\n   🔎 ANALYSIS:")
            if disc_window == 0:
                print(f"      ⚠️  No discovery in {WINDOW_DAYS} days - source may be inactive or sections misconfigured")
            elif ext_valid_window == 0 and disc_window > 0:
                print(f"      🚨 {disc_window} URLs discovered but ZERO valid extractions")
                print(f"         → Extraction is completely failing (bot protection, SSL issues, site format)")
            elif success_rate < 5:
                print(f"      🚨 CRITICAL: {success_rate:.1f}% extraction success (<5%)")
                print(f"         → Severe extraction issues on this source")
            elif success_rate < 15:
                print(f"      🟡 LOW: {success_rate:.1f}% extraction success (<15%)")
                print(f"         → Most discovered URLs not being extracted")
        
        except Exception as e:
            print(f"   ❌ Error: {str(e)[:100]}")

print(f"\n{'='*140}\n")
