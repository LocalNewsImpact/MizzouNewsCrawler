#!/usr/bin/env python3
"""
Demo script showing how to integrate wire service detection with article processing.

This script demonstrates how to:
1. Clean bylines and extract authors
2. Detect and capture wire services
3. Update the articles table with Wire column data
4. Query and filter articles by wire service status
"""

import sqlite3
import sys
from pathlib import Path

# Add src directory to path
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

from utils.byline_cleaner import BylineCleaner  # noqa: E402


def demo_wire_service_integration():
    """Demonstrate wire service detection and database integration."""
    
    print("🚀 Wire Service Detection Integration Demo")
    print("=" * 50)
    
    # Initialize byline cleaner
    cleaner = BylineCleaner(enable_telemetry=False)
    
    # Connect to database
    db_path = Path('data/mizzou.db')
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    print("📊 Current Wire Service Status:")
    print("-" * 30)
    
    # Check current wire service distribution
    cursor.execute("""
        SELECT 
            CASE 
                WHEN wire IS NULL THEN 'Local/Staff Content'
                ELSE 'Wire Service Content'
            END as content_type,
            COUNT(*) as count
        FROM articles 
        GROUP BY 
            CASE 
                WHEN wire IS NULL THEN 'Local/Staff Content'
                ELSE 'Wire Service Content'
            END
    """)
    
    for content_type, count in cursor.fetchall():
        print(f"  {content_type}: {count:,} articles")
    
    print("\n🧪 Processing Sample Bylines:")
    print("-" * 35)
    
    # Sample bylines to test
    sample_bylines = [
        "John Smith Staff Reporter",
        "Associated Press", 
        "Sarah Johnson Reuters",
        "Mike Davis The New York Times",
        "CNN",
        "Mary Williams Sports Editor",
        "Bob Wilson Fox News",
        "Alice Brown Wall Street Journal"
    ]
    
    for i, byline in enumerate(sample_bylines, 1):
        print(f"\n{i}. Processing: '{byline}'")
        
        # Clean byline and get results
        result = cleaner.clean_byline(byline, return_json=True)
        
        authors = result['authors']
        wire_services = result['wire_services']
        primary_wire = result['primary_wire_service']
        
        print(f"   Authors: {authors}")
        print(f"   Wire Services: {wire_services}")
        
        # Simulate database update
        if primary_wire:
            print(f"   📊 Would set wire = '{primary_wire}'")
            print("   🏷️  Classification: WIRE CONTENT")
        else:
            print("   📊 Would set wire = NULL")
            print("   🏷️  Classification: LOCAL/STAFF CONTENT")
    
    print("\n🔍 Sample Wire Service Queries:")
    print("-" * 32)
    
    # Show some example queries
    print("\n1. Find all wire service articles:")
    print("   SELECT * FROM articles WHERE wire IS NOT NULL;")
    
    print("\n2. Find all CNN articles:")
    print("   SELECT * FROM articles WHERE wire = 'cnn';")
    
    print("\n3. Find all local content:")
    print("   SELECT * FROM articles WHERE wire IS NULL;")
    
    print("\n4. Count articles by wire service:")
    print("   SELECT wire, COUNT(*) FROM articles")
    print("   WHERE wire IS NOT NULL GROUP BY wire;")
    
    print("\n5. Get wire service distribution:")
    print("   SELECT")
    print("     CASE WHEN wire IS NULL THEN 'Local' ELSE wire END,")
    print("     COUNT(*)")
    print("   FROM articles GROUP BY wire;")
    
    # Show actual wire service breakdown from current data
    print("\n📈 Current Article Distribution:")
    print("-" * 29)
    
    cursor.execute("""
        SELECT 
            COALESCE(wire, 'Local/Staff') as source_type,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM articles), 1) as percentage
        FROM articles 
        GROUP BY wire
        ORDER BY count DESC
        LIMIT 10
    """)
    
    for source_type, count, percentage in cursor.fetchall():
        print(f"  {source_type}: {count:,} articles ({percentage}%)")
    
    conn.close()
    
    print("\n✅ Integration Demo Complete!")
    print("\n📋 Next Steps for Implementation:")
    print("   1. Update article processing pipeline to use wire detection")
    print("   2. Backfill existing articles with wire service data")
    print("   3. Add wire service filtering to content management")
    print("   4. Create reports and analytics for wire vs local content")
    print("   5. Implement automated wire service classification")


def demo_backfill_process():
    """Show how to backfill existing articles with wire service data."""
    
    print("\n\n🔄 Wire Service Backfill Demo")
    print("=" * 32)
    
    # Connect to database
    db_path = Path('data/mizzou.db')
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Get sample of articles that might have wire services
    cursor.execute("""
        SELECT id, byline, clean_byline 
        FROM articles 
        WHERE byline IS NOT NULL 
        AND wire IS NULL
        AND (
            LOWER(byline) LIKE '%associated press%' OR
            LOWER(byline) LIKE '%reuters%' OR  
            LOWER(byline) LIKE '%cnn%' OR
            LOWER(byline) LIKE '%fox news%' OR
            LOWER(byline) LIKE '%new york times%' OR
            LOWER(byline) LIKE '%washington post%'
        )
        LIMIT 5
    """)
    
    sample_articles = cursor.fetchall()
    
    if sample_articles:
        print(f"📝 Found {len(sample_articles)} articles with potential wire services:")
        print("-" * 55)
        
        cleaner = BylineCleaner(enable_telemetry=False)
        
        for article_id, byline, clean_byline in sample_articles:
            print(f"\nArticle ID: {article_id}")
            print(f"Original Byline: '{byline}'")
            print(f"Current Clean Byline: '{clean_byline}'")
            
            # Process with wire detection
            result = cleaner.clean_byline(byline, return_json=True)
            primary_wire = result['primary_wire_service']
            
            if primary_wire:
                print(f"🎯 Detected Wire Service: {primary_wire}")
                print(f"SQL: UPDATE articles SET wire = '{primary_wire}' WHERE id = '{article_id}';")
            else:
                print("🎯 No wire service detected")
    else:
        print("📝 No articles found with obvious wire service patterns")
    
    # Show proposed backfill query
    print("\n📋 Proposed Backfill Process:")
    print("-" * 28)
    print("1. SELECT articles WHERE wire IS NULL AND byline IS NOT NULL")
    print("2. FOR EACH article:")
    print("   - Clean byline with wire detection")
    print("   - UPDATE wire column if wire service detected")
    print("3. Log progress and results")
    print("4. Verify and validate results")
    
    conn.close()


if __name__ == "__main__":
    try:
        demo_wire_service_integration()
        demo_backfill_process()
        
        print("\n🎉 All demos completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)