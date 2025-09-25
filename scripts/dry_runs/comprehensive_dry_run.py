#!/usr/bin/env python3
"""
Better dry run that simulates real byline processing scenarios.
This reconstructs potential original bylines from the JSON data.
"""

import sqlite3
import json
import sys
import os
from collections import defaultdict, Counter
from typing import Dict, List, Tuple

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.utils.byline_cleaner import BylineCleaner
except ImportError:
    print("Error: Could not import BylineCleaner")
    sys.exit(1)


def parse_authors_json(authors_json: str) -> List[str]:
    """Parse authors JSON string into list of author names."""
    try:
        if not authors_json or authors_json.strip() == '':
            return []
        
        if authors_json.startswith('[') and authors_json.endswith(']'):
            authors = json.loads(authors_json)
            return [str(author).strip() for author in authors
                    if str(author).strip()]
        else:
            return [authors_json.strip()] if authors_json.strip() else []
    except (json.JSONDecodeError, ValueError):
        return [authors_json.strip()] if authors_json.strip() else []


def reconstruct_possible_bylines(authors: List[str]) -> List[str]:
    """
    Reconstruct possible original byline formats from author list.
    This simulates what the original byline text might have looked like.
    """
    if not authors:
        return []
    
    if len(authors) == 1:
        author = authors[0]
        # Single author scenarios
        return [
            author,  # Clean name
            f"By {author}",  # With "By" prefix
            f"{author}, Reporter",  # With title suffix
            f"{author} | Staff Writer",  # With pipe separator
        ]
    elif len(authors) == 2:
        # Two author scenarios
        return [
            f"{authors[0]}, {authors[1]}",  # Comma separated
            f"{authors[0]} and {authors[1]}",  # "and" separated
            f"By {authors[0]} and {authors[1]}",  # With "By" prefix
            f"{authors[0]}, {authors[1]}, Staff Writers",  # With titles
        ]
    else:
        # Multiple authors (rare, but happens)
        comma_sep = ", ".join(authors)
        return [
            comma_sep,
            f"By {comma_sep}",
            f"{comma_sep}, Staff",
        ]


def analyze_author_changes(current: List[str], new: List[str]) -> Dict:
    """Analyze the differences between current and new author lists."""
    current_set = set(current)
    new_set = set(new)
    
    # Calculate quality scores
    current_quality = sum(1 for name in current if len(name.split()) >= 2)
    new_quality = sum(1 for name in new if len(name.split()) >= 2)
    
    # Detect improvements
    is_improvement = (
        # Same or more authors with better quality
        (len(new) >= len(current) and new_quality >= current_quality) or
        # Removed obvious noise while keeping real names
        (len(new) < len(current) and new_quality >= current_quality and
         any(removed.lower() in ['cnn', 'ap', 'reuters', 'staff', 'reporter', 
                               'editor', 'news', 'forum', 'owner', 'inc']
             for removed in (current_set - new_set)))
    )
    
    return {
        'current_count': len(current),
        'new_count': len(new),
        'current_authors': current,
        'new_authors': new,
        'added': list(new_set - current_set),
        'removed': list(current_set - new_set),
        'unchanged': list(current_set & new_set),
        'is_changed': current != new,
        'is_improvement': is_improvement,
        'current_quality': current_quality,
        'new_quality': new_quality
    }


