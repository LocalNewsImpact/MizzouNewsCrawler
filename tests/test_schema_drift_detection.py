"""Tests to detect schema drift between code and Alembic migrations.

These tests parse schema definitions from both the application code (CREATE TABLE
statements) and Alembic migrations, comparing them to catch drift before it reaches
production.
"""

import re
from pathlib import Path
from typing import Set

import pytest


def extract_columns_from_create_table(sql: str) -> Set[str]:
    """Extract column names from a CREATE TABLE statement.
    
    Args:
        sql: CREATE TABLE SQL statement
        
    Returns:
        Set of column names
    """
    # Find the CREATE TABLE statement
    create_match = re.search(
        r'CREATE TABLE (?:IF NOT EXISTS )?(\w+) \((.*?)\)',
        sql,
        re.DOTALL | re.IGNORECASE
    )
    
    if not create_match:
        return set()
    
    table_def = create_match.group(2)
    
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


def extract_columns_from_alembic_migration(migration_file: Path) -> Set[str]:
    """Extract column names from an Alembic migration file.
    
    Args:
        migration_file: Path to Alembic migration file
        
    Returns:
        Set of column names for byline_cleaning_telemetry table
    """
    with open(migration_file, 'r') as f:
        content = f.read()
    
    # Find the byline_cleaning_telemetry table creation
    in_table = False
    columns = []
    
    for line in content.split('\n'):
        if "'byline_cleaning_telemetry'" in line and 'op.create_table' in line:
            in_table = True
            continue
        
        if in_table:
            if 'sa.Column' in line:
                # Extract column name from sa.Column('column_name', ...)
                match = re.search(r"sa\.Column\('([^']+)'", line)
                if match:
                    columns.append(match.group(1))
            elif 'sa.PrimaryKeyConstraint' in line or 'sa.ForeignKeyConstraint' in line:
                # End of column definitions
                break
            elif ')' in line and not 'sa.Column' in line:
                # End of table definition
                break
    
    return set(columns)


class TestSchemaDrift:
    """Tests to detect schema drift between code and migrations."""
    
    def test_byline_telemetry_schema_matches_alembic(self):
        """Verify byline_telemetry.py CREATE TABLE matches Alembic migration.
        
        This test catches schema drift by comparing the CREATE TABLE statement
        in the code with the schema defined in Alembic migrations.
        """
        # Path to byline_telemetry.py
        telemetry_file = Path(__file__).parent.parent / "src" / "utils" / "byline_telemetry.py"
        
        # Read and parse CREATE TABLE from code
        with open(telemetry_file, 'r') as f:
            content = f.read()
        
        code_columns = extract_columns_from_create_table(content)
        
        # Path to Alembic migration
        migration_file = (
            Path(__file__).parent.parent / "alembic" / "versions" / 
            "e3114395bcc4_add_api_backend_and_telemetry_tables.py"
        )
        
        alembic_columns = extract_columns_from_alembic_migration(migration_file)
        
        # Compare schemas
        missing_in_code = alembic_columns - code_columns
        missing_in_alembic = code_columns - alembic_columns
        
        assert not missing_in_code, (
            f"Schema drift detected! Columns in Alembic migration but not in code:\n"
            f"{missing_in_code}\n\n"
            f"Update the CREATE TABLE statement in {telemetry_file} to include these columns."
        )
        
        assert not missing_in_alembic, (
            f"Schema drift detected! Columns in code but not in Alembic migration:\n"
            f"{missing_in_alembic}\n\n"
            f"Create a new Alembic migration to add these columns to PostgreSQL."
        )
        
        # Verify exact match
        assert code_columns == alembic_columns, (
            f"Schema mismatch between code and Alembic migration!\n"
            f"Code columns: {sorted(code_columns)}\n"
            f"Alembic columns: {sorted(alembic_columns)}\n"
            f"Missing in code: {missing_in_code}\n"
            f"Missing in Alembic: {missing_in_alembic}"
        )
    
    def test_insert_column_count_matches_create_table(self):
        """Verify INSERT statement column count matches CREATE TABLE.
        
        This test ensures the INSERT statement includes the correct number
        of columns and placeholders.
        """
        # Path to byline_telemetry.py
        telemetry_file = Path(__file__).parent.parent / "src" / "utils" / "byline_telemetry.py"
        
        with open(telemetry_file, 'r') as f:
            content = f.read()
        
        # Extract columns from CREATE TABLE
        create_columns = extract_columns_from_create_table(content)
        
        # Extract columns from INSERT statement
        insert_match = re.search(
            r'INSERT INTO byline_cleaning_telemetry \((.*?)\) VALUES \((.*?)\)',
            content,
            re.DOTALL
        )
        
        assert insert_match, "Could not find INSERT statement in byline_telemetry.py"
        
        columns_str = insert_match.group(1)
        values_str = insert_match.group(2)
        
        insert_columns = [c.strip() for c in columns_str.split(',') if c.strip()]
        placeholders = [v.strip() for v in values_str.split(',') if v.strip()]
        
        # Verify column count matches CREATE TABLE
        assert len(insert_columns) == len(create_columns), (
            f"INSERT column count ({len(insert_columns)}) does not match "
            f"CREATE TABLE column count ({len(create_columns)})\n"
            f"INSERT columns: {insert_columns}\n"
            f"CREATE TABLE columns: {sorted(create_columns)}"
        )
        
        # Verify column count matches placeholder count
        assert len(insert_columns) == len(placeholders), (
            f"INSERT column count ({len(insert_columns)}) does not match "
            f"placeholder count ({len(placeholders)})\n"
            f"This will cause runtime SQL errors!"
        )
        
        # Verify all CREATE TABLE columns are in INSERT
        insert_column_set = set(insert_columns)
        missing_in_insert = create_columns - insert_column_set
        
        assert not missing_in_insert, (
            f"INSERT statement missing columns from CREATE TABLE: {missing_in_insert}"
        )
    
    def test_transformation_steps_schema_matches_alembic(self):
        """Verify byline_transformation_steps CREATE TABLE matches Alembic migration."""
        # Path to byline_telemetry.py
        telemetry_file = Path(__file__).parent.parent / "src" / "utils" / "byline_telemetry.py"
        
        # Read and parse CREATE TABLE from code
        with open(telemetry_file, 'r') as f:
            content = f.read()
        
        # Extract transformation_steps table
        steps_match = re.search(
            r'CREATE TABLE IF NOT EXISTS byline_transformation_steps \((.*?)\)',
            content,
            re.DOTALL
        )
        
        assert steps_match, "Could not find byline_transformation_steps CREATE TABLE"
        
        code_columns = extract_columns_from_create_table(
            f"CREATE TABLE byline_transformation_steps ({steps_match.group(1)})"
        )
        
        # Path to Alembic migration
        migration_file = (
            Path(__file__).parent.parent / "alembic" / "versions" / 
            "e3114395bcc4_add_api_backend_and_telemetry_tables.py"
        )
        
        with open(migration_file, 'r') as f:
            content = f.read()
        
        # Find the byline_transformation_steps table
        in_table = False
        alembic_columns = []
        
        for line in content.split('\n'):
            if "'byline_transformation_steps'" in line and 'op.create_table' in line:
                in_table = True
                continue
            
            if in_table:
                if 'sa.Column' in line:
                    match = re.search(r"sa\.Column\('([^']+)'", line)
                    if match:
                        alembic_columns.append(match.group(1))
                elif 'sa.PrimaryKeyConstraint' in line or ')' in line:
                    break
        
        alembic_columns = set(alembic_columns)
        
        # Compare schemas
        missing_in_code = alembic_columns - code_columns
        missing_in_alembic = code_columns - alembic_columns
        
        assert not missing_in_code, (
            f"Schema drift in byline_transformation_steps! "
            f"Columns in Alembic but not in code: {missing_in_code}"
        )
        
        assert not missing_in_alembic, (
            f"Schema drift in byline_transformation_steps! "
            f"Columns in code but not in Alembic: {missing_in_alembic}"
        )


