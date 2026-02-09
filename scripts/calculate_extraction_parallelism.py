#!/usr/bin/env python3
"""Calculate optimal extraction parallelism based on backlog size.

Scaling formula:
- Target: Complete backlog in 4 hours (240 minutes)
- Processing time: 4 minutes per article
- Articles per worker: 240 / 4 = 60 articles in 4 hours
- Workers needed: backlog / 60
- Minimum: 3 workers (accounts for ongoing discovery adding to backlog)
- Maximum: 15 workers (cost/resource constraint)

The minimum of 3 workers ensures we can process the existing backlog while
simultaneously handling new articles discovered by the ongoing discovery process.
This prevents the backlog from growing faster than we can process it.

Examples:
- 50 articles: 50/60 = 0.83 → 3 workers (minimum, handles growth)
- 180 articles: 180/60 = 3 workers
- 600 articles: 600/60 = 10 workers
- 1200 articles: 1200/60 = 20 → 15 workers (maximum)

Usage:
    python scripts/calculate_extraction_parallelism.py
    # Outputs just the number: 5
"""
import sys
from src.models.database import DatabaseManager
from sqlalchemy import text

# Constants
MINUTES_PER_ARTICLE = 4
TARGET_COMPLETION_HOURS = 4
TARGET_COMPLETION_MINUTES = TARGET_COMPLETION_HOURS * 60  # 240 minutes
ARTICLES_PER_WORKER = TARGET_COMPLETION_MINUTES / MINUTES_PER_ARTICLE  # 60 articles
MIN_WORKERS = 3  # Baseline to handle backlog + ongoing discovery growth
MAX_WORKERS = 15


def get_extraction_backlog() -> int:
    """Count articles ready for extraction (verified but not extracted)."""
    db = DatabaseManager()
    with db.get_session() as session:
        result = session.execute(
            text(
                """
            SELECT COUNT(*)
            FROM candidate_links cl
            WHERE cl.status = 'article'
            AND cl.id NOT IN (
                SELECT candidate_link_id 
                FROM articles 
                WHERE candidate_link_id IS NOT NULL
            )
        """
            )
        ).scalar()
        return result or 0


def calculate_parallelism(backlog: int) -> int:
    """Calculate optimal number of extraction workers based on backlog size.
    
    Formula: workers = backlog / (240 minutes / 4 minutes per article)
             workers = backlog / 60
    
    Constraints:
    - Minimum: 3 workers (handles backlog + ongoing discovery growth)
    - Maximum: 15 workers (cost/resource constraint)
    
    The minimum ensures we maintain capacity to process both the existing
    backlog and new articles continuously added by discovery processes,
    preventing backlog accumulation.
    
    Args:
        backlog: Number of articles awaiting extraction
        
    Returns:
        Number of workers needed (between 3 and 15)
    """
    if backlog == 0:
        return MIN_WORKERS
    
    # Calculate workers needed to complete backlog in 4 hours
    workers_needed = int(backlog / ARTICLES_PER_WORKER)
    
    # Apply min/max constraints
    if workers_needed < MIN_WORKERS:
        return MIN_WORKERS
    elif workers_needed > MAX_WORKERS:
        return MAX_WORKERS
    else:
        return workers_needed


def main():
    try:
        backlog = get_extraction_backlog()
        parallelism = calculate_parallelism(backlog)

        # Output to stderr for logging, stdout for capture
        print(f"Backlog: {backlog} articles → {parallelism} workers", file=sys.stderr)
        print(parallelism)  # Just the number for easy capture
        return 0
    except Exception as e:
        print(f"Error calculating parallelism: {e}", file=sys.stderr)
        print(2)  # Default fallback
        return 1


if __name__ == "__main__":
    sys.exit(main())
