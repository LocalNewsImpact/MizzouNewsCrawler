#!/usr/bin/env python3
"""
Demo script showing the complete URL verification workflow.

This demonstrates the background verification system that:
1. Takes URLs with 'discovered' status
2. Runs StorySniffer verification
3. Updates status to 'article' or 'not_article'
4. Provides telemetry tracking by extraction job
5. Shows how extraction would filter by verified status
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from sqlalchemy import text
from models.database import DatabaseManager
from services.url_verification import URLVerificationService


def show_verification_status():
    """Show current verification status."""
    print("\n" + "="*60)
    print("VERIFICATION STATUS CHECK")
    print("="*60)
    
    db = DatabaseManager()
    session = db.session
    
    # Get status counts
    result = session.execute(text("""
        SELECT status, COUNT(*) as count
        FROM candidate_links
        GROUP BY status
        ORDER BY count DESC
    """))
    
    total = 0
    status_counts = {}
    for row in result:
        status_counts[row[0]] = row[1]
        total += row[1]
    
    print(f"Total URLs: {total}")
    print(f"Pending verification: {status_counts.get('discovered', 0)}")
    print(f"Verified articles: {status_counts.get('article', 0)}")
    print(f"Verified non-articles: {status_counts.get('not_article', 0)}")
    print(f"Verification failures: {status_counts.get('verification_failed', 0)}")
    
    print("\nStatus breakdown:")
    for status, count in status_counts.items():
        print(f"  {status}: {count}")
    
    session.close()
    return status_counts


def run_verification_demo(batch_size=10):
    """Run a demonstration verification batch."""
    print("\n" + "="*60)
    print(f"RUNNING VERIFICATION DEMO (batch_size={batch_size})")
    print("="*60)
    
    service = URLVerificationService(batch_size=batch_size, sleep_interval=1)
    
    # Get a small batch to process
    db = service.db
    session = db.session
    
    candidates = session.execute(text("""
        SELECT id, url, source
        FROM candidate_links
        WHERE status = 'discovered'
        ORDER BY created_at DESC
        LIMIT :batch_size
    """), {"batch_size": batch_size}).fetchall()
    
    if not candidates:
        print("No URLs with 'discovered' status found!")
        session.close()
        return
    
    print(f"Found {len(candidates)} URLs to verify:")
    for i, candidate in enumerate(candidates[:3], 1):
        print(f"  {i}. {candidate[1]} (source: {candidate[2]})")
    if len(candidates) > 3:
        print(f"  ... and {len(candidates) - 3} more")
    
    session.close()
    
    # Process the batch
    print(f"\nProcessing {len(candidates)} URLs with StorySniffer...")
    candidates_dict = [
        {"id": c[0], "url": c[1], "source": c[2]} 
        for c in candidates
    ]
    
    metrics = service.process_batch(candidates_dict)
    
    print(f"✅ Verification complete!")
    print(f"   Articles found: {metrics['verified_articles']}")
    print(f"   Non-articles: {metrics['verified_non_articles']}")
    print(f"   Errors: {metrics['verification_errors']}")
    print(f"   Average time: {metrics['avg_verification_time_ms']:.1f}ms")


def show_article_extraction_simulation():
    """Show how extraction would work with verified URLs."""
    print("\n" + "="*60)
    print("ARTICLE EXTRACTION SIMULATION")
    print("="*60)
    
    db = DatabaseManager()
    session = db.session
    
    # Show URLs that would be processed by extraction
    result = session.execute(text("""
        SELECT url, source, created_at
        FROM candidate_links
        WHERE status = 'article'
        ORDER BY created_at DESC
        LIMIT 5
    """))
    
    articles = result.fetchall()
    
    if articles:
        print(f"URLs ready for article extraction ({len(articles)} shown):")
        for i, article in enumerate(articles, 1):
            print(f"  {i}. {article[0]} (source: {article[1]})")
    else:
        print("No verified articles found yet.")
        print("Run verification on more URLs to find actual articles.")
    
    # Show URLs that would be skipped
    result = session.execute(text("""
        SELECT COUNT(*)
        FROM candidate_links
        WHERE status = 'not_article'
    """))
    
    not_articles = result.fetchone()[0]
    print(f"\nURLs that would be SKIPPED by extraction: {not_articles}")
    print("(These were verified as non-articles by StorySniffer)")
    
    session.close()


def show_telemetry_data():
    """Show telemetry data from verification runs."""
    print("\n" + "="*60)
    print("VERIFICATION TELEMETRY")
    print("="*60)
    
    try:
        with open("verification_telemetry.log", "r") as f:
            content = f.read().strip()
            if content:
                import json
                # Get the last entry
                lines = content.strip().split('\n')
                if lines:
                    last_entry = json.loads(lines[-1])
                    print(f"Latest verification job: {last_entry['job_name']}")
                    print(f"Timestamp: {last_entry['timestamp']}")
                    print(f"Batch size: {last_entry['batch_size']}")
                    print(f"Metrics:")
                    for key, value in last_entry['metrics'].items():
                        if isinstance(value, float):
                            print(f"  {key}: {value:.2f}")
                        else:
                            print(f"  {key}: {value}")
                    print(f"Sources: {', '.join(last_entry['sources_processed'])}")
                else:
                    print("No telemetry data found.")
            else:
                print("No telemetry data found.")
    except FileNotFoundError:
        print("No telemetry file found. Run verification first.")


def main():
    """Run the complete verification workflow demo."""
    print("URL VERIFICATION WORKFLOW DEMONSTRATION")
    print("="*60)
    print("This demo shows the complete background verification system:")
    print("1. URLs start with 'discovered' status")
    print("2. StorySniffer verifies each URL") 
    print("3. Status changes to 'article' or 'not_article'")
    print("4. Telemetry tracks the verification job")
    print("5. Extraction processes only 'article' status URLs")
    
    # Show initial status
    initial_status = show_verification_status()
    
    # If we have URLs to verify, run a demo batch
    if initial_status.get('discovered', 0) > 0:
        run_verification_demo(batch_size=min(10, initial_status['discovered']))
        
        # Show updated status
        show_verification_status()
    else:
        print("\nNo URLs with 'discovered' status found.")
        print("Run URL discovery first to populate URLs for verification.")
    
    # Show extraction simulation
    show_article_extraction_simulation()
    
    # Show telemetry
    show_telemetry_data()
    
    print("\n" + "="*60)
    print("WORKFLOW COMPLETE")
    print("="*60)
    print("The verification system successfully:")
    print("✅ Processes URLs with 'discovered' status")
    print("✅ Uses StorySniffer to verify article content")
    print("✅ Updates status to 'article' or 'not_article'")
    print("✅ Logs comprehensive telemetry by job")
    print("✅ Enables extraction to process only verified articles")
    
    print("\nTo run ongoing verification:")
    print("  python -m src.services.url_verification")
    print("\nTo check verification status:")
    print("  python -m src.services.url_verification --status")


if __name__ == "__main__":
    main()