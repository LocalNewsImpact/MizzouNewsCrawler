#!/usr/bin/env python3
"""
Patch script to add record_extraction_outcome method to telemetry.py.

This script adds the extraction outcome recording functionality to the
TelemetryReporter class, following the same pattern as discovery outcomes.

Usage:
    python scripts/patch_telemetry_extraction.py
"""

import re
from pathlib import Path


def patch_telemetry_file():
    """Add record_extraction_outcome method to telemetry.py."""

    telemetry_path = Path(__file__).parent.parent / "src" / "utils" / "telemetry.py"

    if not telemetry_path.exists():
        print(f"Error: telemetry.py not found at {telemetry_path}")
        return 1

    # Read the current file
    with open(telemetry_path) as f:
        content = f.read()

    # Function to add after record_discovery_outcome
    extraction_function = '''
    def record_extraction_outcome(self, operation_id: str, article_id: int, 
                                  url: str, extraction_result):
        """Record detailed extraction outcome for reporting and analysis."""
        from src.utils.extraction_outcomes import ExtractionResult
        
        if not isinstance(extraction_result, ExtractionResult):
            self.logger.warning(f"Expected ExtractionResult, got {type(extraction_result)}")
            return

        try:
            # Convert ExtractionResult to database record
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

            # Insert extraction outcome record
            insert_query = text("""
                INSERT INTO extraction_outcomes (
                    operation_id, article_id, url, outcome, extraction_time_ms,
                    start_time, end_time, http_status_code, response_size_bytes,
                    has_title, has_content, has_author, has_publish_date,
                    content_length, title_length, author_count, content_quality_score,
                    error_message, error_type, is_success, is_content_success,
                    is_technical_failure, is_bot_protection, metadata
                ) VALUES (
                    :operation_id, :article_id, :url, :outcome, :extraction_time_ms,
                    :start_time, :end_time, :http_status_code, :response_size_bytes,
                    :has_title, :has_content, :has_author, :has_publish_date,
                    :content_length, :title_length, :author_count, :content_quality_score,
                    :error_message, :error_type, :is_success, :is_content_success,
                    :is_technical_failure, :is_bot_protection, :metadata
                )
            """)

            with self.db_engine.connect() as conn:
                conn.execute(insert_query, outcome_data)
                
                # Update articles table status based on extraction result
                if extraction_result.is_success:
                    article_status = 'extracted'
                else:
                    article_status = 'error'
                
                update_article_query = text("""
                    UPDATE articles 
                    SET status = :status,
                        processed_at = datetime('now'),
                        error_message = :error_message
                    WHERE id = :article_id
                """)
                
                conn.execute(update_article_query, {
                    "article_id": article_id,
                    "status": article_status,
                    "error_message": extraction_result.error_message
                })
                
                conn.commit()

            self.logger.debug(f"Recorded extraction outcome: {extraction_result.outcome.value} for article {article_id}")

        except Exception as e:
            self.logger.error(f"Failed to record extraction outcome: {e}")
'''

    # Find the end of record_discovery_outcome method
    pattern = r"(\n\s+def record_discovery_outcome\(.*?\n(?:\s{4,}.*\n)*)"
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print("Error: Could not find record_discovery_outcome method")
        return 1

    # Insert the new function after record_discovery_outcome
    insertion_point = match.end()
    new_content = (
        content[:insertion_point] + extraction_function + content[insertion_point:]
    )

    # Write the patched file
    with open(telemetry_path, "w") as f:
        f.write(new_content)

    print("✓ Successfully added record_extraction_outcome method to telemetry.py")
    return 0


if __name__ == "__main__":
    exit(patch_telemetry_file())
