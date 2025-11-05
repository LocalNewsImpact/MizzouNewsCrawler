# Alembic Migration Testing Guide

## Overview

This document describes the comprehensive Alembic migration testing framework added to prevent database issues from repeatedly reaching production.

## Test Structure

### Test Files

- `tests/alembic/test_alembic_migrations.py` - Basic migration functionality tests
- `tests/alembic/test_alembic_cloud_sql.py` - Cloud SQL Connector integration tests  
- `tests/alembic/test_migration_workflow.py` - End-to-end workflow tests

### Running Tests

```bash
# Run all Alembic tests
make test-migrations

# Or directly with pytest
python -m pytest tests/alembic/ -v

# Run specific test file
python -m pytest tests/alembic/test_alembic_migrations.py -v

# Run specific test
python -m pytest tests/alembic/test_alembic_migrations.py::TestAlembicMigrations::test_alembic_revision_history -v
```

## Test Categories

### 1. Basic Migration Tests

These tests verify core Alembic functionality:

- **test_alembic_upgrade_head_sqlite**: Runs migrations against SQLite (development database)
- **test_alembic_downgrade_one_revision**: Tests migration rollback
- **test_alembic_revision_history**: Validates migration chain integrity
- **test_alembic_current_shows_version**: Checks version tracking
- **test_migrations_are_idempotent**: Ensures migrations can run multiple times safely
- **test_migration_creates_all_required_tables**: Validates all expected tables are created

### 2. Cloud SQL Connector Tests

These tests verify Cloud SQL integration:

- **test_alembic_env_module_imports**: Basic import test
- **test_alembic_uses_cloud_sql_connector_when_enabled**: Verifies Cloud SQL Connector usage
- **test_alembic_uses_database_url_when_connector_disabled**: Tests fallback to standard connection
- **test_alembic_env_detects_cloud_sql_config**: Environment detection
- **test_alembic_config_url_escapes_percent_signs**: ConfigParser % escaping
- **test_database_url_construction_from_components**: URL building from individual config vars

### 3. End-to-End Workflow Tests

These tests verify complete migration workflows:

- **test_fresh_database_setup**: Clean database initialization
- **test_migration_with_existing_data**: Data preservation during migrations
- **test_table_schemas_match_models**: Schema validation
- **test_migration_adds_indexes**: Index creation verification
- **test_migration_version_tracking**: Version tracking validation
- **test_rollback_and_reapply_migration**: Rollback/reapply cycle

## Known Issues

### Duplicate Table Creation in Migrations

**Issue**: The `byline_cleaning_telemetry` table is created in BOTH migrations:
- `e3114395bcc4_add_api_backend_and_telemetry_tables.py`
- `a9957c3054a4_add_remaining_telemetry_tables.py`

This causes "table already exists" errors when running migrations from scratch.

**Impact**: Some migration tests may fail when running against a fresh database.

**Workaround**: 
1. Skip the problematic migration revision when testing
2. Or fix the migration duplication (recommended for production)

**Resolution**: This should be fixed in a dedicated migration fix PR. The issue is tracked but not in scope for the testing infrastructure PR.

## PostgreSQL Testing

To run tests against PostgreSQL, set the `TEST_DATABASE_URL` environment variable:

```bash
export TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/test_db"
python -m pytest tests/alembic/ -v
```

Tests requiring PostgreSQL will be automatically skipped if `TEST_DATABASE_URL` is not set.

## Cloud SQL Connector Testing

Cloud SQL Connector tests use mocking to avoid requiring actual Cloud SQL access:

- Tests mock `create_cloud_sql_engine` to verify it's called with correct parameters
- Tests mock `engine_from_config` to verify fallback behavior
- No actual Cloud SQL connection is made during tests

## Test Configuration

### Environment Variables

Tests respect these environment variables:

- `DATABASE_URL` - Database connection string (set by test fixtures)
- `USE_CLOUD_SQL_CONNECTOR` - Enable/disable Cloud SQL Connector
- `CLOUD_SQL_INSTANCE` - Cloud SQL instance connection name
- `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME` - DB credentials
- `TEST_DATABASE_URL` - PostgreSQL test database (optional)

### Test Markers

Tests use the `@pytest.mark.integration` marker to indicate integration tests that:
- Run actual migrations
- Create temporary databases
- May take longer than unit tests

## CI/CD Integration

### GitHub Actions

Add to `.github/workflows/test.yml`:

```yaml
- name: Run migration tests
  run: |
    make test-migrations
```

### Cloud Build

Add to `cloudbuild.yaml`:

```yaml
- name: 'python:3.12'
  entrypoint: 'bash'
  args:
    - '-c'
    - |
      pip install -r requirements-dev.txt
      make test-migrations
```

## Best Practices

### When Writing Migrations

1. **Always use `IF NOT EXISTS`** for table/index creation
2. **Test migrations locally** before committing
3. **Run migration tests** to catch issues early
4. **Document breaking changes** in migration docstrings
5. **Ensure both upgrade and downgrade work**

### When Adding New Tests

1. **Use tmp_path fixture** for temporary databases
2. **Clean up after tests** (pytest handles tmp_path cleanup automatically)
3. **Mock external services** (Cloud SQL Connector, etc.)
4. **Use descriptive test names** that explain what's being tested
5. **Add docstrings** to explain test purpose

## Troubleshooting

### "Table already exists" errors

This usually indicates:
1. Duplicate table creation in migrations (see Known Issues above)
2. Test database wasn't cleaned up properly
3. Migration was run manually before test

**Solution**: Use fresh tmp_path for each test, or fix migration duplication.

### "Cloud SQL Connector import failed"

This indicates the Cloud SQL Python Connector isn't installed.

**Solution**:
```bash
pip install cloud-sql-python-connector[pg8000]
```

### "PostgreSQL tests skipped"

This is expected when `TEST_DATABASE_URL` is not set.

**To enable**: Set environment variable to point to test PostgreSQL instance.

### "Import error: alembic.env module not found"

This indicates sys.path manipulation issues.

**Solution**: Ensure tests run from project root with correct Python path.

## Future Enhancements

- [ ] Add mutation testing for migrations
- [ ] Test concurrent migration attempts
- [ ] Add performance benchmarks for migrations
- [ ] Test migration safety with production-like data volumes
- [ ] Add automated migration safety checks in pre-commit hooks
- [ ] Integration with testcontainers for PostgreSQL

## References

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Cloud SQL Python Connector](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector)
- [Issue #42 - Add Alembic Integration Tests](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/42)
