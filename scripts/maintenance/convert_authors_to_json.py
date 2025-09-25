#!/usr/bin/env python3
"""
Convert normal author format to JSON-like format for consistency.
This script converts entries like "John Doe" to ["John Doe"] format.
"""

import sqlite3
import json
import os
from typing import List


def parse_normal_author(author_str: str) -> List[str]:
    """
    Parse a normal author string into a list of authors.
    Handles comma-separated authors and single authors.
    """
    if not author_str or not author_str.strip():
        return []
    
    # Handle comma-separated authors
    if ',' in author_str:
        # Split by comma and clean each author
        authors = [author.strip() for author in author_str.split(',')]
        authors = [author for author in authors if author]  # Remove empty
        return authors
    else:
        # Single author
        return [author_str.strip()]


def convert_to_json_format(authors: List[str]) -> str:
    """Convert list of authors to JSON string format."""
    if not authors:
        return "[]"
    return json.dumps(authors)


def convert_normal_to_json_format():
    """Convert normal author entries to JSON format."""
    
    print("🔄 Converting Normal Author Format to JSON Format")
    print("=" * 50)
    
    # Database path
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'mizzou.db')
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # First, get all normal format entries
    cursor.execute('''
        SELECT id, author 
        FROM articles 
        WHERE author IS NOT NULL 
        AND author != '' 
        AND author NOT LIKE '[%'
    ''')
    
    normal_entries = cursor.fetchall()
    
    print(f"📊 Found {len(normal_entries)} normal format entries to convert")
    
    if not normal_entries:
        print("✅ No normal format entries to convert")
        conn.close()
        return
    
    # Show some examples before conversion
    print("\n📋 Examples of entries to convert:")
    for i, (article_id, author) in enumerate(normal_entries[:5], 1):
        authors_list = parse_normal_author(author)
        json_format = convert_to_json_format(authors_list)
        print(f"   {i}. \"{author}\" → {json_format}")
    
    if len(normal_entries) > 5:
        print(f"   ... and {len(normal_entries) - 5} more entries")
    
    # Ask for confirmation
    response = input(f"\n❓ Convert {len(normal_entries)} entries? (y/N): ")
    if response.lower() != 'y':
        print("❌ Conversion cancelled")
        conn.close()
        return
    
    print("\n🔄 Converting entries...")
    
    converted_count = 0
    error_count = 0
    
    for article_id, author in normal_entries:
        try:
            # Parse the normal author string
            authors_list = parse_normal_author(author)
            
            # Convert to JSON format
            json_author = convert_to_json_format(authors_list)
            
            # Update the database
            cursor.execute('''
                UPDATE articles 
                SET author = ? 
                WHERE id = ?
            ''', (json_author, article_id))
            
            converted_count += 1
            
            if converted_count % 100 == 0:
                print(f"   ... converted {converted_count}/{len(normal_entries)}")
                
        except Exception as e:
            print(f"⚠️  Error converting article {article_id}: {e}")
            error_count += 1
    
    # Commit the changes
    conn.commit()
    
    print("\n✅ Conversion complete!")
    print(f"   Successfully converted: {converted_count}")
    print(f"   Errors: {error_count}")
    
    # Verify the conversion
    cursor.execute('''
        SELECT COUNT(*) 
        FROM articles 
        WHERE author IS NOT NULL 
        AND author != '' 
        AND author NOT LIKE '[%'
    ''')
    remaining_normal = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT COUNT(*) 
        FROM articles 
        WHERE author LIKE '[%'
    ''')
    total_json = cursor.fetchone()[0]
    
    print("\n📊 Post-conversion statistics:")
    print(f"   JSON format entries: {total_json:,}")
    print(f"   Normal format entries remaining: {remaining_normal:,}")
    
    # Show some examples after conversion
    if total_json > 0:
        cursor.execute('''
            SELECT author 
            FROM articles 
            WHERE author LIKE '[%' 
            LIMIT 5
        ''')
        json_examples = [row[0] for row in cursor.fetchall()]
        
        print("\n📋 Examples after conversion:")
        for i, example in enumerate(json_examples, 1):
            print(f"   {i}. {example}")
    
    conn.close()
    
    if remaining_normal == 0:
        print("\n🎉 All author entries are now in JSON format!")
    else:
        print(f"\n⚠️  {remaining_normal} entries still in normal format")


if __name__ == '__main__':
    convert_normal_to_json_format()