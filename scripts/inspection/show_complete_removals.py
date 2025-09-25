#!/usr/bin/env python3
"""
Show complete text removal analysis for each domain with boilerplate content.
Saves detailed removal information to a file for review.
"""

import sqlite3
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner
from datetime import datetime
import os


def analyze_domain_removals():
    """Analyze and show complete text removals for each domain."""
    db_path = "data/mizzou.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cleaner = BalancedBoundaryContentCleaner()
    
    # Get domains with sufficient articles (extract domain from URL)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            CASE 
                WHEN url LIKE 'https://%' THEN SUBSTR(url, 9, INSTR(SUBSTR(url, 9), '/') - 1)
                WHEN url LIKE 'http://%' THEN SUBSTR(url, 8, INSTR(SUBSTR(url, 8), '/') - 1)
                ELSE url
            END as domain,
            COUNT(*) as article_count
        FROM articles
        WHERE content IS NOT NULL AND LENGTH(content) > 100
        GROUP BY domain
        HAVING article_count >= 3
        ORDER BY article_count DESC
        LIMIT 20
    """)
    
    domains = cursor.fetchall()
    print(f"📊 Found {len(domains)} domains with 3+ articles")
    
    # Prepare output file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"complete_text_removals_{timestamp}.txt"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("COMPLETE TEXT REMOVAL ANALYSIS\n")
        f.write("=" * 50 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                f"\n\n")
        
        domains_with_removals = 0
        total_removals = 0
        
        for i, (domain, count) in enumerate(domains, 1):
            print(f"🔍 {i:2d}. Analyzing {domain} ({count} articles)...")
            
            # Get articles for this domain
            cursor.execute("""
                SELECT id, url, content
                FROM articles
                WHERE (
                    (url LIKE 'https://%' AND SUBSTR(url, 9, INSTR(SUBSTR(url, 9), '/') - 1) = ?)
                    OR (url LIKE 'http://%' AND SUBSTR(url, 8, INSTR(SUBSTR(url, 8), '/') - 1) = ?)
                    OR url = ?
                ) AND content IS NOT NULL
                AND LENGTH(content) > 100
            """, (domain, domain, domain))
            
            articles = cursor.fetchall()
            if len(articles) < 3:
                continue
                
            # Analyze content
            results = cleaner.analyze_domain(domain)
            
            # Filter for segments that would be removed (boundary_score >= 0.5)
            removable_segments = [
                segment for segment in results['segments']
                if segment.get('boundary_score', 0) >= 0.5
            ]
            
            if not removable_segments:
                f.write(f"{i:2d}. {domain} ({count} articles)\n")
                f.write("    ❌ No boilerplate segments detected\n\n")
                continue
            
            domains_with_removals += 1
            total_removals += len(removable_segments)
            
            stats = results.get('stats', {})
            f.write(f"{i:2d}. {domain} ({count} articles)\n")
            f.write(f"    ✅ {len(removable_segments)} segments for removal\n")
            removal_pct = stats.get('removal_percentage', 0)
            removable_chars = stats.get('total_removable_chars', 0)
            f.write(f"    📈 Estimated removal: {removal_pct:.1f}% of content\n")
            f.write(f"    📝 {removable_chars} characters removable\n\n")
            
            # Show each removable segment
            for j, segment in enumerate(removable_segments, 1):
                conf_score = segment.get('boundary_score', 0)
                f.write(f"    SEGMENT {j} (Confidence: {conf_score:.2f})\n")
                pattern_type = segment.get('pattern_type', 'unknown')
                f.write(f"    Pattern: {pattern_type.upper()}\n")
                occurrences = segment.get('occurrences', 0)
                f.write(f"    Occurrences: {occurrences} times\n")
                text = segment.get('text', '')
                f.write(f"    Length: {len(text)} characters\n")
                boundary_score = segment.get('boundary_score', 0)
                f.write(f"    Boundary Score: {boundary_score:.2f}\n")
                f.write("    " + "-" * 50 + "\n")
                
                # Show the complete text that would be removed
                if len(text) > 500:  # Truncate long segments
                    f.write(f"    TEXT (first/last 250 chars of {len(text)}):\n")
                    f.write(f"    \"{text[:250]}...\n")
                    f.write(f"    ...{text[-250:]}\"\n\n")
                else:
                    f.write("    COMPLETE TEXT:\n")
                    f.write(f"    \"{text}\"\n\n")
                
                # Show URLs where this text appears
                f.write("    APPEARS IN ARTICLES:\n")
                for article_id, url, content in articles:
                    if text in content:
                        f.write(f"    • {url}\n")
                f.write("\n")
            
            f.write("=" * 70 + "\n\n")
        
        # Summary
        f.write("SUMMARY\n")
        f.write("=" * 50 + "\n")
        f.write(f"Total domains analyzed: {len(domains)}\n")
        f.write(f"Domains with removable content: {domains_with_removals}\n")
        f.write(f"Total removable segments: {total_removals}\n")
        f.write(f"Analysis completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    conn.close()
    
    print("✅ Analysis complete!")
    print(f"📄 Detailed report saved to: {output_file}")
    print(f"🎯 {domains_with_removals} domains have removable content")
    print(f"📊 {total_removals} total segments identified for removal")

if __name__ == "__main__":
    analyze_domain_removals()