"""
API endpoints for byline cleaning telemetry human feedback.

Extends the existing reviewer_api.py with telemetry review capabilities.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import sqlite3
from src.config import DATABASE_URL


class BylineTelemetryItem(BaseModel):
    """Single byline cleaning result for human review."""
    telemetry_id: str
    raw_byline: str
    final_authors_display: str
    confidence_score: float
    source_name: str
    processing_time_ms: float
    extraction_timestamp: datetime
    has_wire_service: bool
    source_name_removed: bool
    cleaning_method: str
    
    # Human feedback fields (initially null)
    human_label: Optional[str] = None  # "correct", "incorrect", "partial"
    human_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None


class BylineFeedback(BaseModel):
    """Human feedback for a byline cleaning result."""
    telemetry_id: str
    human_label: str  # "correct", "incorrect", "partial"
    human_notes: Optional[str] = None
    reviewed_by: str


class BylineTelemetryStats(BaseModel):
    """Summary statistics for byline telemetry."""
    total_extractions: int
    pending_review: int
    reviewed_correct: int
    reviewed_incorrect: int
    reviewed_partial: int
    avg_confidence_score: float
    sources_represented: int


def get_db_connection():
    """Get database connection for telemetry data."""
    db_path = DATABASE_URL.replace('sqlite:///', '')
    return sqlite3.connect(db_path)


def get_pending_byline_reviews(limit: int = 50) -> List[BylineTelemetryItem]:
    """Get byline extractions that need human review."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get items without human feedback, ordered by extraction time
    cursor.execute("""
        SELECT 
            id, raw_byline, final_authors_display, confidence_score,
            source_name, processing_time_ms, extraction_timestamp,
            has_wire_service, source_name_removed, cleaning_method,
            human_label, human_notes, reviewed_by, reviewed_at
        FROM byline_cleaning_telemetry 
        WHERE human_label IS NULL
        ORDER BY extraction_timestamp DESC
        LIMIT ?
    """, (limit,))
    
    items = []
    for row in cursor.fetchall():
        item = BylineTelemetryItem(
            telemetry_id=row[0],
            raw_byline=row[1],
            final_authors_display=row[2],
            confidence_score=row[3],
            source_name=row[4] or "Unknown",
            processing_time_ms=row[5],
            extraction_timestamp=datetime.fromisoformat(row[6]),
            has_wire_service=bool(row[7]),
            source_name_removed=bool(row[8]),
            cleaning_method=row[9],
            human_label=row[10],
            human_notes=row[11],
            reviewed_by=row[12],
            reviewed_at=datetime.fromisoformat(row[13]) if row[13] else None
        )
        items.append(item)
    
    conn.close()
    return items


def submit_byline_feedback(feedback: BylineFeedback) -> bool:
    """Store human feedback for a byline cleaning result."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE byline_cleaning_telemetry 
            SET human_label = ?, human_notes = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
        """, (
            feedback.human_label,
            feedback.human_notes,
            feedback.reviewed_by,
            datetime.now().isoformat(),
            feedback.telemetry_id
        ))
        
        conn.commit()
        success = cursor.rowcount > 0
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
    
    return success


def get_byline_telemetry_stats() -> BylineTelemetryStats:
    """Get summary statistics for byline telemetry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get overall counts
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN human_label IS NULL THEN 1 END) as pending,
            COUNT(CASE WHEN human_label = 'correct' THEN 1 END) as correct,
            COUNT(CASE WHEN human_label = 'incorrect' THEN 1 END) as incorrect,
            COUNT(CASE WHEN human_label = 'partial' THEN 1 END) as partial,
            AVG(confidence_score) as avg_confidence,
            COUNT(DISTINCT source_name) as sources
        FROM byline_cleaning_telemetry
    """)
    
    row = cursor.fetchone()
    
    stats = BylineTelemetryStats(
        total_extractions=row[0],
        pending_review=row[1],
        reviewed_correct=row[2],
        reviewed_incorrect=row[3],
        reviewed_partial=row[4],
        avg_confidence_score=round(row[5] or 0, 3),
        sources_represented=row[6]
    )
    
    conn.close()
    return stats


def get_labeled_training_data(min_confidence: float = 0.0) -> List[dict]:
    """Export labeled data for ML training."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            raw_byline, final_authors_display, confidence_score,
            source_name, processing_time_ms, has_wire_service,
            source_name_removed, duplicates_removed_count,
            human_label, cleaning_method,
            raw_byline_length, raw_byline_words, final_authors_count
        FROM byline_cleaning_telemetry 
        WHERE human_label IS NOT NULL 
        AND confidence_score >= ?
        ORDER BY extraction_timestamp DESC
    """, (min_confidence,))
    
    columns = [
        'raw_byline', 'final_authors_display', 'confidence_score',
        'source_name', 'processing_time_ms', 'has_wire_service',
        'source_name_removed', 'duplicates_removed_count',
        'human_label', 'cleaning_method',
        'raw_byline_length', 'raw_byline_words', 'final_authors_count'
    ]
    
    training_data = []
    for row in cursor.fetchall():
        item = dict(zip(columns, row))
        # Add engineered features
        item['complexity_score'] = (item['raw_byline_length'] / max(item['raw_byline_words'], 1))
        item['words_per_author'] = (item['raw_byline_words'] / max(item['final_authors_count'], 1))
        training_data.append(item)
    
    conn.close()
    return training_data