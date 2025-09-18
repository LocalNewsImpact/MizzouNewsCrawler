"""
Telemetry and tracking system for MizzouNewsCrawler operations.

This module provides comprehensive tracking and telemetry for all crawler
operations, designed to integrate with the existing React frontend and backend
API.

Features:
- Real-time operation tracking
- Progress reporting with metrics
- Error tracking and alerting
- API endpoint integration
- WebSocket support for live updates
- Structured logging with correlation IDs
"""
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass, asdict
import logging
import threading
from contextlib import contextmanager

import requests
from sqlalchemy import text


class OperationType(str, Enum):
    """Types of crawler operations."""
    LOAD_SOURCES = "load_sources"
    CRAWL_DISCOVERY = "crawl_discovery"
    CONTENT_EXTRACTION = "content_extraction"
    ML_ANALYSIS = "ml_analysis"
    DATA_EXPORT = "data_export"


class OperationStatus(str, Enum):
    """Status of operations."""
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OperationMetrics:
    """Metrics for tracking operation progress."""
    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    success_rate: float = 0.0
    items_per_second: float = 0.0
    estimated_completion: Optional[datetime] = None
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0


@dataclass
class OperationEvent:
    """Single operation event for tracking."""
    event_id: str
    operation_id: str
    operation_type: OperationType
    status: OperationStatus
    timestamp: datetime
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = None
    metrics: Optional[OperationMetrics] = None
    error_details: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class TelemetryReporter:
    """Handles sending telemetry data to external APIs."""
    
    def __init__(self, api_base_url: Optional[str] = None,
                 api_key: Optional[str] = None):
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)
        
        # Set up headers for API requests
        if api_key:
            self.session.headers.update({
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            })
    
    def send_operation_event(self, event: OperationEvent) -> bool:
        """Send operation event to external API."""
        if not self.api_base_url:
            return False
        
        try:
            url = f"{self.api_base_url}/api/v1/telemetry/operations"
            payload = self._serialize_event(event)
            
            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            self.logger.debug(f"Sent telemetry event {event.event_id} to API")
            return True
            
        except Exception as e:
            self.logger.warning(f"Failed to send telemetry event: {e}")
            return False
    
    def send_progress_update(self, operation_id: str, metrics: OperationMetrics) -> bool:
        """Send progress update to external API."""
        if not self.api_base_url:
            return False
        
        try:
            url = f"{self.api_base_url}/api/v1/telemetry/progress/{operation_id}"
            payload = asdict(metrics)
            payload['timestamp'] = datetime.now(timezone.utc).isoformat()
            
            response = self.session.put(url, json=payload, timeout=10)
            response.raise_for_status()
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Failed to send progress update: {e}")
            return False
    
    def _serialize_event(self, event: OperationEvent) -> Dict[str, Any]:
        """Serialize event for API transmission."""
        data = asdict(event)
        data['timestamp'] = event.timestamp.isoformat()
        
        if event.metrics:
            data['metrics'] = asdict(event.metrics)
            if event.metrics.estimated_completion:
                data['metrics']['estimated_completion'] = event.metrics.estimated_completion.isoformat()
        
        return data


