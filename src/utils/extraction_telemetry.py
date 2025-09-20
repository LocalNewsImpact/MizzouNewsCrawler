"""
Standalone extraction telemetry module for recording extraction outcomes.

This module provides telemetry recording functionality for extraction
operations without requiring modifications to the main telemetry.py file.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .extraction_outcomes import ExtractionResult


class ExtractionTelemetry:
    """Handles recording of extraction telemetry to database."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize extraction telemetry."""
        if db_path is None:
            data_path = Path(__file__).parent.parent.parent / "data"
            self.db_path = data_path / "mizzou.db"
        else:
            self.db_path = Path(db_path)
    
    def record_extraction_outcome(self, operation_id: str, article_id: int,
                                  url: str,
                                  extraction_result: ExtractionResult):
        """Record detailed extraction outcome for reporting and analysis."""
        
        if not isinstance(extraction_result, ExtractionResult):
            msg = f"Warning: Expected ExtractionResult, got {type(extraction_result)}"
            print(msg)
            return

        try:
            # Prepare data for insertion
            metadata = extraction_result.extracted_content
            metadata_json = json.dumps(metadata) if metadata else None
            
            # Prepare field quality issues as JSON strings
            title_issues = json.dumps(extraction_result.title_quality_issues or [])
            content_issues = json.dumps(extraction_result.content_quality_issues or [])
            author_issues = json.dumps(extraction_result.author_quality_issues or [])
            date_issues = json.dumps(extraction_result.publish_date_quality_issues or [])
            
            outcome_data = (
                operation_id,
                article_id,
                url,
                extraction_result.outcome.value,
                extraction_result.extraction_time_ms,
                extraction_result.start_time.isoformat(),
                extraction_result.end_time.isoformat(),
                extraction_result.http_status_code,
                extraction_result.response_size_bytes,
                1 if extraction_result.has_title else 0,
                1 if extraction_result.has_content else 0,
                1 if extraction_result.has_author else 0,
                1 if extraction_result.has_publish_date else 0,
                extraction_result.content_length,
                extraction_result.title_length,
                extraction_result.author_count,
                extraction_result.content_quality_score,
                extraction_result.error_message,
                extraction_result.error_type,
                1 if extraction_result.is_success else 0,
                1 if extraction_result.is_content_success else 0,
                1 if extraction_result.is_technical_failure else 0,
                1 if extraction_result.is_bot_protection else 0,
                metadata_json,
                # Field quality tracking
                title_issues,
                content_issues,
                author_issues,
                date_issues,
                extraction_result.overall_quality_score,
                1 if extraction_result.title_quality_issues else 0,
                1 if extraction_result.content_quality_issues else 0,
                1 if extraction_result.author_quality_issues else 0,
                1 if extraction_result.publish_date_quality_issues else 0,
            )

            insert_query = """
                INSERT INTO extraction_outcomes (
                    operation_id, article_id, url, outcome, 
                    extraction_time_ms, start_time, end_time, 
                    http_status_code, response_size_bytes,
                    has_title, has_content, has_author, has_publish_date,
                    content_length, title_length, author_count, 
                    content_quality_score, error_message, error_type, 
                    is_success, is_content_success, is_technical_failure, 
                    is_bot_protection, metadata,
                    title_quality_issues, content_quality_issues, 
                    author_quality_issues, publish_date_quality_issues,
                    overall_quality_score, title_has_issues, 
                    content_has_issues, author_has_issues, 
                    publish_date_has_issues
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            with sqlite3.connect(self.db_path) as conn:
                # Insert extraction outcome
                conn.execute(insert_query, outcome_data)
                
                # Update articles table status based on extraction result
                status = 'extracted' if extraction_result.is_success else 'error'
                update_query = """
                    UPDATE articles
                    SET status = ?,
                        processed_at = datetime('now')
                    WHERE id = ?
                """
                conn.execute(update_query, (
                    status,
                    article_id
                ))
                
                conn.commit()

            outcome_value = extraction_result.outcome.value
            print(f"Recorded extraction outcome: {outcome_value} for article {article_id}")

        except Exception as e:
            print(f"Failed to record extraction outcome: {e}")
            raise
    
    def get_extraction_stats(self, operation_id: Optional[str] = None):
        """Get extraction statistics for reporting."""
        
        base_query = """
            SELECT 
                outcome,
                COUNT(*) as count,
                AVG(extraction_time_ms) as avg_time_ms,
                AVG(content_quality_score) as avg_quality_score,
                SUM(is_success) as success_count,
                SUM(is_content_success) as content_success_count,
                SUM(is_technical_failure) as technical_failure_count,
                SUM(is_bot_protection) as bot_protection_count
            FROM extraction_outcomes
        """
        
        if operation_id:
            query = base_query + " WHERE operation_id = ? GROUP BY outcome"
            params = (operation_id,)
        else:
            query = base_query + " GROUP BY outcome"
            params = ()
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, params)
                results = [dict(row) for row in cursor.fetchall()]
                return results
        except Exception as e:
            print(f"Failed to get extraction stats: {e}")
            return []
