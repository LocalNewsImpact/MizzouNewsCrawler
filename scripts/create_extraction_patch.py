#!/usr/bin/env python3
"""
Simple patch to add record_extraction_outcome to telemetry module.
"""

from pathlib import Path


def add_extraction_function():
    """Add the extraction outcome recording function."""
    
    # Define the function to add
    function_code = '''
    def record_extraction_outcome(self, operation_id: str, article_id: int, 
                                  url: str, extraction_result):
        """Record detailed extraction outcome."""
        from src.utils.extraction_outcomes import ExtractionResult
        import json
        
        if not isinstance(extraction_result, ExtractionResult):
            self.logger.warning(f"Expected ExtractionResult, got {type(extraction_result)}")
            return

        try:
            outcome_data = {
                "operation_id": operation_id,
                "article_id": article_id,
                "url": url,
                "outcome": extraction_result.outcome.value,
                "extraction_time_ms": extraction_result.extraction_time_ms,
                "start_time": extraction_result.start_time.isoformat(),
                "end_time": extraction_result.end_time.isoformat(),
                "http_status_code": extraction_result.http_status_code,
                "response_size_bytes": extraction_result.response_size_bytes,
                "has_title": 1 if extraction_result.has_title else 0,
                "has_content": 1 if extraction_result.has_content else 0,
                "has_author": 1 if extraction_result.has_author else 0,
                "has_publish_date": 1 if extraction_result.has_publish_date else 0,
                "content_length": extraction_result.content_length,
                "title_length": extraction_result.title_length,
                "author_count": extraction_result.author_count,
                "content_quality_score": extraction_result.content_quality_score,
                "error_message": extraction_result.error_message,
                "error_type": extraction_result.error_type,
                "is_success": 1 if extraction_result.is_success else 0,
                "is_content_success": 1 if extraction_result.is_content_success else 0,
                "is_technical_failure": 1 if extraction_result.is_technical_failure else 0,
                "is_bot_protection": 1 if extraction_result.is_bot_protection else 0,
                "metadata": json.dumps(extraction_result.extracted_content) if extraction_result.extracted_content else None,
            }

            insert_query = """
                INSERT INTO extraction_outcomes (
                    operation_id, article_id, url, outcome, extraction_time_ms,
                    start_time, end_time, http_status_code, response_size_bytes,
                    has_title, has_content, has_author, has_publish_date,
                    content_length, title_length, author_count, content_quality_score,
                    error_message, error_type, is_success, is_content_success,
                    is_technical_failure, is_bot_protection, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            # Use direct SQLite connection for simplicity
            import sqlite3
            db_path = Path(__file__).parent.parent / "data" / "mizzou.db"
            
            with sqlite3.connect(db_path) as conn:
                conn.execute(insert_query, tuple(outcome_data.values()))
                
                # Update articles table status
                article_status = 'extracted' if extraction_result.is_success else 'error'
                conn.execute(
                    "UPDATE articles SET status = ?, processed_at = datetime('now'), error_message = ? WHERE id = ?",
                    (article_status, extraction_result.error_message, article_id)
                )
                
                conn.commit()

            self.logger.debug(f"Recorded extraction outcome: {extraction_result.outcome.value}")

        except Exception as e:
            self.logger.error(f"Failed to record extraction outcome: {e}")
'''
    
    # Write the function to a patch file that can be imported
    patch_file = Path(__file__).parent.parent / "src" / "utils" / "extraction_telemetry_patch.py"
    
    with open(patch_file, 'w') as f:
        f.write(f'''"""
Patch module for extraction telemetry functionality.
This adds the record_extraction_outcome method to TelemetryReporter.
"""

def add_extraction_telemetry_to_class(cls):
    """Add extraction telemetry method to TelemetryReporter class."""
    {function_code}
    
    # Add the method to the class
    cls.record_extraction_outcome = record_extraction_outcome
    return cls
''')
    
    print(f"✓ Created extraction telemetry patch at {patch_file}")
    return 0


if __name__ == "__main__":
    exit(add_extraction_function())