#!/usr/bin/env python3

"""
Re-clean existing author names using telemetry data.

This script finds original bylines from the telemetry data and re-cleans them
with the improved byline cleaner, then updates the articles table.
"""

import sys
import os
import sqlite3
import json
from typing import List, Dict, Tuple
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner

# Simple logging
def log_info(message: str):
    print(f"[INFO] {message}")

def log_error(message: str):
    print(f"[ERROR] {message}")


def get_telemetry_originals(db_path: str) -> List[Tuple]:
    """
    Get original bylines from telemetry data that can be re-cleaned.
    
    Returns:
        List of tuples: (article_id, original_byline, current_authors)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Get current telemetry entries with raw bylines
        query = """
        SELECT t.article_id, t.raw_byline, t.final_authors_json, t.confidence_score,
               a.author as current_authors, a.title, a.url
        FROM byline_cleaning_telemetry t
        JOIN articles a ON t.article_id = a.id
        WHERE t.raw_byline IS NOT NULL 
        AND t.final_authors_json IS NOT NULL
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
    finally:
        conn.close()
    
    log_info(f"Found {len(results)} articles with telemetry data")
    return results


def re_clean_authors(telemetry_data: List[Tuple], 
                    db_path: str, 
                    dry_run: bool = True) -> Dict:
    """
    Re-clean author names using improved byline cleaner.
    
    Args:
        telemetry_data: List of (article_id, original_byline, current_authors, ...)
        db_path: Path to database
        dry_run: If True, don't actually update the database
        
    Returns:
        Dictionary with statistics and results
    """
    cleaner = BylineCleaner(enable_telemetry=False)  # Disable to avoid interference
    
    stats = {
        'total_processed': 0,
        'improved': 0,
        'unchanged': 0,
        'degraded': 0,
        'empty_to_filled': 0,
        'filled_to_empty': 0,
        'improvements': [],
        'degradations': []
    }
    
    conn = sqlite3.connect(db_path) if not dry_run else None
    cursor = conn.cursor() if not dry_run else None
    
    for article_id, original_byline, telemetry_result, confidence_score, current_author, title, url in telemetry_data:
        stats['total_processed'] += 1
        
        # Re-clean the original byline
        new_authors = cleaner.clean_byline(original_byline)
        
        # Parse current authors
        try:
            if current_author:
                current_authors = json.loads(current_author) if isinstance(current_author, str) else current_author
                if not isinstance(current_authors, list):
                    current_authors = [current_author] if current_author else []
            else:
                current_authors = []
        except (json.JSONDecodeError, TypeError):
            current_authors = [current_author] if current_author else []
        
        # Compare results
        current_count = len(current_authors)
        new_count = len(new_authors)
        
        # Normalize for comparison
        current_set = set(author.lower().strip() for author in current_authors if author)
        new_set = set(author.lower().strip() for author in new_authors if author)
        
        # Determine if this is an improvement
        is_improvement = False
        
        if current_count == 0 and new_count > 0:
            # Empty to filled - definitely an improvement
            stats['empty_to_filled'] += 1
            is_improvement = True
            
        elif current_count > 0 and new_count == 0:
            # Filled to empty - likely a degradation
            stats['filled_to_empty'] += 1
            
        elif new_set != current_set:
            # Different results - need to evaluate quality
            
            # Check for common improvements
            improvements_found = []
            
            # Look for apostrophe fixes
            for new_author in new_authors:
                if "'" in new_author:  # Has apostrophe
                    # See if current version was broken
                    for current_author in current_authors:
                        if new_author.replace("'", "").lower() in current_author.lower():
                            improvements_found.append(f"Fixed apostrophe: '{current_author}' -> '{new_author}'")
            
            # Look for "Last, First" reordering
            for new_author in new_authors:
                if len(new_author.split()) == 2:  # "First Last" format
                    first, last = new_author.split()
                    for current_author in current_authors:
                        if current_author.lower().strip() == f"{last.lower()}, {first.lower()}":
                            improvements_found.append(f"Fixed name order: '{current_author}' -> '{new_author}'")
            
            # Look for title removal improvements
            title_words = {'staff', 'reporter', 'editor', 'writer', 'correspondent'}
            for current_author in current_authors:
                if any(word in current_author.lower() for word in title_words):
                    for new_author in new_authors:
                        if not any(word in new_author.lower() for word in title_words):
                            if new_author.lower().replace(' ', '') in current_author.lower().replace(' ', ''):
                                improvements_found.append(f"Removed title: '{current_author}' -> '{new_author}'")
            
            if improvements_found:
                stats['improved'] += 1
                is_improvement = True
                stats['improvements'].append({
                    'article_id': article_id,
                    'title': title,
                    'url': url,
                    'original_byline': original_byline,
                    'current': current_authors,
                    'new': new_authors,
                    'improvements': improvements_found
                })
            else:
                # No clear improvements detected, but results are different
                # Default to considering it unchanged unless clearly worse
                if new_count < current_count:
                    stats['degraded'] += 1
                    stats['degradations'].append({
                        'article_id': article_id,
                        'title': title,
                        'original_byline': original_byline,
                        'current': current_authors,
                        'new': new_authors,
                        'issue': f"Reduced from {current_count} to {new_count} authors"
                    })
                else:
                    stats['unchanged'] += 1
        else:
            # Same results
            stats['unchanged'] += 1
        
        # Update database if not dry run and there's an improvement
        if not dry_run and is_improvement and cursor:
            new_author_json = json.dumps(new_authors) if new_authors else None
            cursor.execute(
                "UPDATE articles SET author = ?, updated_at = ? WHERE id = ?",
                (new_author_json, datetime.now().isoformat(), article_id)
            )
            log_info(f"Updated article {article_id}: {current_authors} -> {new_authors}")
    
    if not dry_run and conn:
        conn.commit()
        conn.close()
    
    return stats


