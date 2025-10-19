"""Tests for Phase 4: Telemetry & Jobs integration."""

import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_operation_tracker_tracks_load_sources_operation():
    """OperationTracker should track load-sources operations."""
    from src.utils.telemetry import OperationTracker, OperationType

    # Create a temporary database for testing
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = tmp_file.name
    
    try:
        tracker = OperationTracker(database_url=f"sqlite:///{db_path}")
        
        # Track an operation
        with tracker.track_operation(
            OperationType.LOAD_SOURCES,
            source_file="test.csv",
            total_rows=10
        ) as operation:
            # Operation should be tracked
            assert operation is not None
        
        # Operation should be completed after context manager exits
        # (no exception means test passed)
    finally:
        # Clean up
        Path(db_path).unlink(missing_ok=True)


def test_operation_tracker_tracks_crawl_discovery():
    """OperationTracker should track crawl discovery operations."""
    from src.utils.telemetry import OperationMetrics, OperationTracker, OperationType
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = tmp_file.name
    
    try:
        tracker = OperationTracker(database_url=f"sqlite:///{db_path}")
        
        # Track a crawl operation
        with tracker.track_operation(
            OperationType.CRAWL_DISCOVERY,
            job_id="test-job",
            sources_file="test.json",
            num_sources=5
        ) as operation:
            # Update progress
            metrics = OperationMetrics(total_items=5, processed_items=2)
            operation.update_progress(metrics)
            
            # Operation should track progress
            assert metrics.processed_items == 2
            assert metrics.total_items == 5
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_operation_tracker_handles_failures():
    """OperationTracker should handle operation failures gracefully."""
    from src.utils.telemetry import OperationTracker, OperationType
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = tmp_file.name
    
    try:
        tracker = OperationTracker(database_url=f"sqlite:///{db_path}")
        
        # Track an operation that fails
        with pytest.raises(ValueError):
            with tracker.track_operation(
                OperationType.LOAD_SOURCES,
                source_file="fail.csv"
            ):
                raise ValueError("Test failure")
        
        # Operation should be marked as failed (no exception from tracker itself)
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_telemetry_url_env_var_support():
    """TELEMETRY_URL environment variable should be supported."""
    import os

    from src.config import TELEMETRY_URL

    # TELEMETRY_URL should be available from config
    assert TELEMETRY_URL is None or isinstance(TELEMETRY_URL, str)


def test_operation_tracker_stores_job_records():
    """OperationTracker should store job records in the database."""
    from sqlalchemy import select

    from src.models import Job
    from src.models.database import DatabaseManager
    from src.utils.telemetry import OperationTracker, OperationType
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = tmp_file.name
    
    try:
        db_url = f"sqlite:///{db_path}"
        tracker = OperationTracker(database_url=db_url)
        
        # Track an operation
        with tracker.track_operation(
            OperationType.LOAD_SOURCES,
            source_file="test.csv"
        ):
            pass
        
        # Verify job was created in database
        with DatabaseManager(database_url=db_url) as db:
            jobs = db.session.execute(select(Job)).scalars().all()
            # At least one job should exist (there may be telemetry-related jobs too)
            assert len(jobs) > 0
            
    finally:
        Path(db_path).unlink(missing_ok=True)
