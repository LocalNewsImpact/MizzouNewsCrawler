"""Background process tracking and monitoring utilities."""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import sessionmaker

from ..models import BackgroundProcess
from ..models.database import DatabaseManager

logger = logging.getLogger(__name__)


class ProcessTracker:
    """Manages background process tracking and monitoring."""

    def __init__(self, database_url: str = "sqlite:///data/mizzou.db"):
        self.db = DatabaseManager(database_url)
        self.Session = sessionmaker(bind=self.db.engine)

    def register_process(
        self,
        process_type: str,
        command: str,
        pid: Optional[int] = None,
        dataset_id: Optional[str] = None,
        source_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        parent_process_id: Optional[str] = None,
    ) -> BackgroundProcess:
        """Register a new background process."""
        with self.Session() as session:
            process = BackgroundProcess(
                process_type=process_type,
                command=command,
                pid=pid or os.getpid(),
                dataset_id=dataset_id,
                source_id=source_id,
                process_metadata=metadata,
                parent_process_id=parent_process_id,
                status="started",
            )
            session.add(process)
            session.commit()
            session.refresh(process)

            logger.info(
                f"Registered {process_type} process {process.id} (PID: {process.pid})"
            )
            return process

    def update_progress(
        self,
        process_id: str,
        current: int,
        message: Optional[str] = None,
        total: Optional[int] = None,
        status: Optional[str] = None,
    ):
        """Update process progress."""
        with self.Session() as session:
            process = session.get(BackgroundProcess, process_id)
            if process:
                process.update_progress(current, message, total)
                if status:
                    process.status = status
                session.commit()
                logger.debug(
                    f"Updated process {process_id}: {current}/{total or '?'} - {message}"
                )

    def complete_process(
        self,
        process_id: str,
        status: str = "completed",
        result_summary: Optional[Dict] = None,
        error_message: Optional[str] = None,
    ):
        """Mark process as completed."""
        with self.Session() as session:
            process = session.get(BackgroundProcess, process_id)
            if process:
                process.status = status
                process.completed_at = datetime.utcnow()
                if result_summary:
                    process.result_summary = result_summary
                if error_message:
                    process.error_message = error_message
                session.commit()
                logger.info(f"Process {process_id} completed with status: {status}")

    def get_active_processes(self) -> List[BackgroundProcess]:
        """Get all active (running) processes."""
        with self.Session() as session:
            processes = (
                session.query(BackgroundProcess)
                .filter(BackgroundProcess.status.in_(["started", "running"]))
                .all()
            )
            return [p for p in processes]  # Detach from session

    def get_process_by_id(self, process_id: str) -> Optional[BackgroundProcess]:
        """Get a specific process by ID."""
        with self.Session() as session:
            process = session.get(BackgroundProcess, process_id)
            if process:
                # Detach from session to avoid lazy loading issues
                session.expunge(process)
            return process

    def get_processes_by_type(self, process_type: str) -> List[BackgroundProcess]:
        """Get all processes of a specific type."""
        with self.Session() as session:
            processes = (
                session.query(BackgroundProcess)
                .filter(BackgroundProcess.process_type == process_type)
                .order_by(BackgroundProcess.started_at.desc())
                .all()
            )
            return [p for p in processes]  # Detach from session

    def cleanup_stale_processes(self, max_age_hours: int = 24):
        """Clean up old completed processes."""
        with self.Session() as session:
            cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
            deleted = (
                session.query(BackgroundProcess)
                .filter(
                    BackgroundProcess.status.in_(["completed", "failed", "cancelled"]),
                    BackgroundProcess.completed_at < cutoff,
                )
                .delete()
            )
            session.commit()
            logger.info(f"Cleaned up {deleted} stale processes")
            return deleted


# Global tracker instance
_tracker = None


def get_tracker() -> ProcessTracker:
    """Get the global process tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = ProcessTracker()
    return _tracker


class ProcessContext:
    """Context manager for tracking a background process."""

    def __init__(
        self,
        process_type: str,
        command: str,
        dataset_id: Optional[str] = None,
        source_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        self.tracker = get_tracker()
        self.process_type = process_type
        self.command = command
        self.dataset_id = dataset_id
        self.source_id = source_id
        self.metadata = metadata
        self.process = None

    def __enter__(self) -> BackgroundProcess:
        """Start process tracking."""
        self.process = self.tracker.register_process(
            self.process_type,
            self.command,
            dataset_id=self.dataset_id,
            source_id=self.source_id,
            metadata=self.metadata,
        )
        return self.process

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Complete process tracking."""
        if self.process:
            if exc_type is None:
                self.tracker.complete_process(self.process.id, "completed")
            else:
                error_msg = str(exc_val) if exc_val else "Unknown error"
                self.tracker.complete_process(
                    self.process.id, "failed", error_message=error_msg
                )


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds // 60:.0f}m {seconds % 60:.0f}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:.0f}h {minutes:.0f}m"


def format_progress(process: BackgroundProcess) -> str:
    """Format progress information for display."""
    if process.progress_total:
        pct = process.progress_percentage or 0
        current = process.progress_current
        total = process.progress_total
        return f"{current}/{total} ({pct:.1f}%)"
    else:
        return f"{process.progress_current} items"
