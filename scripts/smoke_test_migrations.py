#!/usr/bin/env python3
"""Smoke test script to verify database migrations completed successfully.

This script:
1. Connects to the database
2. Verifies expected tables exist
3. Checks alembic_version table
4. Validates table structure for critical tables

Exit codes:
0 - All checks passed
1 - Configuration error
2 - Connection error
3 - Validation error
"""

import os
import sys

from sqlalchemy import create_engine, inspect, text


def get_database_url() -> str:
    """Get database URL from environment."""
    # Try direct DATABASE_URL first
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Build from components if using Cloud SQL
    use_cloud_sql = os.getenv("USE_CLOUD_SQL_CONNECTOR", "").lower() == "true"
    if use_cloud_sql:
        instance = os.getenv("CLOUD_SQL_INSTANCE")
        user = os.getenv("DATABASE_USER")
        password = os.getenv("DATABASE_PASSWORD")
        database = os.getenv("DATABASE_NAME")

        if not all([instance, user, password, database]):
            print("ERROR: Missing Cloud SQL configuration")
            sys.exit(1)

        # For smoke test, use pg8000 connector
        return f"postgresql+pg8000://{user}:{password}@/{database}?unix_sock=/cloudsql/{instance}/.s.PGSQL.5432"

    print("ERROR: No database configuration found")
    sys.exit(1)


def check_table_exists(inspector, table_name: str) -> bool:
    """Check if a table exists."""
    tables = inspector.get_table_names()
    return table_name in tables


def get_missing_tables(inspector, expected_tables: set[str]) -> set[str]:
    """Get list of missing tables."""
    existing_tables = set(inspector.get_table_names())
    return expected_tables - existing_tables


def check_alembic_version(engine) -> str:
    """Check and return current alembic version."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        if row:
            return row[0]
        return ""


def main():
    """Run smoke tests."""
    print("=" * 60)
    print("Database Migration Smoke Test")
    print("=" * 60)

    # Get database URL
    try:
        database_url = get_database_url()
        # Mask password in output
        safe_url = database_url
        if "@" in safe_url:
            parts = safe_url.split("@")
            user_pass = parts[0].split("://")[1]
            if ":" in user_pass:
                user = user_pass.split(":")[0]
                safe_url = safe_url.replace(user_pass, f"{user}:****")
        print(f"Database URL: {safe_url}")
    except Exception as e:
        print(f"ERROR: Failed to get database URL: {e}")
        sys.exit(1)

    # Connect to database
    print("\n1. Connecting to database...")
    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        print("   ✓ Connection successful")
    except Exception as e:
        print(f"   ✗ Connection failed: {e}")
        sys.exit(2)

    # Check alembic version
    print("\n2. Checking Alembic version...")
    try:
        version = check_alembic_version(engine)
        if version:
            print(f"   ✓ Current version: {version}")
        else:
            print("   ✗ No alembic version found")
            sys.exit(3)
    except Exception as e:
        print(f"   ✗ Failed to check version: {e}")
        sys.exit(3)

    # Verify core tables exist
    print("\n3. Verifying core tables exist...")
    inspector = inspect(engine)

    # Define expected tables
    core_tables = {
        "alembic_version",
        "sources",
        "candidate_links",
        "articles",
        "ml_results",
        "locations",
        "jobs",
    }

    telemetry_tables = {
        "byline_cleaning_telemetry",
        "content_cleaning_sessions",
        "extraction_telemetry_v2",
        "persistent_boilerplate_patterns",
    }

    backend_tables = {
        "snapshots",
    }

    all_expected_tables = core_tables | telemetry_tables | backend_tables

    missing_tables = get_missing_tables(inspector, all_expected_tables)

    if missing_tables:
        print(f"   ✗ Missing tables: {', '.join(sorted(missing_tables))}")
        sys.exit(3)
    else:
        print(f"   ✓ All {len(all_expected_tables)} expected tables exist")

    # Verify key columns in critical tables
    print("\n4. Verifying critical table structure...")
    try:
        # Check sources table has key columns
        sources_columns = {col["name"] for col in inspector.get_columns("sources")}
        required_sources_cols = {"id", "host", "status"}
        if not required_sources_cols.issubset(sources_columns):
            missing = required_sources_cols - sources_columns
            print(f"   ✗ sources table missing columns: {missing}")
            sys.exit(3)
        print("   ✓ sources table structure valid")

        # Check articles table has key columns
        articles_columns = {col["name"] for col in inspector.get_columns("articles")}
        required_articles_cols = {"id", "url", "title"}
        if not required_articles_cols.issubset(articles_columns):
            missing = required_articles_cols - articles_columns
            print(f"   ✗ articles table missing columns: {missing}")
            sys.exit(3)
        print("   ✓ articles table structure valid")
    except Exception as e:
        print(f"   ✗ Failed to verify table structure: {e}")
        sys.exit(3)

    # Final summary
    print("\n" + "=" * 60)
    print("✓ All smoke tests passed!")
    print("=" * 60)

    engine.dispose()
    sys.exit(0)


if __name__ == "__main__":
    main()
