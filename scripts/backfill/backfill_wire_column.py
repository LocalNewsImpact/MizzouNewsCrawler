#!/usr/bin/env python3
"""
Backfill Wire Column Script

Processes all existing articles to populate the wire column by:
1. Running enhanced byline cleaner on author data
2. Detecting wire services while respecting source matching
3. Updating both author and wire columns
4. Handling JSON array format for authors

Key Logic:
- If wire service name closely matches source name → NOT wire content (local)
- If wire service differs from source → IS wire content (syndicated)
- Person names with wire services → separate and classify appropriately
"""

import sys
import os
import sqlite3
import json
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner

class WireBackfillProcessor:
    """Handles the backfill process for wire service detection."""
    
    def __init__(self, db_path: str = 'data/mizzou.db', dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.cleaner = BylineCleaner(enable_telemetry=False)
        
        # Statistics tracking
        self.stats = {
            'total_processed': 0,
            'wire_detected': 0,
            'local_content': 0,
            'author_cleaned': 0,
            'errors': 0,
            'skipped_no_author': 0,
            'source_matches': 0  # Wire service matches source name
        }
    
    def similarity_ratio(self, text1: str, text2: str) -> float:
        """Calculate similarity ratio between two strings."""
        if not text1 or not text2:
            return 0.0
        
        # Normalize for comparison
        norm1 = self._normalize_for_comparison(text1)
        norm2 = self._normalize_for_comparison(text2)
        
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def _normalize_for_comparison(self, text: str) -> str:
        """Normalize text for similarity comparison."""
        import re
        # Remove common words and normalize
        text = text.lower().strip()
        # Remove articles and common publication words
        text = re.sub(r'\b(the|a|an|news|press|daily|weekly|times|post|gazette|herald|tribune|journal)\b', '', text)
        # Remove extra whitespace and punctuation
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def parse_author_json(self, author_data: Any) -> List[str]:
        """Parse author data from database (could be JSON string, list, or None)."""
        if not author_data:
            return []
        
        if isinstance(author_data, str):
            try:
                # Try to parse as JSON
                parsed = json.loads(author_data)
                if isinstance(parsed, list):
                    return [str(author) for author in parsed if author]
                else:
                    return [str(parsed)] if parsed else []
            except json.JSONDecodeError:
                # Not JSON, treat as plain string
                return [author_data] if author_data.strip() else []
        elif isinstance(author_data, list):
            return [str(author) for author in author_data if author]
        else:
            return [str(author_data)] if author_data else []
    
    def format_author_json(self, authors: List[str]) -> str:
        """Format authors as JSON string for database storage."""
        return json.dumps(authors)
    
    def is_wire_service_from_own_source(self, wire_service: str, source_name: str) -> bool:
        """
        Check if detected wire service is actually from the publication's own source.
        
        Returns True if the wire service matches the source (indicating local content),
        False if it's syndicated content.
        """
        if not wire_service or not source_name:
            return False
        
        # Calculate similarity
        similarity = self.similarity_ratio(wire_service, source_name)
        
        # High similarity threshold - this is the publication's own content
        if similarity > 0.7:  # 70% similarity threshold
            print(f"   🏠 Source match detected: '{wire_service}' matches '{source_name}' (similarity: {similarity:.2f})")
            return True
        
        # Check for direct substring matches (case insensitive)
        wire_lower = wire_service.lower()
        source_lower = source_name.lower()
        
        # Check if wire service is contained in source name or vice versa
        if (wire_lower in source_lower or source_lower in wire_lower):
            print(f"   🏠 Source substring match: '{wire_service}' <-> '{source_name}'")
            return True
        
        return False
    
    def process_article(self, article_id: str, author_data: Any, source_name: str, current_wire: Any) -> Tuple[List[str], Optional[str], bool]:
        """
        Process a single article's author data.
        
        Returns:
            (new_authors, wire_service, needs_update)
        """
        # Parse current author data
        current_authors = self.parse_author_json(author_data)
        
        if not current_authors:
            self.stats['skipped_no_author'] += 1
            return [], None, False
        
        # Process each author in the list
        new_authors = []
        detected_wire_services = []
        
        for author in current_authors:
            if not author or author.strip() == '':
                continue
            
            # Use the byline cleaner to detect wire services
            if self.cleaner._is_wire_service(author):
                # Reset detection state for this cleaning session
                self.cleaner._detected_wire_services = []
                
                # Check if it's a wire service
                if self.cleaner._is_wire_service(author):
                    detected_service = (
                        self.cleaner._detected_wire_services[-1]
                        if self.cleaner._detected_wire_services
                        else author.strip()
                    )
                    
                    # Check if this wire service matches the source
                    if self.is_wire_service_from_own_source(
                            detected_service, source_name):
                        # This is local content, not syndicated
                        self.stats['source_matches'] += 1
                        print(f"   ✅ Local content: Wire service "
                              f"'{detected_service}' matches source "
                              f"'{source_name}'")
                        
                        # Try to extract actual author name from the byline
                        cleaned_result = self.cleaner.clean_byline(
                            author,
                            return_json=False,
                            source_name=source_name
                        )
                        if cleaned_result:
                            new_authors.extend(cleaned_result)
                        
                    else:
                        # This is actual syndicated wire content
                        detected_wire_services.append(detected_service)
                        print(f"   🔗 Syndicated content: "
                              f"'{detected_service}' from '{source_name}'")
                        # Do NOT add to authors - wire services are not authors
                        
            else:
                # Not a wire service, process as normal author
                cleaned_result = self.cleaner.clean_byline(
                    author,
                    return_json=False,
                    source_name=source_name
                )
                if cleaned_result:
                    new_authors.extend(cleaned_result)
        
        # Determine final wire service value
        final_wire = None
        if detected_wire_services:
            # Use the first/primary wire service detected
            final_wire = detected_wire_services[0]
            self.stats['wire_detected'] += 1
        else:
            self.stats['local_content'] += 1
        
        # Check if we need to update
        needs_update = False
        
        # Check if authors changed
        if new_authors != current_authors:
            needs_update = True
            self.stats['author_cleaned'] += 1
        
        # Check if wire service changed
        current_wire_str = str(current_wire) if current_wire else None
        final_wire_str = str(final_wire) if final_wire else None
        
        if current_wire_str != final_wire_str:
            needs_update = True
        
        return new_authors, final_wire, needs_update
    
    def get_source_name_for_article(self, cursor, article_id: str) -> Optional[str]:
        """Get the source name for an article by looking up candidate_link and source tables."""
        try:
            # Get the candidate_link_id for this article
            cursor.execute("""
                SELECT candidate_link_id 
                FROM articles 
                WHERE id = ?
            """, (article_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            candidate_link_id = result[0]
            
            # Get the source_id from candidate_links
            cursor.execute("""
                SELECT source_id 
                FROM candidate_links 
                WHERE id = ?
            """, (candidate_link_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            source_id = result[0]
            
            # Get the source name
            cursor.execute("""
                SELECT canonical_name
                FROM sources
                WHERE id = ?
            """, (source_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            canonical_name = result[0]
            return canonical_name
        
        except Exception as e:
            print(f"   ⚠️  Error getting source name for article {article_id[:8]}: {e}")
            return None
    
    def backfill_all_articles(self, limit: Optional[int] = None, offset: int = 0):
        """Backfill wire column for all articles."""
        
        print("🔄 Starting Wire Column Backfill Process")
        print("=" * 50)
        
        if self.dry_run:
            print("🚨 DRY RUN MODE - No database changes will be made")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get total count
            cursor.execute("SELECT COUNT(*) FROM articles WHERE author IS NOT NULL AND author != 'null' AND author != '[]'")
            total_count = cursor.fetchone()[0]
            
            print(f"📊 Found {total_count} articles with author data")
            
            if limit:
                print(f"🎯 Processing {limit} articles (offset: {offset})")
            
            # Get articles to process
            query = """
                SELECT id, author, wire 
                FROM articles 
                WHERE author IS NOT NULL 
                AND author != 'null' 
                AND author != '[]'
                ORDER BY created_at DESC
            """
            
            if limit:
                query += f" LIMIT {limit} OFFSET {offset}"
            
            cursor.execute(query)
            articles = cursor.fetchall()
            
            print(f"🚀 Processing {len(articles)} articles...")
            print("-" * 50)
            
            updates_to_perform = []
            
            for i, (article_id, author_data, current_wire) in enumerate(articles, 1):
                try:
                    # Get source name for this article
                    source_name = self.get_source_name_for_article(cursor, article_id)
                    
                    print(f"\n{i:4d}. Article {article_id[:8]}... (Source: {source_name or 'Unknown'})")
                    print(f"      Current Authors: {author_data}")
                    
                    # Process the article
                    new_authors, final_wire, needs_update = self.process_article(
                        article_id, author_data, source_name, current_wire
                    )
                    
                    if needs_update:
                        print(f"      New Authors: {new_authors}")
                        if final_wire:
                            print(f"      🎯 Wire Service: {final_wire}")
                        else:
                            print("      ✅ Local Content")
                        
                        # Store update for later execution
                        updates_to_perform.append({
                            'article_id': article_id,
                            'new_authors': new_authors,
                            'final_wire': final_wire
                        })
                    else:
                        print("      ✅ No changes needed")
                    
                    self.stats['total_processed'] += 1
                    
                    # Progress indicator
                    if i % 50 == 0:
                        print(f"\n📈 Progress: {i}/{len(articles)} articles processed")
                        self._print_stats()
                
                except Exception as e:
                    print(f"      ❌ Error processing article {article_id[:8]}: {e}")
                    self.stats['errors'] += 1
                    continue
            
            # Perform updates
            if updates_to_perform:
                print(f"\n💾 Applying {len(updates_to_perform)} updates...")
                
                if not self.dry_run:
                    self._apply_updates(cursor, updates_to_perform)
                    conn.commit()
                    print("✅ Database updates committed!")
                else:
                    print("🚨 DRY RUN - Updates would be applied here")
                    # Show sample updates
                    for update in updates_to_perform[:5]:
                        authors_json = self.format_author_json(update['new_authors'])
                        print(f"   UPDATE articles SET author='{authors_json}', wire='{update['final_wire']}' WHERE id='{update['article_id'][:8]}...'")
                    if len(updates_to_perform) > 5:
                        print(f"   ... and {len(updates_to_perform) - 5} more updates")
            else:
                print("\n✅ No updates needed - all articles already processed correctly")
            
            conn.close()
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            raise
    
    def _apply_updates(self, cursor, updates: List[Dict]):
        """Apply the updates to the database."""
        for update in updates:
            authors_json = self.format_author_json(update['new_authors'])
            
            cursor.execute("""
                UPDATE articles 
                SET author = ?, wire = ? 
                WHERE id = ?
            """, (authors_json, update['final_wire'], update['article_id']))
    
    def _print_stats(self):
        """Print current statistics."""
        print("\n📊 Current Statistics:")
        print(f"   Total Processed: {self.stats['total_processed']}")
        print(f"   Wire Detected: {self.stats['wire_detected']}")
        print(f"   Local Content: {self.stats['local_content']}")
        print(f"   Source Matches: {self.stats['source_matches']}")
        print(f"   Authors Cleaned: {self.stats['author_cleaned']}")
        print(f"   Skipped (No Author): {self.stats['skipped_no_author']}")
        print(f"   Errors: {self.stats['errors']}")
    
    def print_final_summary(self):
        """Print final processing summary."""
        print("\n" + "=" * 60)
        print("🎉 Wire Column Backfill Complete!")
        print("=" * 60)
        
        self._print_stats()
        
        if self.stats['total_processed'] > 0:
            wire_percentage = (self.stats['wire_detected'] / self.stats['total_processed']) * 100
            local_percentage = (self.stats['local_content'] / self.stats['total_processed']) * 100
            
            print("\n📈 Content Distribution:")
            print(f"   Wire Content: {wire_percentage:.1f}%")
            print(f"   Local Content: {local_percentage:.1f}%")
            
            if self.stats['source_matches'] > 0:
                print("\n🏠 Source Matching:")
                print(f"   Wire services matching source names: {self.stats['source_matches']}")
                print("   These were correctly classified as LOCAL content")


def main():
    """Main execution function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Backfill wire column with enhanced source matching')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--limit', type=int, help='Limit number of articles to process')
    parser.add_argument('--offset', type=int, default=0, help='Starting offset for processing')
    parser.add_argument('--db-path', default='data/mizzou.db', help='Path to database file')
    
    args = parser.parse_args()
    
    # Create processor
    processor = WireBackfillProcessor(
        db_path=args.db_path,
        dry_run=args.dry_run
    )
    
    try:
        # Run backfill
        processor.backfill_all_articles(
            limit=args.limit,
            offset=args.offset
        )
        
        # Print summary
        processor.print_final_summary()
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Process interrupted by user")
        processor.print_final_summary()
    except Exception as e:
        print(f"\n❌ Error during backfill: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()