class TestSQLValidation:
    """Tests that validate SQL statement correctness."""
    
    def test_no_hardcoded_column_counts_in_docstrings(self):
        """Ensure no hardcoded column counts in comments that might become stale.
        
        Hardcoded column counts in comments/docstrings can mislead developers
        when the schema changes.
        """
        telemetry_file = Path(__file__).parent.parent / "src" / "utils" / "byline_telemetry.py"
        
        with open(telemetry_file, 'r') as f:
            content = f.read()
        
        # Look for suspicious patterns like "28 columns" or "32 columns" in comments
        # that might indicate hardcoded assumptions
        suspicious_patterns = [
            r'#.*\d+\s+columns',
            r'"""\s*\d+\s+columns',
            r"'''\s*\d+\s+columns",
        ]
        
        found_issues = []
        for pattern in suspicious_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Extract context around the match
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 50)
                context = content[start:end]
                found_issues.append(context)
        
        if found_issues:
            # This is a warning, not a failure - just documenting the pattern
            pytest.skip(
                f"Found potentially hardcoded column counts in comments:\n"
                f"{chr(10).join(found_issues)}\n"
                f"Consider removing hardcoded column counts to prevent stale documentation."
            )
    
    def test_all_required_columns_have_defaults_or_nullable(self):
        """Verify INSERT can succeed with minimal data.
        
        This test ensures that columns not always populated (like human_label)
        are either nullable or have default values.
        """
        # Path to Alembic migration
        migration_file = (
            Path(__file__).parent.parent / "alembic" / "versions" / 
            "e3114395bcc4_add_api_backend_and_telemetry_tables.py"
        )
        
        with open(migration_file, 'r') as f:
            content = f.read()
        
        # Find columns that are NOT NULL and have no default
        required_columns = []
        in_table = False
        
        for line in content.split('\n'):
            if "'byline_cleaning_telemetry'" in line and 'op.create_table' in line:
                in_table = True
                continue
            
            if in_table:
                if 'sa.Column' in line:
                    # Check if nullable=False (required) and no default
                    if 'nullable=False' in line:
                        match = re.search(r"sa\.Column\('([^']+)'", line)
                        if match:
                            col_name = match.group(1)
                            # Check if it has a default or is auto-generated
                            if 'server_default' not in line and 'default=' not in line:
                                if col_name != 'id':  # Primary key
                                    required_columns.append(col_name)
                elif 'sa.PrimaryKeyConstraint' in line:
                    break
        
        # These columns must be provided in INSERT
        # Verify our INSERT statement includes them
        telemetry_file = Path(__file__).parent.parent / "src" / "utils" / "byline_telemetry.py"
        with open(telemetry_file, 'r') as f:
            content = f.read()
        
        insert_match = re.search(
            r'INSERT INTO byline_cleaning_telemetry \((.*?)\)',
            content,
            re.DOTALL
        )
        
        assert insert_match, "Could not find INSERT statement"
        
        insert_columns = set(c.strip() for c in insert_match.group(1).split(','))
        
        missing_required = set(required_columns) - insert_columns
        
        assert not missing_required, (
            f"INSERT statement missing required (NOT NULL) columns: {missing_required}\n"
            f"Required columns: {required_columns}\n"
            f"INSERT columns: {sorted(insert_columns)}"
        )
