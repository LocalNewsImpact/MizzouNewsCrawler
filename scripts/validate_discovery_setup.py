#!/usr/bin/env python3
"""Pre-flight validation script for discovery pipeline.

This script validates the discovery pipeline configuration before running
discovery to catch common issues early.

Usage:
    python scripts/validate_discovery_setup.py [dataset_label]

Examples:
    python scripts/validate_discovery_setup.py
    python scripts/validate_discovery_setup.py Mizzou-Missouri-State
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text

from src.models.database import DatabaseManager


def validate_discovery_setup(
    database_url: str = "sqlite:///data/mizzou.db",
    dataset_label: str | None = None,
) -> tuple[bool, list[str]]:
    """Run pre-flight checks for discovery pipeline.

    Args:
        database_url: Database connection string
        dataset_label: Optional dataset label to validate

    Returns:
        Tuple of (all_passed, list of error messages)
    """
    print("🔍 Validating discovery pipeline setup...\n")

    checks_passed = 0
    checks_total = 0
    errors = []

    try:
        db = DatabaseManager(database_url)
    except Exception as e:
        print(f"❌ Failed to create database manager: {e}")
        return False, [f"Database manager creation failed: {e}"]

    # Check 1: Database connectivity
    checks_total += 1
    print("1. Checking database connection...")
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("   ✅ Database connection OK")
        checks_passed += 1
    except Exception as e:
        error_msg = f"Database connection failed: {e}"
        print(f"   ❌ {error_msg}")
        errors.append(error_msg)

    # Check 2: Required tables exist
    checks_total += 1
    print("\n2. Checking required tables...")
    try:
        required_tables = [
            "sources",
            "datasets",
            "dataset_sources",
            "candidate_links",
        ]
        with db.engine.connect() as conn:
            for table in required_tables:
                conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        print("   ✅ All required tables exist")
        checks_passed += 1
    except Exception as e:
        error_msg = f"Missing required tables: {e}"
        print(f"   ❌ {error_msg}")
        errors.append(error_msg)

    # Check 3: Database dialect compatibility
    checks_total += 1
    print("\n3. Checking database dialect...")
    try:
        dialect = db.engine.dialect.name
        print(f"   ℹ️  Database dialect: {dialect}")
        if dialect in ("sqlite", "postgresql"):
            print("   ✅ Supported database dialect")
            checks_passed += 1
        else:
            error_msg = f"Unsupported database dialect: {dialect}"
            print(f"   ⚠️  {error_msg}")
            errors.append(error_msg)
    except Exception as e:
        error_msg = f"Failed to detect database dialect: {e}"
        print(f"   ❌ {error_msg}")
        errors.append(error_msg)

    # Check 4: Dataset validation (if specified)
    if dataset_label:
        checks_total += 1
        print(f"\n4. Validating dataset '{dataset_label}'...")
        try:
            with db.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT id FROM datasets WHERE label = :label"),
                    {"label": dataset_label},
                ).fetchone()

                if result:
                    dataset_id = result[0]
                    print(f"   ✅ Dataset '{dataset_label}' found")

                    # Check for linked sources
                    source_result = conn.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM dataset_sources
                            WHERE dataset_id = :dataset_id
                            """
                        ),
                        {"dataset_id": dataset_id},
                    ).fetchone()

                    source_count = source_result[0] if source_result else 0
                    if source_count > 0:
                        print(f"   ✅ Dataset has {source_count} linked sources")
                    else:
                        error_msg = (
                            f"Dataset '{dataset_label}' has no linked sources"
                        )
                        print(f"   ⚠️  {error_msg}")
                        errors.append(error_msg)

                    checks_passed += 1
                else:
                    error_msg = f"Dataset '{dataset_label}' not found"
                    print(f"   ❌ {error_msg}")

                    # Show available datasets
                    available = conn.execute(
                        text("SELECT label FROM datasets ORDER BY label")
                    ).fetchall()
                    if available:
                        labels = [row[0] for row in available]
                        print(f"   ℹ️  Available datasets: {', '.join(labels)}")
                    else:
                        print("   ℹ️  No datasets found in database")

                    errors.append(error_msg)
        except Exception as e:
            error_msg = f"Dataset validation failed: {e}"
            print(f"   ❌ {error_msg}")
            errors.append(error_msg)

    # Check 5: Sources available
    checks_total += 1
    print(f"\n{5 if dataset_label else 4}. Checking source availability...")
    try:
        with db.engine.connect() as conn:
            if dataset_label:
                result = conn.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT s.id)
                        FROM sources s
                        JOIN dataset_sources ds ON s.id = ds.source_id
                        JOIN datasets d ON ds.dataset_id = d.id
                        WHERE d.label = :label
                        """
                    ),
                    {"label": dataset_label},
                ).fetchone()
                scope = f"for dataset '{dataset_label}'"
            else:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM sources")
                ).fetchone()
                scope = "in database"

            count = result[0] if result else 0
            if count > 0:
                print(f"   ✅ {count} sources available {scope}")
                checks_passed += 1
            else:
                error_msg = f"No sources available {scope}"
                print(f"   ❌ {error_msg}")
                print("\n   💡 To load sources, run:")
                print(
                    "      python -m src.cli load-sources --csv sources/publinks.csv"
                )
                errors.append(error_msg)
    except Exception as e:
        error_msg = f"Source count check failed: {e}"
        print(f"   ❌ {error_msg}")
        errors.append(error_msg)

    # Summary
    print(f"\n{'=' * 70}")
    print(
        f"📊 Validation Summary: {checks_passed}/{checks_total} checks passed"
    )

    if checks_passed == checks_total:
        print("✅ All pre-flight checks passed - ready for discovery!")
        print(f"\n💡 Run discovery with:")
        if dataset_label:
            print(
                f"   python -m src.cli discover-urls --dataset {dataset_label}"
            )
        else:
            print(f"   python -m src.cli discover-urls")
        return True, []
    else:
        print("❌ Some pre-flight checks failed - see errors above")
        if errors:
            print("\n❌ Errors encountered:")
            for i, error in enumerate(errors, 1):
                print(f"   {i}. {error}")
        return False, errors


def main():
    """Main entry point for validation script."""
    dataset = sys.argv[1] if len(sys.argv) > 1 else None

    if dataset:
        print(f"Validating discovery setup for dataset: {dataset}\n")
    else:
        print("Validating discovery setup for all datasets\n")

    success, errors = validate_discovery_setup(dataset_label=dataset)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
