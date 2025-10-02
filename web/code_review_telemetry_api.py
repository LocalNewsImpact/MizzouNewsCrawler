"""
API endpoints for code review telemetry and human feedback.

Provides human review interface for code changes that require manual approval.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import sqlite3
import json

# Use absolute path for database when running from web directory
DATABASE_URL = "sqlite:///../data/mizzou.db"


class CodeReviewItem(BaseModel):
    """Single code change item for human review."""
    review_id: str
    title: str
    description: str
    author: str
    file_path: Optional[str]
    code_diff: Optional[str]
    change_type: str  # "feature", "bugfix", "refactor", "documentation"
    priority: str  # "low", "medium", "high", "critical"
    created_at: datetime
    source_branch: Optional[str]
    target_branch: Optional[str]

    # Human feedback fields (initially null)
    human_label: Optional[str] = None  # "approved", "rejected", "needs_changes"
    human_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None


class CodeReviewFeedback(BaseModel):
    """Human feedback for a code review item."""
    review_id: str
    human_label: str  # "approved", "rejected", "needs_changes"
    human_notes: Optional[str] = None
    reviewed_by: str


class CodeReviewStats(BaseModel):
    """Summary statistics for code review telemetry."""
    total_reviews: int
    pending_review: int
    approved: int
    rejected: int
    needs_changes: int
    avg_review_time_hours: Optional[float]
    reviewers_active: int


def init_code_review_tables():
    """Initialize code review telemetry tables if they don't exist."""
    try:
        # Use absolute path to database file
        import os
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "mizzou.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Create code review telemetry table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS code_review_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            author TEXT NOT NULL,
            file_path TEXT,
            code_diff TEXT,
            change_type TEXT NOT NULL,
            priority TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source_branch TEXT,
            target_branch TEXT,
            human_label TEXT,
            human_notes TEXT,
            reviewed_by TEXT,
            reviewed_at TIMESTAMP
        )
        """)

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error initializing code review tables: {e}")
        return False


def get_pending_code_reviews(limit: int = 50) -> List[CodeReviewItem]:
    """Get code review items that need human review."""
    try:
        import os
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "mizzou.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
        SELECT * FROM code_review_telemetry
        WHERE human_label IS NULL
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
                ELSE 5
            END,
            created_at ASC
        LIMIT ?
        """, (limit,))

        rows = cur.fetchall()
        conn.close()

        items = []
        for row in rows:
            item = CodeReviewItem(
                review_id=row['review_id'],
                title=row['title'],
                description=row['description'],
                author=row['author'],
                file_path=row['file_path'],
                code_diff=row['code_diff'],
                change_type=row['change_type'],
                priority=row['priority'],
                created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.now(),
                source_branch=row['source_branch'],
                target_branch=row['target_branch'],
                human_label=row['human_label'],
                human_notes=row['human_notes'],
                reviewed_by=row['reviewed_by'],
                reviewed_at=datetime.fromisoformat(row['reviewed_at']) if row['reviewed_at'] else None
            )
            items.append(item)

        return items

    except Exception as e:
        print(f"Error fetching pending code reviews: {e}")
        return []


def submit_code_review_feedback(feedback: CodeReviewFeedback) -> bool:
    """Submit human feedback for a code review item."""
    try:
        import os
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "mizzou.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("""
        UPDATE code_review_telemetry
        SET human_label = ?, human_notes = ?, reviewed_by = ?, reviewed_at = ?
        WHERE review_id = ?
        """, (
            feedback.human_label,
            feedback.human_notes,
            feedback.reviewed_by,
            datetime.utcnow().isoformat(),
            feedback.review_id
        ))

        affected_rows = cur.rowcount
        conn.commit()
        conn.close()

        return affected_rows > 0

    except Exception as e:
        print(f"Error submitting code review feedback: {e}")
        return False


def get_code_review_stats() -> CodeReviewStats:
    """Get summary statistics for code review telemetry."""
    try:
        import os
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "mizzou.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Get basic counts
        cur.execute("SELECT COUNT(*) FROM code_review_telemetry")
        total_reviews = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM code_review_telemetry WHERE human_label IS NULL")
        pending_review = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM code_review_telemetry WHERE human_label = 'approved'")
        approved = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM code_review_telemetry WHERE human_label = 'rejected'")
        rejected = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM code_review_telemetry WHERE human_label = 'needs_changes'")
        needs_changes = cur.fetchone()[0]

        # Get average review time (in hours)
        cur.execute("""
        SELECT AVG(
            (julianday(reviewed_at) - julianday(created_at)) * 24
        ) as avg_hours
        FROM code_review_telemetry
        WHERE reviewed_at IS NOT NULL AND created_at IS NOT NULL
        """)
        avg_result = cur.fetchone()[0]
        avg_review_time_hours = round(avg_result, 2) if avg_result else None

        # Get count of active reviewers (reviewers in last 30 days)
        cur.execute("""
        SELECT COUNT(DISTINCT reviewed_by)
        FROM code_review_telemetry
        WHERE reviewed_at >= datetime('now', '-30 days')
        """)
        reviewers_active = cur.fetchone()[0]

        conn.close()

        return CodeReviewStats(
            total_reviews=total_reviews,
            pending_review=pending_review,
            approved=approved,
            rejected=rejected,
            needs_changes=needs_changes,
            avg_review_time_hours=avg_review_time_hours,
            reviewers_active=reviewers_active
        )

    except Exception as e:
        print(f"Error fetching code review stats: {e}")
        return CodeReviewStats(
            total_reviews=0,
            pending_review=0,
            approved=0,
            rejected=0,
            needs_changes=0,
            avg_review_time_hours=None,
            reviewers_active=0
        )


def add_code_review_item(item: CodeReviewItem) -> bool:
    """Add a new code review item to the database."""
    try:
        import os
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "mizzou.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("""
        INSERT OR REPLACE INTO code_review_telemetry
        (review_id, title, description, author, file_path, code_diff,
         change_type, priority, created_at, source_branch, target_branch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.review_id,
            item.title,
            item.description,
            item.author,
            item.file_path,
            item.code_diff,
            item.change_type,
            item.priority,
            item.created_at.isoformat() if item.created_at else datetime.utcnow().isoformat(),
            item.source_branch,
            item.target_branch
        ))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"Error adding code review item: {e}")
        return False