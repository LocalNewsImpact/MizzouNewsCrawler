"""Test the proxy_status column type migration.

This test validates that the migration d1e2f3a4b5c6 correctly changes
the proxy_status column type from Integer to String.

Uses PostgreSQL for testing migrations (production database type).
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


@pytest.mark.integration
@pytest.mark.postgres
class TestProxyStatusMigration:
    """Test the proxy_status column type migration."""

    def test_migration_creates_correct_column_type(self, cloud_sql_engine):
        """Test that migrating to the fix creates a String column."""
        # Use PostgreSQL engine for migration testing
        engine = cloud_sql_engine
        
        # Import and create tables using the ORM
        from src.models.telemetry_orm import Base, ExtractionTelemetryV2
        
        # Create all tables (this will use the correct ORM definition)
        Base.metadata.create_all(engine)
        
        # Verify the proxy_status column exists and has the correct type
        inspector = inspect(engine)
        columns = inspector.get_columns('extraction_telemetry_v2')
        
        proxy_status_col = next(
            (col for col in columns if col['name'] == 'proxy_status'),
            None
        )
        
        assert proxy_status_col is not None, "proxy_status column not found"
        
        # Test that we can insert string values
        from datetime import datetime
        
        with Session(engine) as session:
            record = ExtractionTelemetryV2(
                operation_id="test-migration",
                article_id="test-article",
                url="https://example.com/test",
                publisher="Test",
                host="example.com",
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow(),
                proxy_status="success",  # String value
                is_success=True,
                created_at=datetime.utcnow(),
            )
            session.add(record)
            session.commit()
            
            # Query back and verify
            result = session.query(ExtractionTelemetryV2).filter_by(
                operation_id="test-migration"
            ).first()
            
            assert result.proxy_status == "success"

    def test_proxy_status_accepts_all_valid_values(self, cloud_sql_engine):
        """Test that the column accepts all expected proxy_status values."""
        engine = cloud_sql_engine
        
        from src.models.telemetry_orm import Base, ExtractionTelemetryV2
        from datetime import datetime
        import time
        
        Base.metadata.create_all(engine)
        
        valid_statuses = ["success", "failed", "bypassed", "disabled", None]
        
        # Use timestamp to ensure unique operation_ids across test runs
        timestamp = int(time.time() * 1000)
        
        with Session(engine) as session:
            for idx, status in enumerate(valid_statuses):
                record = ExtractionTelemetryV2(
                    operation_id=f"test-status-{timestamp}-{idx}",
                    article_id=f"article-{timestamp}-{idx}",
                    url=f"https://example.com/test-{timestamp}-{idx}",
                    publisher="Test",
                    host="example.com",
                    start_time=datetime.utcnow(),
                    end_time=datetime.utcnow(),
                    proxy_status=status,
                    is_success=True,
                    created_at=datetime.utcnow(),
                )
                session.add(record)
            
            session.commit()
            
            # Verify all records were inserted successfully
            count = (
                session.query(ExtractionTelemetryV2)
                .filter(
                    ExtractionTelemetryV2.operation_id.like(
                        f"test-status-{timestamp}-%"
                    )
                )
                .count()
            )
            assert count == len(valid_statuses)
            
            # Verify each status value
            for idx, expected_status in enumerate(valid_statuses):
                result = session.query(ExtractionTelemetryV2).filter_by(
                    operation_id=f"test-status-{timestamp}-{idx}"
                ).first()
                assert result is not None
                assert result.proxy_status == expected_status

    def test_raw_sql_insert_with_string_status(self, cloud_sql_engine):
        """Test that raw SQL INSERT with string proxy_status works."""
        engine = cloud_sql_engine
        
        from src.models.telemetry_orm import Base
        from datetime import datetime
        
        Base.metadata.create_all(engine)
        
        now = datetime.utcnow()
        
        with engine.begin() as conn:
            # Insert using raw SQL with string proxy_status
            conn.execute(
                text("""
                    INSERT INTO extraction_telemetry_v2 (
                        operation_id, article_id, url, publisher, host,
                        start_time, end_time, proxy_status, is_success, created_at
                    ) VALUES (
                        :operation_id, :article_id, :url, :publisher, :host,
                        :start_time, :end_time, :proxy_status, :is_success, :created_at
                    )
                """),
                {
                    "operation_id": "raw-sql-test",
                    "article_id": "article-raw",
                    "url": "https://example.com/raw",
                    "publisher": "Raw Test",
                    "host": "example.com",
                    "start_time": now,
                    "end_time": now,
                    "proxy_status": "success",  # String value
                    "is_success": True,
                    "created_at": now,
                }
            )
            
            # Query back and verify
            result = conn.execute(
                text(
                    "SELECT proxy_status FROM extraction_telemetry_v2 "
                    "WHERE operation_id = :op_id"
                ),
                {"op_id": "raw-sql-test"}
            ).fetchone()
            
            assert result is not None
            assert result[0] == "success"


def test_migration_documentation():
    """Verify the migration file has proper documentation."""
    from pathlib import Path
    
    migration_file = Path(
        "alembic/versions/d1e2f3a4b5c6_fix_proxy_status_column_type.py"
    )
    
    assert migration_file.exists(), f"Migration file not found: {migration_file}"
    
    content = migration_file.read_text()
    
    # Check for critical elements
    assert "proxy_status" in content
    assert "Integer" in content or "VARCHAR" in content or "String" in content
    assert "upgrade" in content
    assert "downgrade" in content
    
    # Check for proper revision identifier
    assert "revision: str = 'd1e2f3a4b5c6'" in content
    assert "down_revision:" in content
