"""
Enhanced extraction telemetry system for comprehensive performance tracking.

This module provides detailed tracking of extraction performance across
methods, publishers, and error conditions to optimize extraction strategies.
"""

import json
import time
from datetime import datetime
from typing import Dict, Optional, Any, List
from urllib.parse import urlparse
import sqlite3
from pathlib import Path


class ExtractionMetrics:
    """Tracks detailed metrics for a single extraction operation."""

    def __init__(self, operation_id: str, article_id: str, url: str,
                 publisher: str):
        self.operation_id = operation_id
        self.article_id = article_id
        self.url = url
        self.publisher = publisher
        self.host = urlparse(url).netloc

        # Overall timing
        self.start_time = datetime.utcnow()
        self.end_time = None
        self.total_duration_ms = 0

        # HTTP metrics
        self.http_status_code = None
        self.http_error_type = None
        self.response_size_bytes = 0
        self.response_time_ms = 0

        # Method tracking
        self.methods_attempted = []
        self.method_timings = {}
        self.method_success = {}
        self.method_errors = {}
        self.successful_method = None

        # Field extraction tracking
        self.field_extraction = {}

        # Final results
        self.extracted_fields = {
            'title': False,
            'author': False,
            'content': False,
            'publish_date': False
        }
        self.content_length = 0
        self.is_success = False

        # Error tracking
        self.error_message: Optional[str] = None
        self.error_type: Optional[str] = None

    def start_method(self, method_name: str):
        """Start timing a specific extraction method."""
        self.methods_attempted.append(method_name)
        self.method_timings[method_name] = time.time()

    def end_method(self, method_name: str, success: bool,
                   error: Optional[str] = None,
                   extracted_fields: Optional[Dict[str, Any]] = None):
        """End timing and record results for a method."""
        if method_name in self.method_timings:
            duration = (time.time() - self.method_timings[method_name]) * 1000
            self.method_timings[method_name] = duration

        self.method_success[method_name] = success
        if error:
            self.method_errors[method_name] = error

        if success and not self.successful_method:
            self.successful_method = method_name

        # Track field-level success (always track, even for failed methods)
        if extracted_fields is not None:
            self.field_extraction[method_name] = {
                'title': bool(extracted_fields.get('title')),
                'author': bool(extracted_fields.get('author')),
                'content': bool(extracted_fields.get('content')),
                'publish_date': bool(extracted_fields.get('publish_date'))
            }
            
            # Extract HTTP status from metadata if available
            metadata = extracted_fields.get('metadata', {})
            http_status = metadata.get('http_status')
            if http_status and self.http_status_code is None:
                # Use first HTTP status we encounter
                self.set_http_metrics(http_status, 0, 0)

    def set_http_metrics(self, status_code: int, response_size: int,
                         response_time_ms: float):
        """Record HTTP-level metrics."""
        self.http_status_code = status_code
        self.response_size_bytes = response_size
        self.response_time_ms = response_time_ms

        # Categorize HTTP errors
        if 300 <= status_code < 400:
            self.http_error_type = '3xx_redirect'
        elif 400 <= status_code < 500:
            self.http_error_type = '4xx_client_error'
        elif status_code >= 500:
            self.http_error_type = '5xx_server_error'

    def finalize(self, final_result: Dict[str, Any]):
        """Finalize metrics with the overall extraction result."""
        self.end_time = datetime.utcnow()
        duration_sec = (self.end_time - self.start_time).total_seconds()
        self.total_duration_ms = duration_sec * 1000

        # Update final field extraction success
        if final_result:
            self.extracted_fields = {
                'title': bool(final_result.get('title')),
                'author': bool(final_result.get('author')),
                'content': bool(final_result.get('content')),
                'publish_date': bool(final_result.get('publish_date'))
            }

            self.content_length = len(final_result.get('content', ''))
            has_title = bool(final_result.get('title'))
            has_content = bool(final_result.get('content'))
            self.is_success = has_title and has_content