class OperationTracker:
    """Main tracking system for crawler operations."""
    
    def __init__(self, db_engine, telemetry_reporter: Optional[TelemetryReporter] = None):
        self.db_engine = db_engine
        self.telemetry_reporter = telemetry_reporter
        self.logger = logging.getLogger(__name__)
        self.active_operations: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        # Ensure jobs table exists
        self._create_jobs_table()
    
    def _create_jobs_table(self):
        """Create jobs table if it doesn't exist."""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP NULL,
            user_id TEXT,
            session_id TEXT,
            parameters TEXT,
            metrics TEXT,
            error_details TEXT,
            result_summary TEXT
        )
        """
        
        with self.db_engine.connect() as conn:
            conn.execute(text(create_table_sql))
            conn.commit()
    
    @contextmanager
    def track_operation(self, operation_type: OperationType, **kwargs):
        """Context manager for tracking operations."""
        operation_id = str(uuid.uuid4())
        
        try:
            # Start tracking
            self.start_operation(operation_id, operation_type, **kwargs)
            
            # Yield tracker for updates
            yield OperationContext(self, operation_id)
            
            # Mark as completed
            self.complete_operation(operation_id)
            
        except Exception as e:
            # Mark as failed
            self.fail_operation(operation_id, str(e))
            raise
    
    def start_operation(self, operation_id: str, operation_type: OperationType, **kwargs):
        """Start tracking an operation."""
        with self._lock:
            self.active_operations[operation_id] = {
                'operation_type': operation_type,
                'status': OperationStatus.STARTED,
                'start_time': datetime.now(timezone.utc),
                'metrics': OperationMetrics(),
                **kwargs
            }
        
        # Create database record
        self._update_job_record(operation_id, OperationStatus.STARTED, **kwargs)
        
        # Send telemetry event
        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=operation_type,
            status=OperationStatus.STARTED,
            timestamp=datetime.now(timezone.utc),
            message=f"Started {operation_type.value} operation",
            details=kwargs
        )
        self._send_event(event)
    
    def update_progress(self, operation_id: str, metrics: OperationMetrics):
        """Update operation progress."""
        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id]['metrics'] = metrics
                self.active_operations[operation_id]['status'] = OperationStatus.IN_PROGRESS
        
        # Update database
        self._update_job_record(operation_id, OperationStatus.IN_PROGRESS, metrics=metrics)
        
        # Send progress update
        if self.telemetry_reporter:
            self.telemetry_reporter.send_progress_update(operation_id, metrics)
    
    def complete_operation(self, operation_id: str, result_summary: Optional[Dict[str, Any]] = None):
        """Mark operation as completed."""
        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id]['status'] = OperationStatus.COMPLETED
                self.active_operations[operation_id]['end_time'] = datetime.now(timezone.utc)
        
        # Update database
        self._update_job_record(
            operation_id, 
            OperationStatus.COMPLETED, 
            result_summary=result_summary
        )
        
        # Send completion event
        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=self.active_operations.get(operation_id, {}).get('operation_type'),
            status=OperationStatus.COMPLETED,
            timestamp=datetime.now(timezone.utc),
            message=f"Operation completed successfully",
            details=result_summary or {}
        )
        self._send_event(event)
    
    def fail_operation(self, operation_id: str, error_message: str, error_details: Optional[Dict[str, Any]] = None):
        """Mark operation as failed."""
        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id]['status'] = OperationStatus.FAILED
                self.active_operations[operation_id]['end_time'] = datetime.now(timezone.utc)
        
        # Update database
        self._update_job_record(
            operation_id, 
            OperationStatus.FAILED, 
            error_details={'message': error_message, **(error_details or {})}
        )
        
        # Send failure event
        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=self.active_operations.get(operation_id, {}).get('operation_type'),
            status=OperationStatus.FAILED,
            timestamp=datetime.now(timezone.utc),
            message=f"Operation failed: {error_message}",
            error_details={'message': error_message, **(error_details or {})}
        )
        self._send_event(event)
    
    def get_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of an operation."""
        with self._lock:
            return self.active_operations.get(operation_id)
    
    def list_active_operations(self) -> List[Dict[str, Any]]:
        """List all active operations."""
        with self._lock:
            return [
                {'operation_id': op_id, **details}
                for op_id, details in self.active_operations.items()
                if details['status'] in [OperationStatus.STARTED, OperationStatus.IN_PROGRESS]
            ]
    
    def _update_job_record(self, operation_id: str, status: OperationStatus, **kwargs):
        """Update job record in database."""
        try:
            # Check if record exists
            with self.db_engine.connect() as conn:
                result = conn.execute(
                    text("SELECT id FROM jobs WHERE id = :id"), 
                    {'id': operation_id}
                )
                exists = result.fetchone() is not None
            
            if not exists:
                # Insert new record
                insert_sql = """
                INSERT INTO jobs (id, operation_type, status, user_id, session_id, parameters)
                VALUES (:id, :operation_type, :status, :user_id, :session_id, :parameters)
                """
                with self.db_engine.connect() as conn:
                    conn.execute(text(insert_sql), {
                        'id': operation_id,
                        'operation_type': kwargs.get('operation_type', ''),
                        'status': status.value,
                        'user_id': kwargs.get('user_id'),
                        'session_id': kwargs.get('session_id'),
                        'parameters': json.dumps(kwargs.get('parameters', {}))
                    })
                    conn.commit()
            else:
                # Update existing record
                update_fields = ['status = :status', 'updated_at = CURRENT_TIMESTAMP']
                params = {'id': operation_id, 'status': status.value}
                
                if status == OperationStatus.COMPLETED:
                    update_fields.append('completed_at = CURRENT_TIMESTAMP')
                
                if 'metrics' in kwargs and kwargs['metrics']:
                    update_fields.append('metrics = :metrics')
                    params['metrics'] = json.dumps(asdict(kwargs['metrics']))
                
                if 'error_details' in kwargs:
                    update_fields.append('error_details = :error_details')
                    params['error_details'] = json.dumps(kwargs['error_details'])
                
                if 'result_summary' in kwargs:
                    update_fields.append('result_summary = :result_summary')
                    params['result_summary'] = json.dumps(kwargs['result_summary'])
                
                update_sql = f"UPDATE jobs SET {', '.join(update_fields)} WHERE id = :id"
                
                with self.db_engine.connect() as conn:
                    conn.execute(text(update_sql), params)
                    conn.commit()
        
        except Exception as e:
            self.logger.error(f"Failed to update job record: {e}")
    
    def _send_event(self, event: OperationEvent):
        """Send event to telemetry system."""
        if self.telemetry_reporter:
            self.telemetry_reporter.send_operation_event(event)


