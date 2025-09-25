#!/usr/bin/env python3
"""
Corrected Wire Service Integration Demo

Demonstrates how the enhanced byline cleaner integrates with the database
to detect wire services and populate the wire column. Uses correct column names
and handles JSON array format for authors.
"""

import sys
import os
import sqlite3
import json
from typing import List, Any

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner

def parse_author_json(author_data: Any) -> List[str]:
    """Parse author data from database (could be JSON string, list, or None)."""
    if not author_data:
        return []
    
    if isinstance(author_data, str):
        try:
            # Try to parse as JSON
            parsed = json.loads(author_data)
            if isinstance(parsed, list):
                return [str(author) for author in parsed]
            else:
                return [str(parsed)]
        except json.JSONDecodeError:
            # Not JSON, treat as plain string
            return [author_data]
    elif isinstance(author_data, list):
        return [str(author) for author in author_data]
    else:
        return [str(author_data)]

def format_author_json(authors: List[str]) -> str:
    """Format authors as JSON string for database storage."""
    return json.dumps(authors)

def demonstrate_wire_detection():
    """Demonstrate wire service detection with real database integration."""
    
    print("🔍 Wire Service Detection & Database Integration Demo")
    print("=" * 60)
    
    # Initialize cleaner
    cleaner = BylineCleaner(enable_telemetry=False)
    
    # Test cases showing different wire service scenarios
    test_cases = [
        {
            'name': 'Direct Wire Service',
            'byline': 'Associated Press',
            'expected_wire': 'associated press'
        },
        {
            'name': 'Person + Wire Service',
            'byline': 'John Smith CNN',
            'expected_authors': ['John Smith'],
            'expected_wire': 'cnn'
        },
        {
            'name': 'Multi-word Wire Service',
            'byline': 'Fox News',
            'expected_wire': 'fox news'
        },
        {
            'name': 'Person Name Only',
            'byline': 'Sarah Johnson',
            'expected_authors': ['Sarah Johnson'],
            'expected_wire': None
        },
        {
            'name': 'Complex Wire + Person',
            'byline': 'By David Chen, The New York Times',
            'expected_authors': ['David Chen'],
            'expected_wire': 'the new york times'
        }
    ]
    
    print("\n📋 Testing Wire Service Detection:")
    print("-" * 40)
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{i}. {test['name']}")
        print(f"   Input: '{test['byline']}'")
        
        # Clean the byline with JSON output
        result = cleaner.clean_byline(test['byline'], return_json=True)
        
        authors = result.get('authors', [])
        wire_services = result.get('wire_services', [])
        primary_wire = result.get('primary_wire_service')
        
        print(f"   Authors: {authors}")
        print(f"   Wire Services: {wire_services}")
        print(f"   Primary Wire: {primary_wire}")
        
        # Validate expectations
        if 'expected_authors' in test:
            authors_match = authors == test['expected_authors']
            print(f"   ✅ Authors correct: {authors_match}")
        
        if 'expected_wire' in test:
            wire_match = primary_wire == test['expected_wire']
            print(f"   ✅ Wire service correct: {wire_match}")
    
    return True