def print_re_cleaning_report(stats: Dict):
    """Print a comprehensive report of the re-cleaning results."""
    
    print("\n" + "=" * 60)
    print("🧹 BYLINE RE-CLEANING REPORT")
    print("=" * 60)
    
    print("\n📊 OVERALL STATISTICS:")
    print(f"   Total articles processed: {stats['total_processed']}")
    print(f"   ✅ Improved: {stats['improved']}")
    print(f"   ➡️ Unchanged: {stats['unchanged']}")
    print(f"   ❌ Degraded: {stats['degraded']}")
    print(f"   🆕 Empty to filled: {stats['empty_to_filled']}")
    print(f"   🗑️ Filled to empty: {stats['filled_to_empty']}")
    
    if stats['total_processed'] > 0:
        improvement_rate = (stats['improved'] + stats['empty_to_filled']) / stats['total_processed'] * 100
        print(f"\n🎯 Improvement rate: {improvement_rate:.1f}%")
    
    # Show top improvements
    if stats['improvements']:
        print(f"\n🎉 TOP IMPROVEMENTS ({len(stats['improvements'])} total):")
        for i, improvement in enumerate(stats['improvements'][:10], 1):
            print(f"\n{i:2d}. Article: {improvement['title'][:50]}...")
            print(f"    Original byline: '{improvement['original_byline']}'")
            print(f"    Current:  {improvement['current']}")
            print(f"    New:      {improvement['new']}")
            for fix in improvement['improvements']:
                print(f"    🔧 {fix}")
    
    # Show degradations
    if stats['degradations']:
        print(f"\n⚠️ POTENTIAL DEGRADATIONS ({len(stats['degradations'])} total):")
        for i, degradation in enumerate(stats['degradations'][:5], 1):
            print(f"\n{i:2d}. Article: {degradation['title'][:50]}...")
            print(f"    Original byline: '{degradation['original_byline']}'")
            print(f"    Current: {degradation['current']}")
            print(f"    New:     {degradation['new']}")
            print(f"    Issue:   {degradation['issue']}")


def main():
    """Main function to re-clean author names."""
    
    db_path = 'data/mizzou.db'
    
    print("🧹 BYLINE RE-CLEANING UTILITY")
    print("Using telemetry data to find and re-clean original bylines")
    print("=" * 60)
    
    # Get telemetry data
    print("📊 Fetching telemetry data...")
    telemetry_data = get_telemetry_originals(db_path)
    
    if not telemetry_data:
        print("❌ No telemetry data found. Cannot perform re-cleaning.")
        return
    
    print(f"✅ Found {len(telemetry_data)} articles with original bylines")
    
    # First, do a dry run to see what would change
    print("\n🔍 Performing dry run analysis...")
    dry_run_stats = re_clean_authors(telemetry_data, db_path, dry_run=True)
    
    # Show dry run results
    print_re_cleaning_report(dry_run_stats)
    
    # Ask user if they want to proceed
    print("\n" + "=" * 60)
    proceed = input("\n🤔 Do you want to apply these improvements to the database? (y/N): ").lower()
    
    if proceed == 'y':
        print("\n🚀 Applying improvements to database...")
        real_stats = re_clean_authors(telemetry_data, db_path, dry_run=False)
        
        print("\n✅ Database updated!")
        print(f"   {real_stats['improved'] + real_stats['empty_to_filled']} articles improved")
        print(f"   {real_stats['unchanged']} articles unchanged")
        
        if real_stats['degraded'] > 0:
            print(f"   ⚠️ {real_stats['degraded']} potential degradations (not applied)")
    else:
        print("\n❌ Re-cleaning cancelled. No changes made to database.")


if __name__ == "__main__":
    main()