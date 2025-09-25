"""
API endpoints for URL verification telemetry and human feedback.

Provides human review interface for StorySniffer article/not-article classifications.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import sqlite3

# Use absolute path for database when running from web directory
DATABASE_URL = "sqlite:///../data/mizzou.db"


class URLVerificationItem(BaseModel):
    """Single URL verification result for human review."""
    verification_id: str
    url: str
    storysniffer_result: Optional[bool]
    verification_confidence: Optional[float]
    article_headline: Optional[str]
    article_excerpt: Optional[str]
    verification_time_ms: Optional[float]
    verified_at: datetime
    source_name: Optional[str]
    
    # Human feedback fields (initially null)
    human_label: Optional[str] = None  # "correct", "incorrect"
    human_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None


class VerificationFeedback(BaseModel):
    """Human feedback for a URL verification result."""
    verification_id: str
    human_label: str  # "correct", "incorrect"
    human_notes: Optional[str] = None
    reviewed_by: str


class VerificationTelemetryStats(BaseModel):
    """Summary statistics for verification telemetry."""
    total_verifications: int
    pending_review: int
    reviewed_correct: int
    reviewed_incorrect: int
    storysniffer_accuracy: Optional[float]
    avg_verification_time_ms: Optional[float]
    article_rate: float
    sources_represented: int


def get_db_connection():
    """Get database connection for verification telemetry data."""
    db_path = DATABASE_URL.replace('sqlite:///', '')
    return sqlite3.connect(db_path)


def get_pending_verification_reviews(limit: int = 50) -> List[URLVerificationItem]:
    """Get URL verifications that need human review."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get items without human feedback, ordered by verification time
    cursor.execute("""
        SELECT 
            v.id, v.url, v.storysniffer_result, v.verification_confidence,
            v.article_headline, v.article_excerpt, v.verification_time_ms,
            v.verified_at, v.human_label, v.human_notes, v.reviewed_by, v.reviewed_at,
            COALESCE(cl.source_name, 'Unknown') as source_name
        FROM url_verifications v
        LEFT JOIN candidate_links cl ON v.candidate_link_id = cl.id
        WHERE v.human_label IS NULL
        AND v.storysniffer_result IS NOT NULL
        ORDER BY v.verified_at DESC
        LIMIT ?
    """, (limit,))
    
    items = []
    for row in cursor.fetchall():
        item = URLVerificationItem(
            verification_id=row[0],
            url=row[1],
            storysniffer_result=row[2],
            verification_confidence=row[3],
            article_headline=row[4],
            article_excerpt=row[5],
            verification_time_ms=row[6],
            verified_at=datetime.fromisoformat(row[7]) if row[7] else datetime.now(),
            human_label=row[8],
            human_notes=row[9],
            reviewed_by=row[10],
            reviewed_at=datetime.fromisoformat(row[11]) if row[11] else None,
            source_name=row[12]
        )
        items.append(item)
    
    conn.close()
    return items


def submit_verification_feedback(feedback: VerificationFeedback) -> bool:
    """Store human feedback for a URL verification result."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE url_verifications 
            SET human_label = ?, human_notes = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
        """, (
            feedback.human_label,
            feedback.human_notes,
            feedback.reviewed_by,
            datetime.now().isoformat(),
            feedback.verification_id
        ))
        
        conn.commit()
        success = cursor.rowcount > 0
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
    
    return success


def get_verification_telemetry_stats() -> VerificationTelemetryStats:
    """Get summary statistics for verification telemetry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get overall counts and accuracy
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN human_label IS NULL THEN 1 END) as pending,
            COUNT(CASE WHEN human_label = 'correct' THEN 1 END) as correct,
            COUNT(CASE WHEN human_label = 'incorrect' THEN 1 END) as incorrect,
            AVG(verification_time_ms) as avg_time,
            COUNT(CASE WHEN storysniffer_result = 1 THEN 1 END) * 1.0 / COUNT(*) as article_rate
        FROM url_verifications
        WHERE storysniffer_result IS NOT NULL
    """)
    
    row = cursor.fetchone()
    
    # Calculate StorySniffer accuracy based on human feedback
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN 
                (storysniffer_result = 1 AND human_label = 'correct') OR
                (storysniffer_result = 0 AND human_label = 'correct')
                THEN 1 END) * 1.0 / COUNT(*) as accuracy
        FROM url_verifications
        WHERE human_label IN ('correct', 'incorrect')
    """)
    
    accuracy_row = cursor.fetchone()
    
    # Get source count
    cursor.execute("""
        SELECT COUNT(DISTINCT cl.source_name) as sources
        FROM url_verifications v
        LEFT JOIN candidate_links cl ON v.candidate_link_id = cl.id
        WHERE v.storysniffer_result IS NOT NULL
    """)
    
    source_row = cursor.fetchone()
    
    stats = VerificationTelemetryStats(
        total_verifications=row[0] or 0,
        pending_review=row[1] or 0,
        reviewed_correct=row[2] or 0,
        reviewed_incorrect=row[3] or 0,
        storysniffer_accuracy=accuracy_row[0] if accuracy_row[0] is not None else None,
        avg_verification_time_ms=round(row[4], 2) if row[4] else None,
        article_rate=round(row[5], 3) if row[5] else 0.0,
        sources_represented=source_row[0] or 0
    )
    
    conn.close()
    return stats


def get_labeled_verification_training_data(min_confidence: float = 0.0) -> List[dict]:
    """Export labeled verification data for ML training."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            v.url, v.storysniffer_result, v.verification_confidence,
            v.verification_time_ms, v.article_headline, v.article_excerpt,
            v.human_label, cl.source_name,
            LENGTH(v.url) as url_length,
            CASE WHEN v.url LIKE '%/%/%/%/%' THEN 1 ELSE 0 END as has_deep_path,
            CASE WHEN v.url LIKE '%.pdf%' OR v.url LIKE '%.doc%' OR v.url LIKE '%.jpg%' 
                 THEN 1 ELSE 0 END as is_file_url,
            CASE WHEN v.url LIKE '%calendar%' OR v.url LIKE '%event%' 
                 THEN 1 ELSE 0 END as is_event_url
        FROM url_verifications v
        LEFT JOIN candidate_links cl ON v.candidate_link_id = cl.id
        WHERE v.human_label IS NOT NULL 
        AND v.storysniffer_result IS NOT NULL
        AND COALESCE(v.verification_confidence, 0) >= ?
        ORDER BY v.verified_at DESC
    """, (min_confidence,))
    
    columns = [
        'url', 'storysniffer_result', 'verification_confidence',
        'verification_time_ms', 'article_headline', 'article_excerpt',
        'human_label', 'source_name', 'url_length', 'has_deep_path',
        'is_file_url', 'is_event_url'
    ]
    
    training_data = []
    for row in cursor.fetchall():
        item = dict(zip(columns, row))
        # Add engineered features
        item['url_segments'] = len(item['url'].split('/')) - 3  # Subtract protocol and domain
        item['has_headline'] = 1 if item['article_headline'] else 0
        item['headline_length'] = len(item['article_headline'] or '')
        item['excerpt_length'] = len(item['article_excerpt'] or '')
        training_data.append(item)
    
    conn.close()
    return training_data


def enhance_verification_with_content(verification_id: str, headline: str, excerpt: str) -> bool:
    """Add article content to verification record for human review."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE url_verifications 
            SET article_headline = ?, article_excerpt = ?
            WHERE id = ?
        """, (headline, excerpt, verification_id))
        
        conn.commit()
        success = cursor.rowcount > 0
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
    
    return success