class OperationContext:
    """Context object for operation tracking."""
    
    def __init__(self, tracker: OperationTracker, operation_id: str):
        self.tracker = tracker
        self.operation_id = operation_id
        self.start_time = time.time()
        self.last_update = time.time()
    
    def update_progress(self, processed: int, total: int, message: str = ""):
        """Update operation progress."""
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        # Calculate metrics
        success_rate = (processed / total * 100) if total > 0 else 0
        items_per_second = processed / elapsed if elapsed > 0 else 0
        
        # Estimate completion time
        estimated_completion = None
        if items_per_second > 0 and total > processed:
            remaining_items = total - processed
            remaining_seconds = remaining_items / items_per_second
            estimated_completion = datetime.now(timezone.utc).timestamp() + remaining_seconds
            estimated_completion = datetime.fromtimestamp(estimated_completion, timezone.utc)
        
        metrics = OperationMetrics(
            total_items=total,
            processed_items=processed,
            success_rate=success_rate,
            items_per_second=items_per_second,
            estimated_completion=estimated_completion
        )
        
        self.tracker.update_progress(self.operation_id, metrics)
        self.last_update = current_time
        
        if message:
            self.tracker.logger.info(f"Operation {self.operation_id}: {message}")
    
    def log_message(self, message: str, level: str = "info"):
        """Log a message for this operation."""
        logger = self.tracker.logger
        getattr(logger, level)(f"Operation {self.operation_id}: {message}")


def create_telemetry_system(db_engine, api_base_url: Optional[str] = None, api_key: Optional[str] = None) -> OperationTracker:
    """Factory function to create telemetry system."""
    reporter = None
    if api_base_url:
        reporter = TelemetryReporter(api_base_url, api_key)
    
    return OperationTracker(db_engine, reporter)