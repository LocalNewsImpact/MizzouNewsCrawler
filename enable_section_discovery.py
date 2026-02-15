#!/usr/bin/env python3
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()

print("="*80)
print("ENABLING SECTION DISCOVERY FOR ALL ACTIVE SOURCES")
print("="*80)

with db.get_session() as session:
    # Enable section discovery for all active sources
    result = session.execute(text("""
        UPDATE sources
        SET section_discovery_enabled = true
        WHERE status IN ('active', NULL)
        AND (section_discovery_enabled IS NULL OR section_discovery_enabled = false)
    """))
    
    updated_count = result.rowcount
    session.commit()
    
    print(f"\n✅ Enabled section discovery for {updated_count} sources")
    
    # Show summary
    summary = session.execute(text("""
        SELECT 
            status,
            COUNT(*) as total,
            SUM(CASE WHEN section_discovery_enabled = true THEN 1 ELSE 0 END) as enabled
        FROM sources
        GROUP BY status
        ORDER BY total DESC
    """)).fetchall()
    
    print("\n" + "="*80)
    print("SUMMARY BY STATUS")
    print("="*80)
    print(f"{'Status':<20} {'Total':<10} {'Section Discovery Enabled':<30}")
    print("-"*80)
    
    for row in summary:
        status = row[0] or 'active (NULL)'
        total = row[1]
        enabled = row[2]
        print(f"{status:<20} {total:<10} {enabled:<30}")
    
    print("\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)
    print("✓ Section discovery now enabled for all active sources")
    print("✓ Next discovery run will:")
    print("  1. Discover section URLs from homepage navigation")
    print("  2. Store them in sources.discovered_sections")
    print("  3. Use section URLs for supplemental discovery")
    print("  4. Bypass RSS feeds polluted with wire content")

print("\n✅ Done")
