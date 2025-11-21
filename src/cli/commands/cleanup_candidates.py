"""
Cleanup command for candidate links that have been pending too long.

Marks candidates in 'article' status older than a threshold as 'paused' to prevent
them from blocking the extraction pipeline. These candidates have likely already
been attempted and failed transiently multiple times.
"""

import logging
from sqlalchemy import text

from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)


def add_cleanup_candidates_parser(subparsers):
    """Add cleanup-candidates command parser."""
    parser = subparsers.add_parser(
        "cleanup-candidates",
        help="Mark expired candidate links as paused (older than threshold)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Mark candidates older than this many days as paused (default: 7)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be paused without making changes",
    )
    return parser


def handle_cleanup_candidates_command(args):
    """Handle cleanup-candidates command.
    
    Args:
        args: Parsed command arguments
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        days_threshold = args.days
        dry_run = args.dry_run
        
        db = DatabaseManager()
        
        print()
        print("🧹 Candidate Link Cleanup")
        print("=" * 60)
        print(f"Threshold: {days_threshold} days")
        print(f"Dry run: {dry_run}")
        print()
        
        with db.get_session() as session:
            # Find expired candidates
            expired = session.execute(text(f"""
                SELECT id, source, url, created_at,
                    EXTRACT(EPOCH FROM (NOW() - created_at))/86400 as age_days
                FROM candidate_links
                WHERE status = 'article'
                AND created_at < NOW() - INTERVAL '{days_threshold} days'
                ORDER BY created_at ASC
            """)).fetchall()
            
            if not expired:
                print(f"✓ No candidates older than {days_threshold} days found")
                return 0
            
            print(f"Found {len(expired)} candidates older than {days_threshold} days:")
            print()
            
            # Show breakdown by source
            breakdown_query = session.execute(text(f"""
                SELECT source, COUNT(*) as count,
                    MIN(created_at) as oldest
                FROM candidate_links
                WHERE status = 'article'
                AND created_at < NOW() - INTERVAL '{days_threshold} days'
                GROUP BY source
                ORDER BY count DESC
            """)).fetchall()
            
            for source, count, oldest in breakdown_query:
                now = session.execute(text("SELECT NOW()")).scalar()
                age_days = (now - oldest).days
                print(f"  {source}: {count} (oldest: {age_days}d)")
            
            print()
            
            if dry_run:
                print("⏭️  Dry run mode - no changes made")
                return 0
            
            # Mark as paused
            session.execute(text(f"""
                UPDATE candidate_links
                SET status = 'paused'
                WHERE status = 'article'
                AND created_at < NOW() - INTERVAL '{days_threshold} days'
            """))
            
            session.commit()
            
            expired_count = len(expired)
            print(f"✅ Marked {expired_count} candidates as paused")
            print()
            
            # Show final status
            paused_count = session.execute(text("""
                SELECT COUNT(*) FROM candidate_links WHERE status = 'paused'
            """)).scalar()
            article_count = session.execute(text("""
                SELECT COUNT(*) FROM candidate_links WHERE status = 'article'
            """)).scalar()
            
            print("Pipeline status after cleanup:")
            print(f"  paused: {paused_count}")
            print(f"  article (ready for extraction): {article_count}")
            print()
            
            return 0
            
    except Exception as e:
        logger.exception("Cleanup candidates failed: %s", e)
        print(f"❌ Error: {e}")
        return 1