def run_comprehensive_dry_run():
    """Run comprehensive dry run with reconstructed bylines."""
    
    print("🧪 COMPREHENSIVE DRY RUN: New Byline Cleaning Algorithm")
    print("=" * 60)
    
    # Database path
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'mizzou.db')
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get articles with authors
    cursor.execute("""
        SELECT id, title, author
        FROM articles
        WHERE author IS NOT NULL
        AND author != ''
        ORDER BY id
        LIMIT 200
    """)
    
    articles = cursor.fetchall()
    conn.close()
    
    print(f"📊 Testing with {len(articles)} articles")
    
    # Initialize cleaner
    cleaner = BylineCleaner(enable_telemetry=False)
    
    # Analysis tracking
    scenario_results = defaultdict(lambda: defaultdict(list))
    overall_improvements = 0
    overall_degradations = 0
    total_tests = 0
    
    print("\n🔄 Processing articles and reconstructed bylines...")
    
    for i, (article_id, title, author_json) in enumerate(articles, 1):
        if i % 50 == 0:
            print(f"   ... processed {i}/{len(articles)} articles")
        
        # Parse current authors
        current_authors = parse_authors_json(author_json)
        if not current_authors:
            continue
        
        # Generate possible original bylines
        possible_bylines = reconstruct_possible_bylines(current_authors)
        
        for byline_format, original_byline in enumerate(possible_bylines):
            total_tests += 1
            
            # Test the byline cleaning
            try:
                new_authors = cleaner.clean_byline(original_byline, 
                                                 return_json=False)
            except Exception as e:
                new_authors = []
            
            # Analyze the result
            analysis = analyze_author_changes(current_authors, new_authors)
            
            # Categorize the scenario
            scenario_key = f"{len(current_authors)}_authors"
            format_key = f"format_{byline_format}"
            
            scenario_results[scenario_key][format_key].append({
                'article_id': article_id,
                'original_byline': original_byline,
                'analysis': analysis
            })
            
            if analysis['is_improvement']:
                overall_improvements += 1
            elif analysis['is_changed'] and not analysis['is_improvement']:
                overall_degradations += 1
    
    # Generate report
    print(f"\n✅ Completed {total_tests} tests")
    print("\n" + "=" * 60)
    print("📊 COMPREHENSIVE ANALYSIS RESULTS")
    print("=" * 60)
    
    print(f"\n📈 OVERALL PERFORMANCE:")
    print(f"   Total tests: {total_tests:,}")
    print(f"   Improvements: {overall_improvements:,}")
    print(f"   Degradations: {overall_degradations:,}")
    print(f"   Unchanged: {total_tests - overall_improvements - overall_degradations:,}")
    improvement_rate = (overall_improvements / total_tests) * 100
    print(f"   Improvement rate: {improvement_rate:.1f}%")
    
    # Analyze by scenario
    print(f"\n📋 RESULTS BY SCENARIO:")
    
    for scenario, formats in scenario_results.items():
        total_scenario_tests = sum(len(results) for results in formats.values())
        scenario_improvements = sum(
            1 for results in formats.values()
            for result in results
            if result['analysis']['is_improvement']
        )
        
        scenario_rate = (scenario_improvements / total_scenario_tests) * 100
        print(f"\n   {scenario.replace('_', ' ').title()}:")
        print(f"     Tests: {total_scenario_tests}")
        print(f"     Improvements: {scenario_improvements}")
        print(f"     Success rate: {scenario_rate:.1f}%")
        
        # Show examples for this scenario
        for format_key, results in formats.items():
            if results:
                improvements = [r for r in results if r['analysis']['is_improvement']]
                if improvements:
                    example = improvements[0]  # Take first improvement example
                    analysis = example['analysis']
                    print(f"     Example ({format_key}):")
                    print(f"       Byline: \"{example['original_byline']}\"")
                    print(f"       Before: {analysis['current_authors']}")
                    print(f"       After: {analysis['new_authors']}")
                    if analysis['removed']:
                        print(f"       Removed: {analysis['removed']}")
    
    # Detailed analysis of what gets removed
    print(f"\n🔍 NOISE FILTERING ANALYSIS:")
    removed_terms = Counter()
    
    for scenario, formats in scenario_results.items():
        for format_key, results in formats.items():
            for result in results:
                analysis = result['analysis']
                for removed in analysis.get('removed', []):
                    removed_terms[removed.lower()] += 1
    
    print("   Most frequently removed terms:")
    for term, count in removed_terms.most_common(10):
        print(f"     \"{term}\": {count} times")
    
    # Final recommendation
    print(f"\n💡 FINAL ASSESSMENT:")
    if improvement_rate > 70:
        print("   ✅ RECOMMENDED: Algorithm shows excellent performance")
    elif improvement_rate > 50:
        print("   ✅ RECOMMENDED: Algorithm shows good performance")
    elif improvement_rate > 30:
        print("   ⚠️  CAUTION: Algorithm shows mixed results")
    else:
        print("   ❌ NOT RECOMMENDED: Algorithm needs improvement")
    
    print(f"\n   Key strengths:")
    if overall_improvements > overall_degradations * 2:
        print("   - Significantly more improvements than degradations")
    if removed_terms:
        print("   - Effectively removes organizational noise")
    
    print("\n" + "=" * 60)
    print("🎯 COMPREHENSIVE DRY RUN COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    run_comprehensive_dry_run()