#!/usr/bin/env python3
"""
Script to validate schema consistency between code and Alembic migrations.

This script can be run in CI to catch schema drift before deployment.
Exit code 0 means all checks pass, non-zero means drift detected.

Usage:
    python scripts/validate_telemetry_schema.py

Returns:
    0: All schema checks pass
    1: Schema drift detected
"""

import re
import sys
from pathlib import Path
from typing import Set


def extract_columns_from_create_table(sql: str, table_name: str) -> Set[str]:
    """Extract column names from a CREATE TABLE statement."""
    # Find the CREATE TABLE statement
    pattern = rf'CREATE TABLE (?:IF NOT EXISTS )?{re.escape(table_name)} \((.*?)\)'
    create_match = re.search(pattern, sql, re.DOTALL | re.IGNORECASE)
    
    if not create_match:
        return set()
    
    table_def = create_match.group(1)
    
    # Parse column definitions
    columns = []
    for line in table_def.split(','):
        line = line.strip()
        if not line or line.upper().startswith(('FOREIGN', 'PRIMARY', 'CONSTRAINT')):
            continue
        
        # Extract column name (first word)
        parts = line.split()
        if parts:
            columns.append(parts[0].strip())
    
    return set(columns)


def extract_columns_from_alembic(migration_file: Path, table_name: str) -> Set[str]:
    """Extract column names from an Alembic migration file."""
    with open(migration_file, 'r') as f:
        content = f.read()
    
    # Find the table creation
    in_table = False
    columns = []
    
    for line in content.split('\n'):
        if f"'{table_name}'" in line and 'op.create_table' in line:
            in_table = True
            continue
        
        if in_table:
            if 'sa.Column' in line:
                match = re.search(r"sa\.Column\('([^']+)'", line)
                if match:
                    columns.append(match.group(1))
            elif 'sa.PrimaryKeyConstraint' in line or 'sa.ForeignKeyConstraint' in line:
                break
            elif ')' in line and 'sa.Column' not in line:
                break
    
    return set(columns)


def check_table_schema(
    telemetry_file: Path,
    migration_file: Path,
    table_name: str
) -> tuple[bool, Set[str], Set[str]]:
    """Check if a table's schema matches between code and Alembic.
    
    Returns:
        (matches, missing_in_code, missing_in_alembic)
    """
    with open(telemetry_file, 'r') as f:
        content = f.read()
    
    code_columns = extract_columns_from_create_table(content, table_name)
    alembic_columns = extract_columns_from_alembic(migration_file, table_name)
    
    missing_in_code = alembic_columns - code_columns
    missing_in_alembic = code_columns - alembic_columns
    
    matches = not missing_in_code and not missing_in_alembic
    
    return matches, missing_in_code, missing_in_alembic


def check_insert_statement(telemetry_file: Path, table_name: str) -> tuple[bool, str]:
    """Check if INSERT statement column count matches CREATE TABLE.
    
    Returns:
        (valid, error_message)
    """
    with open(telemetry_file, 'r') as f:
        content = f.read()
    
    # Extract columns from CREATE TABLE
    create_columns = extract_columns_from_create_table(content, table_name)
    
    if not create_columns:
        return False, f"Could not find CREATE TABLE for {table_name}"
    
    # Extract columns from INSERT statement
    insert_match = re.search(
        rf'INSERT INTO {re.escape(table_name)} \((.*?)\) VALUES \((.*?)\)',
        content,
        re.DOTALL
    )
    
    if not insert_match:
        return False, f"Could not find INSERT statement for {table_name}"
    
    columns_str = insert_match.group(1)
    values_str = insert_match.group(2)
    
    insert_columns = [c.strip() for c in columns_str.split(',') if c.strip()]
    placeholders = [v.strip() for v in values_str.split(',') if v.strip()]
    
    # Check column count matches
    if len(insert_columns) != len(create_columns):
        return False, (
            f"INSERT column count ({len(insert_columns)}) does not match "
            f"CREATE TABLE column count ({len(create_columns)})"
        )
    
    # Check placeholder count matches
    if len(insert_columns) != len(placeholders):
        return False, (
            f"INSERT column count ({len(insert_columns)}) does not match "
            f"placeholder count ({len(placeholders)})"
        )
    
    # Check all columns are included
    insert_column_set = set(insert_columns)
    missing = create_columns - insert_column_set
    
    if missing:
        return False, f"INSERT statement missing columns: {missing}"
    
    return True, ""


def main():
    """Run all schema validation checks."""
    # Get project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # File paths
    telemetry_file = project_root / "src" / "utils" / "byline_telemetry.py"
    migration_file = (
        project_root / "alembic" / "versions" / 
        "e3114395bcc4_add_api_backend_and_telemetry_tables.py"
    )
    
    all_passed = True
    
    print("=" * 80)
    print("Telemetry Schema Validation")
    print("=" * 80)
    print()
    
    # Check byline_cleaning_telemetry table
    print("Checking byline_cleaning_telemetry table...")
    matches, missing_in_code, missing_in_alembic = check_table_schema(
        telemetry_file, migration_file, "byline_cleaning_telemetry"
    )
    
    if matches:
        print("✅ Schema matches between code and Alembic migration")
    else:
        print("❌ Schema drift detected!")
        all_passed = False
        
        if missing_in_code:
            print(f"   Columns in Alembic but not in code: {missing_in_code}")
        if missing_in_alembic:
            print(f"   Columns in code but not in Alembic: {missing_in_alembic}")
    
    print()
    
    # Check INSERT statement
    print("Checking INSERT statement for byline_cleaning_telemetry...")
    valid, error_msg = check_insert_statement(
        telemetry_file, "byline_cleaning_telemetry"
    )
    
    if valid:
        print("✅ INSERT statement is valid")
    else:
        print(f"❌ INSERT statement has issues: {error_msg}")
        all_passed = False
    
    print()
    
    # Check byline_transformation_steps table
    print("Checking byline_transformation_steps table...")
    matches, missing_in_code, missing_in_alembic = check_table_schema(
        telemetry_file, migration_file, "byline_transformation_steps"
    )
    
    if matches:
        print("✅ Schema matches between code and Alembic migration")
    else:
        print("❌ Schema drift detected!")
        all_passed = False
        
        if missing_in_code:
            print(f"   Columns in Alembic but not in code: {missing_in_code}")
        if missing_in_alembic:
            print(f"   Columns in code but not in Alembic: {missing_in_alembic}")
    
    print()
    print("=" * 80)
    
    if all_passed:
        print("✅ All schema validation checks passed!")
        print("=" * 80)
        return 0
    else:
        print("❌ Schema validation failed!")
        print("=" * 80)
        print()
        print("To fix:")
        print("1. Update CREATE TABLE statements in src/utils/byline_telemetry.py")
        print("2. Update INSERT statements to include all columns")
        print("3. Run tests: pytest tests/test_schema_drift_detection.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
