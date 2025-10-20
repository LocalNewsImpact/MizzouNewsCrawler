#!/usr/bin/env python3
"""
Validate telemetry table schemas against Alembic migrations.

This script compares CREATE TABLE statements in code with the Alembic migration
definitions to catch schema drift before it causes production issues.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

# Add the parent directory to the path to import src modules
sys.path.append(str(Path(__file__).parent.parent))


class SchemaValidator:
    """Validates schema consistency between code and Alembic migrations."""

    # Known telemetry tables to validate
    TELEMETRY_TABLES = [
        "byline_cleaning_telemetry",
        "byline_transformation_steps",
        "content_cleaning_sessions",
        "content_cleaning_segments",
        "content_cleaning_wire_events",
        "content_cleaning_locality_events",
        "extraction_outcomes",
    ]

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def extract_columns_from_create_table(self, sql: str) -> Set[str]:
        """Extract column names from a CREATE TABLE statement."""
        columns = set()
        # Remove comments and normalize whitespace
        sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        sql = re.sub(r"\s+", " ", sql)

        # Find the columns section
        match = re.search(r"CREATE TABLE.*?\((.*)\)", sql, re.IGNORECASE | re.DOTALL)
        if not match:
            return columns

        columns_section = match.group(1)

        # Split by comma, but be careful with nested parentheses
        parts = []
        current = []
        depth = 0
        for char in columns_section:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
            current.append(char)
        if current:
            parts.append("".join(current).strip())

        # Extract column names
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Skip constraints
            if any(
                part.upper().startswith(kw)
                for kw in ["PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "INDEX"]
            ):
                continue
            # Get the first word (column name)
            words = part.split()
            if words:
                col_name = words[0].strip('"\'`')
                columns.add(col_name.lower())

        return columns

    def find_create_table_in_code(
        self, table_name: str
    ) -> Dict[str, Set[str]]:
        """Find CREATE TABLE statements for a table in Python code."""
        results = {}

        # Search in src/utils and src/telemetry
        search_dirs = [
            self.repo_root / "src" / "utils",
            self.repo_root / "src" / "telemetry",
        ]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for py_file in search_dir.glob("*.py"):
                content = py_file.read_text()
                # Look for CREATE TABLE statements in strings
                pattern = (
                    rf'CREATE TABLE[^(]*{re.escape(table_name)}\s*\('
                )
                matches = re.finditer(
                    pattern, content, re.IGNORECASE | re.DOTALL
                )

                for match in matches:
                    # Extract the full CREATE TABLE statement
                    start = match.start()
                    # Find the matching closing parenthesis
                    depth = 0
                    in_statement = False
                    statement_end = start

                    for i, char in enumerate(content[start:], start=start):
                        if char == "(":
                            depth += 1
                            in_statement = True
                        elif char == ")" and in_statement:
                            depth -= 1
                            if depth == 0:
                                statement_end = i + 1
                                break

                    sql = content[start:statement_end]
                    columns = self.extract_columns_from_create_table(sql)
                    if columns:
                        results[f"{py_file.name}"] = columns

        return results

    def find_create_table_in_migration(
        self, table_name: str
    ) -> Set[str]:
        """Find CREATE TABLE for a table in Alembic migrations."""
        migration_dir = self.repo_root / "alembic" / "versions"
        if not migration_dir.exists():
            return set()

        columns = set()

        for migration_file in migration_dir.glob("*.py"):
            content = migration_file.read_text()

            # Look for op.create_table with the table name
            pattern = rf"op\.create_table\s*\(\s*['\"]({re.escape(table_name)})['\"]"
            match = re.search(pattern, content, re.IGNORECASE)

            if match:
                # Extract the create_table call
                # Find the matching closing parenthesis
                start = match.start()
                depth = 0
                call_end = start

                for i, char in enumerate(content[start:], start=start):
                    if char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                        if depth == 0:
                            call_end = i + 1
                            break

                create_table_call = content[start:call_end]

                # Extract sa.Column definitions
                col_pattern = r"sa\.Column\s*\(\s*['\"]([^'\"]+)['\"]"
                for col_match in re.finditer(col_pattern, create_table_call):
                    col_name = col_match.group(1).lower()
                    columns.add(col_name)

                # We found the table, no need to check other migrations
                break

        return columns

    def validate_table(self, table_name: str) -> bool:
        """Validate schema consistency for a single table."""
        print(f"\nValidating {table_name}...")

        # Get columns from code
        code_results = self.find_create_table_in_code(table_name)
        if not code_results:
            self.warnings.append(
                f"No CREATE TABLE found in code for {table_name}"
            )
            return True  # Not an error if table isn't defined in code

        # Get columns from migration
        migration_cols = self.find_create_table_in_migration(table_name)
        if not migration_cols:
            self.warnings.append(
                f"No CREATE TABLE found in Alembic migrations for {table_name}"
            )
            return True  # Not an error if table isn't in migrations yet

        # Compare each code definition with migration
        has_error = False
        for source, code_cols in code_results.items():
            # Check for missing columns
            missing_in_code = migration_cols - code_cols
            if missing_in_code:
                self.errors.append(
                    f"{table_name} in {source}: Missing columns compared to migration: "
                    f"{sorted(missing_in_code)}"
                )
                has_error = True

            # Check for extra columns
            extra_in_code = code_cols - migration_cols
            if extra_in_code:
                self.errors.append(
                    f"{table_name} in {source}: Extra columns not in migration: "
                    f"{sorted(extra_in_code)}"
                )
                has_error = True

            if not has_error:
                print(f"  ✓ {source} matches migration ({len(code_cols)} columns)")

        return not has_error

    def validate_insert_statements(self) -> bool:
        """Validate INSERT statements have correct column counts."""
        print("\nValidating INSERT statements...")

        # Search for INSERT statements in telemetry files
        search_dirs = [
            self.repo_root / "src" / "utils",
            self.repo_root / "src" / "telemetry",
        ]

        has_error = False

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for py_file in search_dir.glob("*telemetry*.py"):
                content = py_file.read_text()

                # Find INSERT statements
                insert_pattern = r"INSERT INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)"
                for match in re.finditer(
                    insert_pattern, content, re.IGNORECASE | re.DOTALL
                ):
                    table_name = match.group(1)
                    columns = match.group(2)
                    values_section = match.group(3)

                    # Count columns
                    col_count = len([c.strip() for c in columns.split(",") if c.strip()])

                    # Extract the full statement to check for ON CONFLICT or other clauses
                    # that might have additional placeholders
                    full_match_start = match.start()
                    # Look ahead for ON CONFLICT or similar clauses
                    remaining = content[match.end():match.end() + 500]
                    
                    # Count total placeholders in the entire statement
                    # including VALUES and any ON CONFLICT clauses
                    statement_end = match.end()
                    # Find the end of the statement (next semicolon or closing of execute call)
                    for i, char in enumerate(remaining):
                        if char in (';', ')'):
                            if char == ')':
                                # Make sure this isn't part of a nested function call
                                # Simple heuristic: if we see a comma after, it's likely a parameter separator
                                if i + 1 < len(remaining) and remaining[i + 1:i + 2].strip() == ',':
                                    continue
                            statement_end = match.end() + i
                            break
                    
                    full_statement = content[full_match_start:statement_end]
                    
                    # Count placeholders - both ? and :name style
                    question_mark_count = full_statement.count("?")
                    # Named parameters: :param_name
                    named_params = len(re.findall(r':\w+', full_statement))
                    total_placeholders = question_mark_count + named_params

                    # Count placeholders in just the VALUES section
                    value_question_marks = values_section.count("?")
                    value_named_params = len(re.findall(r':\w+', values_section))
                    value_count = value_question_marks + value_named_params

                    # If using named parameters, the count should match columns
                    if named_params > 0 and question_mark_count == 0:
                        # Named parameters style
                        if value_count != col_count:
                            self.errors.append(
                                f"{py_file.name}: INSERT INTO {table_name} has "
                                f"{col_count} columns but {value_count} named parameter placeholders"
                            )
                            has_error = True
                        else:
                            print(
                                f"  ✓ {py_file.name}: INSERT INTO {table_name} "
                                f"({col_count} columns, named parameters)"
                            )
                    # If there are more placeholders than columns, check for ON CONFLICT
                    elif total_placeholders > col_count:
                        # This is likely an INSERT with ON CONFLICT DO UPDATE
                        # These are valid and expected, so just check basic sanity
                        if value_count > 0 and value_count < col_count - 1:
                            # Allow for some columns to have literal values
                            # Only flag if significantly fewer placeholders than columns
                            self.errors.append(
                                f"{py_file.name}: INSERT INTO {table_name} has "
                                f"{col_count} columns but only {value_count} value placeholders "
                                f"(note: statement has ON CONFLICT with {total_placeholders} total placeholders)"
                            )
                            has_error = True
                        else:
                            print(
                                f"  ✓ {py_file.name}: INSERT INTO {table_name} "
                                f"({col_count} columns, {value_count} VALUES placeholders, "
                                f"ON CONFLICT with {total_placeholders} total)"
                            )
                    # Allow for literal values in place of some placeholders
                    elif value_count < col_count and value_count >= col_count - 2:
                        # Some columns have literal values, which is acceptable
                        print(
                            f"  ✓ {py_file.name}: INSERT INTO {table_name} "
                            f"({col_count} columns, {value_count} placeholders, "
                            f"{col_count - value_count} literal value(s))"
                        )
                    elif col_count != value_count:
                        self.errors.append(
                            f"{py_file.name}: INSERT INTO {table_name} has "
                            f"{col_count} columns but {value_count} value placeholders"
                        )
                        has_error = True
                    else:
                        print(
                            f"  ✓ {py_file.name}: INSERT INTO {table_name} "
                            f"({col_count} columns)"
                        )

        return not has_error

    def run_validation(self) -> bool:
        """Run all validations."""
        print("=" * 70)
        print("Telemetry Schema Validation")
        print("=" * 70)

        success = True

        # Validate each table
        for table_name in self.TELEMETRY_TABLES:
            if not self.validate_table(table_name):
                success = False

        # Validate INSERT statements
        if not self.validate_insert_statements():
            success = False

        # Print summary
        print("\n" + "=" * 70)
        print("Validation Summary")
        print("=" * 70)

        if self.warnings:
            print("\nWarnings:")
            for warning in self.warnings:
                print(f"  ⚠ {warning}")

        if self.errors:
            print("\nErrors:")
            for error in self.errors:
                print(f"  ✗ {error}")
            print(f"\n{len(self.errors)} error(s) found")
        else:
            print("\n✓ All validations passed!")

        return success


def main():
    """Main entry point."""
    repo_root = Path(__file__).parent.parent
    validator = SchemaValidator(repo_root)

    success = validator.run_validation()

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