class ComprehensiveExtractionTelemetry:
    """Enhanced telemetry system for extraction performance analysis."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize telemetry system."""
        if db_path is None:
            data_path = Path(__file__).parent.parent.parent / "data"
            self.db_path = data_path / "mizzou.db"
        else:
            self.db_path = Path(db_path)

        self._ensure_telemetry_tables()

    def _ensure_telemetry_tables(self):
        """Create telemetry tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            # Enhanced extraction telemetry table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS extraction_telemetry_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    publisher TEXT,
                    host TEXT,

                    -- Timing metrics
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    total_duration_ms REAL,

                    -- HTTP metrics
                    http_status_code INTEGER,
                    http_error_type TEXT,
                    response_size_bytes INTEGER,
                    response_time_ms REAL,

                    -- Method tracking
                    methods_attempted TEXT,
                    successful_method TEXT,
                    method_timings TEXT,
                    method_success TEXT,
                    method_errors TEXT,

                    -- Field extraction tracking
                    field_extraction TEXT,
                    extracted_fields TEXT,

                    -- Results
                    content_length INTEGER,
                    is_success BOOLEAN,
                    error_message TEXT,
                    error_type TEXT,

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # HTTP error tracking
            conn.execute('''
                CREATE TABLE IF NOT EXISTS http_error_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    error_type TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    UNIQUE(host, status_code)
                )
            ''')

            conn.commit()

    def record_extraction(self, metrics: ExtractionMetrics):
        """Record detailed extraction metrics."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO extraction_telemetry_v2 (
                    operation_id, article_id, url, publisher, host,
                    start_time, end_time, total_duration_ms,
                    http_status_code, http_error_type,
                    response_size_bytes, response_time_ms,
                    methods_attempted, successful_method,
                    method_timings, method_success, method_errors,
                    field_extraction, extracted_fields,
                    content_length, is_success, error_message, error_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, ?, ?, ?)
            ''', (
                metrics.operation_id, metrics.article_id, metrics.url,
                metrics.publisher, metrics.host,
                metrics.start_time, metrics.end_time,
                metrics.total_duration_ms,
                metrics.http_status_code, metrics.http_error_type,
                metrics.response_size_bytes, metrics.response_time_ms,
                json.dumps(metrics.methods_attempted),
                metrics.successful_method,
                json.dumps(metrics.method_timings),
                json.dumps(metrics.method_success),
                json.dumps(metrics.method_errors),
                json.dumps(metrics.field_extraction),
                json.dumps(metrics.extracted_fields),
                metrics.content_length, metrics.is_success,
                metrics.error_message, metrics.error_type
            ))

            # Track HTTP errors
            if metrics.http_status_code and metrics.http_error_type:
                conn.execute('''
                    INSERT INTO http_error_summary
                    (host, status_code, error_type, count, last_seen)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(host, status_code) DO UPDATE SET
                        count = count + 1,
                        last_seen = ?
                ''', (metrics.host, metrics.http_status_code,
                      metrics.http_error_type, datetime.utcnow(),
                      datetime.utcnow()))

            conn.commit()

    def get_error_summary(self, days: int = 7) -> list:
        """Get HTTP error summary for the last N days."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT host, status_code, error_type, count, last_seen
                FROM http_error_summary
                WHERE last_seen >= datetime('now', '-{} days')
                ORDER BY count DESC, last_seen DESC
            '''.format(days))

            return [dict(zip([col[0] for col in cursor.description], row))
                    for row in cursor.fetchall()]

    def get_method_effectiveness(self, publisher: Optional[str] = None) -> list:
        """Get method effectiveness stats."""
        with sqlite3.connect(self.db_path) as conn:
            where_clause = ""
            params = []

            if publisher:
                where_clause = "WHERE publisher = ?"
                params.append(publisher)

            # Get individual method stats from JSON data
            cursor = conn.execute(f'''
                SELECT
                    method_timings,
                    method_success,
                    is_success
                FROM extraction_telemetry_v2
                {where_clause}
            ''', params)

            method_stats = {}
            for row in cursor.fetchall():
                timings_json, success_json, overall_success = row
                if timings_json:
                    try:
                        timings = json.loads(timings_json)
                        successes = (json.loads(success_json)
                                     if success_json else {})
                        
                        for method, timing in timings.items():
                            if method not in method_stats:
                                method_stats[method] = {
                                    'count': 0,
                                    'total_duration': 0,
                                    'success_count': 0
                                }
                            
                            method_stats[method]['count'] += 1
                            method_stats[method]['total_duration'] += timing
                            if successes.get(method, False):
                                method_stats[method]['success_count'] += 1
                    except (json.JSONDecodeError, TypeError):
                        continue

            # Convert method stats to result format
            method_results = []
            for method, stats in method_stats.items():
                avg_duration = (stats['total_duration'] / stats['count']
                                if stats['count'] > 0 else 0)
                success_rate = (stats['success_count'] / stats['count']
                                if stats['count'] > 0 else 0)
                
                method_results.append({
                    'method_type': method,
                    'successful_method': method,  # For compatibility
                    'count': stats['count'],
                    'avg_duration': avg_duration,
                    'success_rate': success_rate
                })

            # Sort by count descending
            method_results.sort(key=lambda x: x['count'], reverse=True)
            return method_results

    def get_publisher_stats(self) -> list:
        """Get per-publisher performance statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT
                    publisher,
                    host,
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successful,
                    AVG(total_duration_ms) as avg_duration_ms,
                    successful_method as most_common_method
                FROM extraction_telemetry_v2
                GROUP BY publisher, host, successful_method
                ORDER BY total_attempts DESC
            ''')

            return [dict(zip([col[0] for col in cursor.description], row))
                    for row in cursor.fetchall()]

    def get_field_extraction_stats(self, publisher: Optional[str] = None,
                                   method: Optional[str] = None) -> list:
        """Get field-level extraction success statistics by method."""
        with sqlite3.connect(self.db_path) as conn:
            where_clauses = []
            params = []

            if publisher:
                where_clauses.append("publisher = ?")
                params.append(publisher)

            where_clause = ""
            if where_clauses:
                where_clause = "WHERE " + " AND ".join(where_clauses)

            # Get field extraction data from JSON
            cursor = conn.execute(f'''
                SELECT 
                    field_extraction,
                    methods_attempted,
                    successful_method
                FROM extraction_telemetry_v2
                {where_clause}
            ''', params)

            # Process results to extract field success by method
            method_field_stats = {}
            
            for row in cursor.fetchall():
                field_extraction_json, methods_json, successful_method = row
                
                try:
                    # Parse methods attempted
                    methods = json.loads(methods_json) if methods_json else []
                    
                    # Parse field extraction data
                    field_data = (json.loads(field_extraction_json) 
                                 if field_extraction_json else {})
                    
                    # Process each method that was attempted
                    for method_name in methods:
                        # Skip if filtering by specific method
                        if method and method_name != method:
                            continue
                            
                        if method_name not in method_field_stats:
                            method_field_stats[method_name] = {
                                'count': 0,
                                'title_success': 0,
                                'author_success': 0,
                                'content_success': 0,
                                'date_success': 0
                            }
                        
                        method_field_stats[method_name]['count'] += 1
                        
                        # Check field success for this method
                        method_fields = field_data.get(method_name, {})
                        if method_fields.get('title'):
                            method_field_stats[method_name]['title_success'] += 1
                        if method_fields.get('author'):
                            method_field_stats[method_name]['author_success'] += 1
                        if method_fields.get('content'):
                            method_field_stats[method_name]['content_success'] += 1
                        if method_fields.get('publish_date'):
                            method_field_stats[method_name]['date_success'] += 1
                
                except (json.JSONDecodeError, TypeError):
                    continue

            # Convert to result format with success rates
            results = []
            for method_name, stats in method_field_stats.items():
                count = stats['count']
                results.append({
                    'method': method_name,
                    'count': count,
                    'title_success_rate': (stats['title_success'] / count 
                                          if count > 0 else 0),
                    'author_success_rate': (stats['author_success'] / count 
                                           if count > 0 else 0),
                    'content_success_rate': (stats['content_success'] / count 
                                            if count > 0 else 0),
                    'date_success_rate': (stats['date_success'] / count 
                                         if count > 0 else 0)
                })

            # Sort by count descending
            results.sort(key=lambda x: x['count'], reverse=True)
            return results
