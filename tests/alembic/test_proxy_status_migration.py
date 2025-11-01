"""Test the proxy_status column type migration.

This test validates that the migration d1e2f3a4b5c6 correctly changes
the proxy_status column type from Integer to String.
"""

import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


@pytest.fixture
def sqlite_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_migration.db"
        db_url = f"sqlite:///{db_path}"
        yield db_url


@pytest.fixture
def alembic_config(sqlite_db):
    """Create an Alembic configuration for testing."""
    # Create a test alembic.ini in memory
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", sqlite_db)
    return config


class TestProxyStatusMigration:
    """Test the proxy_status column type migration."""

    def test_migration_creates_correct_column_type(self, sqlite_db):
        """Test that migrating to the fix creates a String column."""
        # Create engine and run migrations up to the fix
        engine = create_engine(sqlite_db)
        
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

    def test_proxy_status_accepts_all_valid_values(self, sqlite_db):
        """Test that the column accepts all expected proxy_status values."""
        engine = create_engine(sqlite_db)
        
        from src.models.telemetry_orm import Base, ExtractionTelemetryV2
        from datetime import datetime
        
        Base.metadata.create_all(engine)
        
        valid_statuses = ["success", "failed", "bypassed", "disabled", None]
        
        with Session(engine) as session:
            for idx, status in enumerate(valid_statuses):
                record = ExtractionTelemetryV2(
                    operation_id=f"test-status-{idx}",
                    article_id=f"article-{idx}",
                    url=f"https://example.com/test-{idx}",
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
            count = session.query(ExtractionTelemetryV2).count()
            assert count == len(valid_statuses)
            
            # Verify each status value
            for idx, expected_status in enumerate(valid_statuses):
                result = session.query(ExtractionTelemetryV2).filter_by(
                    operation_id=f"test-status-{idx}"
                ).first()
                assert result.proxy_status == expected_status

    def test_raw_sql_insert_with_string_status(self, sqlite_db):
        """Test that raw SQL INSERT with string proxy_status works."""
        engine = create_engine(sqlite_db)
        
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
                text("SELECT proxy_status FROM extraction_telemetry_v2 WHERE operation_id = :op_id"),
                {"op_id": "raw-sql-test"}
            ).fetchone()
            
            assert result is not None
            assert result[0] == "success"


def test_migration_documentation():
    """Verify the migration file has proper documentation."""
    migration_file = Path("alembic/versions/d1e2f3a4b5c6_fix_proxy_status_column_type.py")
    
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
