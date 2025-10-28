# Pipeline Critical SQL Tests

## Overview

This document describes the integration tests for critical SQL operations in the MizzouNewsCrawler pipeline. These tests are designed to catch SQL syntax errors, schema issues, and constraint violations before they reach production.

## Test Location

- **File**: `tests/integration/test_pipeline_critical_sql.py`
- **Marker**: `@pytest.mark.integration`
- **Database**: SQLite (in tests), PostgreSQL (in production)

## Running the Tests

```bash
# Run all critical SQL tests
python -m pytest tests/integration/test_pipeline_critical_sql.py -v -m integration --no-cov

# Run a specific test class
python -m pytest tests/integration/test_pipeline_critical_sql.py::TestDiscoveryCriticalSQL -v

# Run with coverage
python -m pytest tests/integration/test_pipeline_critical_sql.py --override-ini="addopts="
```

## Test Coverage

### Discovery Phase (2 tests)

**Purpose**: Ensure the discovery phase can insert candidate links and query sources without SQL errors.

- **test_insert_candidate_link**: Validates that candidate links can be inserted into the database
- **test_query_sources_for_discovery**: Tests the SQL query used to find sources for discovery

**Catches**:
- SQL syntax errors in INSERT statements
- Missing required fields in CandidateLink model
- Schema mismatches between code and database

### Verification Phase (2 tests)

**Purpose**: Ensure the verification phase can update candidate status and query pending URLs.

- **test_update_verification_status**: Tests updating candidate link status after verification
- **test_query_pending_verification**: Validates the SQL query for fetching candidates needing verification

**Catches**:
- SQL syntax errors in UPDATE statements
- Status field name changes
- Query syntax errors

### Extraction Phase (3 tests)

**Purpose**: Ensure the extraction phase can insert articles and handle duplicates correctly.

- **test_insert_article**: Tests article insertion into the database
- **test_duplicate_article_url_constraint**: Validates duplicate URL handling
- **test_query_verified_candidates**: Tests querying verified candidates for extraction

**Catches**:
- Foreign key constraint violations
- Duplicate handling logic
- Missing required fields in Article model

### Labeling/ML Analysis Phase (2 tests)

**Purpose**: Ensure the labeling phase can update article status and query cleaned articles.

- **test_update_article_to_labeled**: Tests updating article status after ML analysis
- **test_query_cleaned_articles**: Validates the SQL query for fetching cleaned articles

**Catches**:
- Status update SQL errors
- Query filter syntax errors
- Schema changes to status field

### Error Handling (1 test)

**Purpose**: Ensure that SQL errors are properly caught and handled.

- **test_sql_syntax_error_handling**: Validates that SQL syntax errors raise the expected exceptions

**Catches**:
- Unhandled SQL exceptions
- Error propagation issues

## What These Tests Prevent

These integration tests are specifically designed to catch the following production-breaking issues:

1. **SQL Syntax Errors**: Typos or syntax errors in SQL queries that would cause runtime failures
2. **Schema Changes**: Database schema changes that break existing queries
3. **Constraint Violations**: Foreign key, unique, and NOT NULL constraint violations
4. **Field Name Mismatches**: When model field names don't match database column names
5. **Missing Required Fields**: When code tries to insert records without required fields

## Test Strategy

These tests use a **real database connection** (SQLite in tests, PostgreSQL in production) to validate:

- SQL query syntax is correct
- Database schema matches model definitions
- Constraints are properly enforced
- Transactions behave correctly

This is different from unit tests which mock the database layer. Integration tests catch issues that only appear when running against a real database.

## Relationship to CI/CD

These tests should be run:

1. **Before merging PRs**: To catch SQL errors before they reach main
2. **In CI pipeline**: As part of automated testing
3. **Before deployments**: To validate schema migrations

## Adding New Tests

When adding new pipeline phases or modifying SQL operations:

1. Add a new test class following the naming convention `Test{Phase}CriticalSQL`
2. Write tests for each critical SQL operation (INSERT, UPDATE, SELECT)
3. Use the `@pytest.mark.integration` marker
4. Use real database fixtures, not mocks
5. Test both success and error cases

Example:

```python
class TestNewPhaseCriticalSQL:
    """Test critical SQL operations in new phase."""
    
    def test_insert_operation(self, test_db, test_source):
        """Test inserting data in new phase."""
        with test_db.session as session:
            # Create and insert test data
            # Verify insertion succeeded
            pass
    
    def test_query_operation(self, test_db):
        """Test querying data in new phase."""
        query = text("""
            SELECT field1, field2
            FROM table_name
            WHERE condition = :value
        """)
        
        with test_db.session as session:
            result = session.execute(query, {"value": "test"})
            # Verify query results
            pass
```

## Troubleshooting

### Tests fail with "No module named 'fastapi'"

The `backend_fixtures` plugin has been updated to handle missing dependencies. If you still see this error:

```bash
pip install fastapi  # or
python -m pytest --override-ini="addopts="  # Skip default addopts
```

### Tests fail with "invalid keyword argument"

This usually means the model definition has changed. Check:

1. The model class definition in `src/models/__init__.py`
2. The field names used in the test
3. Whether any fields have been renamed or removed

### Schema mismatch errors

If you see errors about missing columns or tables:

```bash
# Recreate the test database schema
rm -rf /tmp/test_*.db
python -m pytest tests/integration/test_pipeline_critical_sql.py -v
```

## Maintenance

These tests should be updated when:

- Database schema changes (migrations)
- Model definitions change
- SQL queries are modified
- New pipeline phases are added
- Constraints are added or removed

Regular maintenance ensures these tests continue to catch production issues effectively.
