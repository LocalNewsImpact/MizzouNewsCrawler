"""
Test that all telemetry SQL schemas are PostgreSQL-compatible.

This test validates that DDL statements in telemetry modules can be
executed against PostgreSQL without syntax errors.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# Import all telemetry DDL schemas
from src.utils.extraction_telemetry import (
    _EXTRACTION_OUTCOMES_DDL,
    _EXTRACTION_OUTCOMES_INDEXES,
)
from src.utils.telemetry import (
    _DISCOVERY_METHOD_SCHEMA,
    _DISCOVERY_OUTCOMES_SCHEMA,
    _HTTP_STATUS_SCHEMA,
    _JOBS_SCHEMA,
    _OPERATIONS_SCHEMA,
)


@pytest.mark.postgres
@pytest.mark.integration
def test_telemetry_schemas_postgresql_compatible(cloud_sql_session):
    """Validate all telemetry DDL statements work in PostgreSQL."""
    session = cloud_sql_session

    # Collect all DDL statements from all telemetry modules
    all_ddl_statements = [
        (_JOBS_SCHEMA, "jobs schema"),
        (_OPERATIONS_SCHEMA, "operations schema"),
        (_HTTP_STATUS_SCHEMA, "http_status schema"),
        (_DISCOVERY_METHOD_SCHEMA, "discovery_method schema"),
        (_DISCOVERY_OUTCOMES_SCHEMA, "discovery_outcomes schema"),
        ([_EXTRACTION_OUTCOMES_DDL], "extraction_outcomes DDL"),
        (_EXTRACTION_OUTCOMES_INDEXES, "extraction_outcomes indexes"),
    ]

    failed = []

    for ddl_collection, description in all_ddl_statements:
        for statement in ddl_collection:
            try:
                session.execute(text(statement))
                session.commit()
            except SQLAlchemyError as e:
                error_msg = f"{description}: {statement[:100]}... ERROR: {e}"
                failed.append(error_msg)
                print(f"❌ {error_msg}")
            else:
                print(f"✅ {description} OK")

    if failed:
        error_list = "\n".join(f"  - {f}" for f in failed)
        pytest.fail(f"PostgreSQL compatibility errors:\n{error_list}")


def test_no_sqlite_imports_in_telemetry():
    """Ensure telemetry modules don't import sqlite3."""
    import src.utils.telemetry as telemetry_module
    import src.utils.extraction_telemetry as extraction_telemetry_module

    # Check telemetry module
    telemetry_source = telemetry_module.__file__
    with open(telemetry_source) as f:
        content = f.read()
        assert "import sqlite3" not in content, "telemetry.py should not import sqlite3"

    # Check extraction_telemetry module
    extraction_source = extraction_telemetry_module.__file__
    with open(extraction_source) as f:
        content = f.read()
        assert (
            "import sqlite3" not in content
        ), "extraction_telemetry.py should not import sqlite3"


def test_no_sqlite_specific_sql_in_telemetry():
    """Ensure telemetry SQL uses PostgreSQL-compatible syntax."""
    import src.utils.telemetry as telemetry_module
    import src.utils.extraction_telemetry as extraction_telemetry_module

    # Check for SQLite-specific patterns
    sqlite_patterns = [
        "INSERT OR IGNORE",
        "INSERT OR REPLACE",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        "datetime('now'",
        "AUTOINCREMENT",
    ]

    # Check telemetry module
    telemetry_source = telemetry_module.__file__
    with open(telemetry_source) as f:
        content = f.read()
        for pattern in sqlite_patterns:
            assert (
                pattern not in content
            ), f"telemetry.py contains SQLite-specific pattern: {pattern}"

    # Check extraction_telemetry module
    extraction_source = extraction_telemetry_module.__file__
    with open(extraction_source) as f:
        content = f.read()
        for pattern in sqlite_patterns:
            assert (
                pattern not in content
            ), f"extraction_telemetry.py contains SQLite-specific pattern: {pattern}"


def test_no_sqlite_patterns_in_production_code():
    """Scan ALL production Python files for SQLite-specific patterns."""
    from pathlib import Path

    # Patterns that indicate SQLite-specific code
    problematic_patterns = {
        "datetime('now'": "Use CURRENT_TIMESTAMP or Python datetime",
        "INSERT OR IGNORE": "Use INSERT ... ON CONFLICT DO NOTHING",
        "INSERT OR REPLACE": "Use INSERT ... ON CONFLICT DO UPDATE",
        "PRAGMA ": "PostgreSQL doesn't support PRAGMA (SQLite-only)",
        "AUTOINCREMENT": "Use SERIAL in PostgreSQL",
    }

    # Files to scan (production code only)
    src_dir = Path("src")
    failures = []

    # Safe patterns that are properly gated by dialect checks
    safe_contexts = [
        "_configure_sqlite_engine",  # Function only called for SQLite
        'if "sqlite" in',  # Dialect check
        "if getattr(self._store, '_is_sqlite'",  # SQLite check
        "# Replace AUTOINCREMENT",  # Translation code comment
        "def set_sqlite_pragma",  # SQLite-specific event handler
        "PRAGMA table_info",  # Table introspection (safe in SQLite-only context)
        "_exec_table_info",  # SQLite-specific helper function
        "# Convert SQLite-specific syntax",  # Translation code
    ]

    for py_file in src_dir.rglob("*.py"):
        # Skip test files, web/ (intentionally SQLite), and __pycache__
        if any(skip in str(py_file) for skip in ["test_", "web/", "__pycache__"]):
            continue

        with open(py_file) as f:
            lines = f.readlines()
            for pattern, suggestion in problematic_patterns.items():
                for i, line in enumerate(lines, start=1):
                    if pattern in line:
                        # Check if this is in a safe context
                        # Look at surrounding lines for safety markers
                        context_start = max(0, i - 10)
                        context_end = min(len(lines), i + 5)
                        context = "".join(lines[context_start:context_end])

                        if not any(safe in context for safe in safe_contexts):
                            failures.append(
                                f"{py_file}:{i} has '{pattern}' - {suggestion}"
                            )

    if failures:
        error_msg = "Found SQLite-specific patterns in production code:\n" + "\n".join(
            f"  - {f}" for f in failures
        )
        pytest.fail(error_msg)
