"""Test extraction telemetry proxy_status column accepts string values.

This test validates the fix for Issue #123 where proxy_status column was
incorrectly created as Integer instead of String, causing PostgreSQL insertion
failures and SQLite fallback.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from src.models.telemetry_orm import Base, ExtractionTelemetryV2


@pytest.fixture
def sqlite_engine(tmp_path):
    """Create a SQLite engine for testing."""
    db_path = tmp_path / "test_proxy_status.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(sqlite_engine):
    """Create a database session."""
    session = Session(sqlite_engine)
    yield session
    session.close()


class TestProxyStatusColumnType:
    """Test that proxy_status column accepts string values."""

    def test_proxy_status_accepts_string_values(self, db_session):
        """Test that proxy_status column can store string values like 'success', 'failed', etc."""
        now = datetime.utcnow()
        
        # Test all expected string values for proxy_status
        test_cases = [
            ("success", "Proxy request succeeded"),
            ("failed", "Proxy request failed"),
            ("bypassed", "Proxy was bypassed"),
            ("disabled", "Proxy was disabled"),
        ]
        
        for idx, (status, description) in enumerate(test_cases):
            telemetry = ExtractionTelemetryV2(
                operation_id=f"op-proxy-{idx}",
                article_id=f"article-{idx}",
                url=f"https://example.com/article-{idx}",
                publisher="Test Publisher",
                host="example.com",
                start_time=now,
                end_time=now,
                total_duration_ms=100.0,
                # Proxy fields
                proxy_used=1,  # Boolean represented as Integer
                proxy_url="http://proxy.example.com:8080",
                proxy_authenticated=1,
                proxy_status=status,  # String value - this is what we're testing
                is_success=True,
                created_at=now,
            )
            
            db_session.add(telemetry)
        
        db_session.commit()
        
        # Query back and verify
        results = db_session.query(ExtractionTelemetryV2).all()
        assert len(results) == 4
        
        for idx, (expected_status, _) in enumerate(test_cases):
            result = db_session.query(ExtractionTelemetryV2).filter_by(
                operation_id=f"op-proxy-{idx}"
            ).first()
            
            assert result is not None, f"Record {idx} not found"
            assert result.proxy_status == expected_status, \
                f"proxy_status mismatch for record {idx}: expected '{expected_status}', got '{result.proxy_status}'"
            assert result.proxy_used == 1
            assert result.proxy_authenticated == 1

    def test_proxy_status_with_error_message(self, db_session):
        """Test proxy_status='failed' with proxy_error message."""
        now = datetime.utcnow()
        
        telemetry = ExtractionTelemetryV2(
            operation_id="op-proxy-error",
            article_id="article-error",
            url="https://example.com/error",
            publisher="Test Publisher",
            host="example.com",
            start_time=now,
            end_time=now,
            total_duration_ms=200.0,
            proxy_used=1,
            proxy_url="http://proxy.example.com:8080",
            proxy_authenticated=1,
            proxy_status="failed",  # String value
            proxy_error="Connection timeout after 30 seconds",
            is_success=False,
            error_message="Failed to extract content",
            created_at=now,
        )
        
        db_session.add(telemetry)
        db_session.commit()
        
        result = db_session.query(ExtractionTelemetryV2).filter_by(
            operation_id="op-proxy-error"
        ).first()
        
        assert result.proxy_status == "failed"
        assert result.proxy_error == "Connection timeout after 30 seconds"
        assert result.is_success is False

    def test_proxy_status_nullable(self, db_session):
        """Test that proxy_status can be NULL when proxy is not used."""
        now = datetime.utcnow()
        
        telemetry = ExtractionTelemetryV2(
            operation_id="op-no-proxy",
            article_id="article-direct",
            url="https://example.com/direct",
            publisher="Test Publisher",
            host="example.com",
            start_time=now,
            end_time=now,
            total_duration_ms=50.0,
            proxy_used=0,  # No proxy used
            proxy_status=None,  # Should be NULL
            is_success=True,
            created_at=now,
        )
        
        db_session.add(telemetry)
        db_session.commit()
        
        result = db_session.query(ExtractionTelemetryV2).filter_by(
            operation_id="op-no-proxy"
        ).first()
        
        assert result.proxy_used == 0
        assert result.proxy_status is None

    def test_column_type_in_schema(self, sqlite_engine):
        """Verify the proxy_status column is defined as String in the schema."""
        inspector = inspect(sqlite_engine)
        columns = inspector.get_columns('extraction_telemetry_v2')
        
        proxy_status_col = next(
            (col for col in columns if col['name'] == 'proxy_status'),
            None
        )
        
        assert proxy_status_col is not None, "proxy_status column not found in schema"
        
        # SQLite doesn't strictly enforce types, but we can check the type name
        # The column type should be compatible with String/VARCHAR
        col_type_str = str(proxy_status_col['type']).upper()
        
        # Accept VARCHAR, TEXT, or similar string types
        # SQLite is flexible, so we're mainly ensuring it's not INTEGER or NUMERIC
        assert 'INT' not in col_type_str or 'INTEGER' != col_type_str, \
            f"proxy_status column has numeric type: {col_type_str}"

    def test_bulk_insert_with_mixed_proxy_statuses(self, db_session):
        """Test bulk insert of records with various proxy_status values."""
        now = datetime.utcnow()
        
        records = [
            {
                "operation_id": f"op-bulk-{i}",
                "article_id": f"article-{i}",
                "url": f"https://example.com/article-{i}",
                "publisher": "Bulk Publisher",
                "host": "example.com",
                "start_time": now,
                "end_time": now,
                "total_duration_ms": 100.0 + i,
                "proxy_used": 1 if i % 2 == 0 else 0,
                "proxy_status": ["success", "failed", "bypassed", None][i % 4],
                "is_success": True,
                "created_at": now,
            }
            for i in range(8)
        ]
        
        db_session.bulk_insert_mappings(ExtractionTelemetryV2, records)
        db_session.commit()
        
        # Verify all records were inserted
        count = db_session.query(ExtractionTelemetryV2).count()
        assert count == 8
        
        # Verify specific proxy_status values
        success_records = db_session.query(ExtractionTelemetryV2).filter_by(
            proxy_status="success"
        ).count()
        assert success_records == 2  # Records 0 and 4
        
        failed_records = db_session.query(ExtractionTelemetryV2).filter_by(
            proxy_status="failed"
        ).count()
        assert failed_records == 2  # Records 1 and 5
        
        bypassed_records = db_session.query(ExtractionTelemetryV2).filter_by(
            proxy_status="bypassed"
        ).count()
        assert bypassed_records == 2  # Records 2 and 6
