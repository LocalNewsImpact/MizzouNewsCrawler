#!/usr/bin/env python3
"""
Extraction telemetry reporting and analysis tools.

This script provides comprehensive reporting on content extraction performance,
error analysis, and success metrics from the extraction_outcomes table.

Usage:
    python scripts/extraction_report.py --operation-id uuid
    python scripts/extraction_report.py --last-hours 24
    python scripts/extraction_report.py --summary
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.extraction_telemetry import ExtractionTelemetry


def print_operation_report(telemetry: ExtractionTelemetry, operation_id: str):
    """Print detailed report for a specific operation."""
    stats = telemetry.get_extraction_stats(operation_id)
    
    if not stats:
        print(f"No data found for operation {operation_id}")
        return
    
    print(f"\nOPERATION REPORT: {operation_id}")
    print("=" * 60)
    
    total_articles = sum(stat['count'] for stat in stats)
    total_time = sum(stat['count'] * stat['avg_time_ms'] for stat in stats)
    
    print(f"Total articles processed: {total_articles}")
    print(f"Total processing time: {total_time/1000:.1f} seconds")
    print(f"Average time per article: {total_time/total_articles:.1f}ms")
    
    # Success rate
    successful = sum(stat['count'] for stat in stats 
                    if stat['outcome'] == 'CONTENT_EXTRACTED')
    success_rate = (successful / total_articles * 100) if total_articles > 0 else 0
    print(f"Success rate: {success_rate:.1f}% ({successful}/{total_articles})")
    
    print("\nOutcome breakdown:")
    print("-" * 40)
    for stat in sorted(stats, key=lambda x: x['count'], reverse=True):
        pct = (stat['count'] / total_articles * 100) if total_articles > 0 else 0
        print(f"{stat['outcome']:20} {stat['count']:4} ({pct:5.1f}%) "
              f"avg: {stat['avg_time_ms']:6.1f}ms "
              f"quality: {stat['avg_quality_score']:4.2f}")


def print_time_range_report(telemetry: ExtractionTelemetry, hours: int):
    """Print report for extractions in the last N hours."""
    print(f"\nEXTRACTION REPORT: Last {hours} hours")
    print("=" * 60)
    
    # Get database connection for custom queries
    import sqlite3
    from pathlib import Path
    
    # Use the same database path logic as telemetry
    db_path = Path(__file__).parent.parent / "data" / "mizzou.db"
    
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        
        # Basic stats
        result = conn.execute("""
            SELECT 
                COUNT(*) as total_extractions,
                COUNT(DISTINCT operation_id) as operations,
                AVG(extraction_time_ms) as avg_time,
                AVG(content_quality_score) as avg_quality
            FROM extraction_outcomes 
            WHERE timestamp > ?
        """, (cutoff_time.isoformat(),)).fetchone()
        
        if result['total_extractions'] == 0:
            print(f"No extractions found in the last {hours} hours")
            return
        
        print(f"Total extractions: {result['total_extractions']}")
        print(f"Extraction operations: {result['operations']}")
        print(f"Average processing time: {result['avg_time']:.1f}ms")
        print(f"Average content quality: {result['avg_quality']:.2f}")
        
        # Outcome distribution
        outcomes = conn.execute("""
            SELECT 
                outcome,
                COUNT(*) as count,
                AVG(extraction_time_ms) as avg_time,
                AVG(content_quality_score) as avg_quality
            FROM extraction_outcomes 
            WHERE timestamp > ?
            GROUP BY outcome
            ORDER BY count DESC
        """, (cutoff_time.isoformat(),)).fetchall()
        
        print("\nOutcome distribution:")
        print("-" * 40)
        for outcome in outcomes:
            pct = (outcome['count'] / result['total_extractions'] * 100)
            print(f"{outcome['outcome']:20} {outcome['count']:4} ({pct:5.1f}%) "
                  f"avg: {outcome['avg_time']:6.1f}ms "
                  f"quality: {outcome['avg_quality']:4.2f}")
        
        # Error analysis for failures
        errors = conn.execute("""
            SELECT 
                http_status_code,
                COUNT(*) as count
            FROM extraction_outcomes 
            WHERE timestamp > ? 
            AND outcome != 'CONTENT_EXTRACTED'
            AND http_status_code IS NOT NULL
            GROUP BY http_status_code
            ORDER BY count DESC
        """, (cutoff_time.isoformat(),)).fetchall()
        
        if errors:
            print("\nHTTP error codes:")
            print("-" * 25)
            for error in errors:
                print(f"HTTP {error['http_status_code']:3}: {error['count']} occurrences")


def print_summary_report(telemetry: ExtractionTelemetry):
    """Print overall extraction statistics summary."""
    print("\nEXTRACTION SUMMARY (All Time)")
    print("=" * 60)
    
    import sqlite3
    from pathlib import Path
    
    # Use the same database path logic as telemetry
    db_path = Path(__file__).parent.parent / "data" / "mizzou.db"
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        
        # Overall stats
        result = conn.execute("""
            SELECT 
                COUNT(*) as total_extractions,
                COUNT(DISTINCT operation_id) as total_operations,
                MIN(timestamp) as first_extraction,
                MAX(timestamp) as last_extraction,
                AVG(extraction_time_ms) as avg_time,
                AVG(content_quality_score) as avg_quality
            FROM extraction_outcomes
        """).fetchone()
        
        if result['total_extractions'] == 0:
            print("No extraction data found")
            return
        
        print(f"Total extractions: {result['total_extractions']}")
        print(f"Total operations: {result['total_operations']}")
        print(f"First extraction: {result['first_extraction']}")
        print(f"Last extraction: {result['last_extraction']}")
        print(f"Average processing time: {result['avg_time']:.1f}ms")
        print(f"Average content quality: {result['avg_quality']:.2f}")
        
        # Success rate
        success = conn.execute("""
            SELECT COUNT(*) as successful
            FROM extraction_outcomes 
            WHERE outcome = 'CONTENT_EXTRACTED'
        """).fetchone()
        
        success_rate = (success['successful'] / result['total_extractions'] * 100)
        print(f"Overall success rate: {success_rate:.1f}% "
              f"({success['successful']}/{result['total_extractions']})")
        
        # Top failure reasons
        failures = conn.execute("""
            SELECT 
                outcome,
                COUNT(*) as count
            FROM extraction_outcomes 
            WHERE outcome != 'CONTENT_EXTRACTED'
            GROUP BY outcome
            ORDER BY count DESC
            LIMIT 5
        """).fetchall()
        
        if failures:
            print("\nTop failure reasons:")
            print("-" * 30)
            for failure in failures:
                pct = (failure['count'] / result['total_extractions'] * 100)
                print(f"{failure['outcome']:20} {failure['count']:4} ({pct:4.1f}%)")


def main():
    """Main reporting function."""
    parser = argparse.ArgumentParser(
        description="Generate extraction telemetry reports"
    )
    parser.add_argument(
        "--operation-id", 
        help="Report on specific operation ID"
    )
    parser.add_argument(
        "--last-hours", 
        type=int, 
        help="Report on extractions in last N hours"
    )
    parser.add_argument(
        "--summary", 
        action="store_true", 
        help="Show overall summary statistics"
    )
    
    args = parser.parse_args()
    
    if not any([args.operation_id, args.last_hours, args.summary]):
        parser.print_help()
        return 1
    
    telemetry = ExtractionTelemetry()
    
    if args.operation_id:
        print_operation_report(telemetry, args.operation_id)
    
    if args.last_hours:
        print_time_range_report(telemetry, args.last_hours)
    
    if args.summary:
        print_summary_report(telemetry)
    
    return 0


if __name__ == "__main__":
    exit(main())