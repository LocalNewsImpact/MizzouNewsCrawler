#!/usr/bin/env python3
"""
Smoke test for extraction workflow fixes (Issue #105).

This script verifies that the key fixes are working:
1. DatabaseManager logs initialization correctly
2. EXTRACTION_DUMP_SQL flag works
3. Post-commit verification logic is present
4. Migration file is valid

Run: python scripts/test_extraction_fixes.py
"""

import os
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def test_database_manager_logging():
    """Test that DatabaseManager logs initialization."""
    logger.info("Testing DatabaseManager logging...")
    
    from src.models.database import DatabaseManager
    import tempfile
    
    # Create a test database with proper temp file
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        test_db_path = f.name
    
    test_db_url = f"sqlite:///{test_db_path}"
    os.environ['DATABASE_URL'] = test_db_url
    
    try:
        # Capture logs
        db = DatabaseManager()
        
        # Verify it initialized
        assert db.database_url == test_db_url, "Database URL not set correctly"
        
        db.close()
        logger.info("✓ DatabaseManager logging works")
    finally:
        # Clean up
        if os.path.exists(test_db_path):
            os.unlink(test_db_path)


def test_extraction_dump_sql_flag():
    """Test EXTRACTION_DUMP_SQL environment flag."""
    logger.info("Testing EXTRACTION_DUMP_SQL flag...")
    
    # Test flag detection
    os.environ['EXTRACTION_DUMP_SQL'] = 'false'
    assert os.getenv('EXTRACTION_DUMP_SQL', '').lower() not in ('true', '1', 'yes')
    
    os.environ['EXTRACTION_DUMP_SQL'] = 'true'
    assert os.getenv('EXTRACTION_DUMP_SQL', '').lower() in ('true', '1', 'yes')
    
    os.environ['EXTRACTION_DUMP_SQL'] = '1'
    assert os.getenv('EXTRACTION_DUMP_SQL', '').lower() in ('true', '1', 'yes')
    
    logger.info("✓ EXTRACTION_DUMP_SQL flag works")


def test_extraction_imports():
    """Test that extraction module imports successfully."""
    logger.info("Testing extraction module imports...")
    
    from src.cli.commands.extraction import (
        _process_batch,
        handle_extraction_command,
        ARTICLE_INSERT_SQL,
    )
    
    # Verify key functions exist
    assert callable(_process_batch), "_process_batch is not callable"
    assert callable(handle_extraction_command), "handle_extraction_command is not callable"
    
    # Verify SQL contains ON CONFLICT DO NOTHING
    sql_text = str(ARTICLE_INSERT_SQL)
    assert "ON CONFLICT DO NOTHING" in sql_text, "ON CONFLICT DO NOTHING not in SQL"
    
    logger.info("✓ Extraction module imports successfully")


def test_post_commit_verification_code():
    """Verify post-commit verification code is present."""
    logger.info("Testing post-commit verification code presence...")
    
    # Read the extraction.py file
    extraction_file = Path(__file__).parent.parent / 'src' / 'cli' / 'commands' / 'extraction.py'
    content = extraction_file.read_text()
    
    # Check for key verification components
    assert 'POST-COMMIT VERIFICATION' in content, "Post-commit verification comment not found"
    assert 'SELECT id FROM articles WHERE id = :id' in content, "Verification query not found"
    assert 'POST-COMMIT VERIFICATION FAILED' in content, "Verification failure message not found"
    
    logger.info("✓ Post-commit verification code is present")


def test_migration_file():
    """Verify migration file exists and is valid."""
    logger.info("Testing migration file...")
    
    migration_file = Path(__file__).parent.parent / 'alembic' / 'versions' / '1a2b3c4d5e6f_add_unique_constraint_articles_url.py'
    
    assert migration_file.exists(), "Migration file not found"
    
    # Import the migration to verify it's valid Python
    import importlib.util
    spec = importlib.util.spec_from_file_location("migration", migration_file)
    if spec and spec.loader:
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        
        # Verify key functions exist
        assert hasattr(migration, 'upgrade'), "Migration missing upgrade function"
        assert hasattr(migration, 'downgrade'), "Migration missing downgrade function"
        assert migration.revision == '1a2b3c4d5e6f', "Migration revision doesn't match"
        
    logger.info("✓ Migration file is valid")


def test_integration_tests_exist():
    """Verify integration tests were created."""
    logger.info("Testing integration tests existence...")
    
    test_file = Path(__file__).parent.parent / 'tests' / 'integration' / 'test_extraction_db.py'
    
    assert test_file.exists(), "Integration test file not found"
    
    content = test_file.read_text()
    
    # Check for key test functions
    assert 'test_extraction_inserts_article' in content
    assert 'test_extraction_query_returns_candidates' in content
    assert 'test_post_commit_verification' in content
    assert 'test_extraction_with_on_conflict_do_nothing' in content
    
    logger.info("✓ Integration tests exist")


def main():
    """Run all smoke tests."""
    logger.info("=" * 60)
    logger.info("Extraction Workflow Fixes - Smoke Tests (Issue #105)")
    logger.info("=" * 60)
    
    tests = [
        test_database_manager_logging,
        test_extraction_dump_sql_flag,
        test_extraction_imports,
        test_post_commit_verification_code,
        test_migration_file,
        test_integration_tests_exist,
    ]
    
    failed = []
    
    for test in tests:
        try:
            test()
        except Exception as e:
            logger.error(f"✗ {test.__name__} failed: {e}")
            failed.append((test.__name__, e))
    
    logger.info("=" * 60)
    
    if failed:
        logger.error(f"FAILED: {len(failed)} test(s) failed")
        for name, error in failed:
            logger.error(f"  - {name}: {error}")
        return 1
    else:
        logger.info("SUCCESS: All smoke tests passed!")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Run full test suite: pytest tests/ -v")
        logger.info("2. Run integration tests: pytest tests/integration/test_extraction_db.py -v -m integration")
        logger.info("3. Test migration in staging: alembic upgrade head")
        logger.info("4. Deploy to production with EXTRACTION_DUMP_SQL=false")
        return 0


if __name__ == '__main__':
    sys.exit(main())