def demonstrate_database_integration():
    """Show how to integrate wire detection with database updates."""
    
    print("\n\n💾 Database Integration Simulation")
    print("=" * 40)
    
    # Connect to database
    try:
        conn = sqlite3.connect('data/mizzou.db')
        cursor = conn.cursor()
        
        # Get some sample records with authors
        cursor.execute("""
            SELECT id, author, wire 
            FROM articles 
            WHERE author IS NOT NULL 
            AND author != 'null' 
            AND author != '[]'
            LIMIT 10
        """)
        
        records = cursor.fetchall()
        
        if not records:
            print("❌ No records with author data found")
            return False
        
        print(f"📊 Processing {len(records)} sample records...")
        
        cleaner = BylineCleaner(enable_telemetry=False)
        
        wire_detected_count = 0
        processed_records = []
        
        for record in records:
            article_id, author_data, current_wire = record
            
            # Parse current author data
            current_authors = parse_author_json(author_data)
            
            if not current_authors:
                continue
            
            # For demonstration, process each author in the list
            new_authors = []
            detected_wire_services = []
            
            for author in current_authors:
                if not author or author.strip() == '':
                    continue
                
                # Clean the author byline
                result = cleaner.clean_byline(author, return_json=True)
                
                # Extract results
                cleaned_authors = result.get('authors', [])
                wire_services = result.get('wire_services', [])
                
                # Add cleaned authors
                new_authors.extend(cleaned_authors)
                
                # Track wire services
                detected_wire_services.extend(wire_services)
            
            # Determine final wire service value
            final_wire = None
            if detected_wire_services:
                # Use the first/primary wire service detected
                final_wire = detected_wire_services[0]
                wire_detected_count += 1
            
            # Store the processing results
            processed_records.append({
                'id': article_id,
                'original_authors': current_authors,
                'new_authors': new_authors,
                'detected_wire_services': detected_wire_services,
                'final_wire': final_wire,
                'current_wire': current_wire
            })
        
        # Display results
        print("\n📈 Processing Results:")
        print(f"   Records processed: {len(processed_records)}")
        print(f"   Wire services detected: {wire_detected_count}")
        
        # Show detailed results for interesting cases
        print("\n🔍 Detailed Results:")
        print("-" * 60)
        
        for i, record in enumerate(processed_records[:5], 1):
            print(f"\n{i}. Article ID: {record['id'][:8]}...")
            print(f"   Original Authors: {record['original_authors']}")
            print(f"   Cleaned Authors: {record['new_authors']}")
            if record['detected_wire_services']:
                print(f"   🎯 Wire Services: {record['detected_wire_services']}")
                print(f"   📝 Final Wire: {record['final_wire']}")
            else:
                print("   ✅ No wire services detected")
        
        # Demonstrate the SQL update pattern (simulation only)
        print("\n💾 SQL Update Pattern (simulation):")
        print("-" * 40)
        
        update_examples = []
        for record in processed_records:
            if record['detected_wire_services'] or record['new_authors'] != record['original_authors']:
                update_examples.append(record)
        
        if update_examples:
            print("Example updates that would be performed:")
            for record in update_examples[:3]:
                print("\nUPDATE articles SET")
                if record['new_authors']:
                    authors_json = format_author_json(record['new_authors'])
                    print(f"  author = '{authors_json}',")
                if record['final_wire']:
                    print(f"  wire = '{record['final_wire']}'")
                print(f"WHERE id = '{record['id']}';")
        else:
            print("✅ No updates needed for current sample")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False

def demonstrate_convenience_methods():
    """Show the convenience methods for wire service access."""
    
    print("\n\n🛠️ Convenience Methods Demo")
    print("=" * 30)
    
    cleaner = BylineCleaner(enable_telemetry=False)
    
    test_bylines = [
        "John Doe Associated Press",
        "Reuters",
        "Sarah Smith CNN NewsSource",
        "Regular Author Name"
    ]
    
    for byline in test_bylines:
        print(f"\nProcessing: '{byline}'")
        
        # Clean with JSON to get full details
        result = cleaner.clean_byline(byline, return_json=True)
        
        # Also demonstrate convenience methods
        authors = cleaner.clean_byline(byline, return_json=False)
        wire_services = cleaner.get_detected_wire_services()
        primary_wire = cleaner.get_primary_wire_service()
        
        print(f"  Authors (list): {authors}")
        print(f"  JSON result: {result}")
        print(f"  Wire services: {wire_services}")
        print(f"  Primary wire: {primary_wire}")

def main():
    """Run all demonstrations."""
    
    print("🚀 Enhanced Byline Cleaner - Wire Service Integration")
    print("=" * 80)
    
    try:
        # Test 1: Wire service detection
        success1 = demonstrate_wire_detection()
        
        # Test 2: Database integration
        success2 = demonstrate_database_integration()
        
        # Test 3: Convenience methods
        demonstrate_convenience_methods()
        
        print("\n" + "=" * 80)
        if success1 and success2:
            print("🎉 All demonstrations completed successfully!")
            print("\n💡 Key Integration Points:")
            print("   • Wire services detected and tracked throughout cleaning")
            print("   • JSON API provides wire_services array and primary_wire_service")
            print("   • Convenience methods available for direct access")
            print("   • Database integration ready with correct column names")
            print("   • Authors cleaned while preserving wire service information")
        else:
            print("⚠️  Some demonstrations had issues - check output above")
        
    except Exception as e:
        print(f"❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()