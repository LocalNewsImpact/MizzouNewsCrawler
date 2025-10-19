#!/usr/bin/env python3
"""Migrate candidate_links.dataset_id from names/slugs to UUIDs.

This migration script fixes the data integrity issue where dataset_id columns
contain mixed data types (names, slugs, and sometimes UUIDs) instead of
consistently using dataset UUIDs.

Usage:
    python scripts/migrations/fix_dataset_ids_to_uuid.py [--dry-run]

Options:
    --dry-run    Show what would be changed without actually modifying data
"""

import argparse
import logging
import sys
import uuid as uuid_lib
from collections import defaultdict

from sqlalchemy import text

# Add project root to path
sys.path.insert(0, ".")

from src.models.database import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def validate_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        uuid_lib.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def migrate_dataset_ids(dry_run: bool = False) -> dict:
    """Migrate dataset_id values from names/slugs to UUIDs.
    
    Args:
        dry_run: If True, only analyze and report what would be changed
        
    Returns:
        Dictionary with migration statistics
    """
    logger.info("Starting dataset_id migration to UUIDs...")
    
    if dry_run:
        logger.info("DRY RUN MODE - No data will be modified")
    
    db = DatabaseManager()
    stats = {
        "total_rows": 0,
        "valid_uuids": 0,
        "invalid_values": 0,
        "null_values": 0,
        "updated_by_name": 0,
        "updated_by_slug": 0,
        "updated_by_label": 0,
        "unresolved": 0,
        "errors": 0,
    }
    
    invalid_values = defaultdict(int)
    unresolved_values = []
    
    try:
        with db.engine.connect() as conn:
            # Get all datasets for resolution mapping
            logger.info("Loading datasets for resolution...")
            datasets_result = conn.execute(
                text("SELECT id, name, slug, label FROM datasets")
            )
            datasets = list(datasets_result.fetchall())
            logger.info(f"Loaded {len(datasets)} datasets")
            
            # Create lookup maps
            name_to_uuid = {}
            slug_to_uuid = {}
            label_to_uuid = {}
            
            for dataset_id, name, slug, label in datasets:
                if name:
                    name_to_uuid[name] = dataset_id
                if slug:
                    slug_to_uuid[slug] = dataset_id
                if label:
                    label_to_uuid[label] = dataset_id
            
            # Analyze current state
            logger.info("Analyzing current dataset_id values...")
            result = conn.execute(
                text(
                    "SELECT dataset_id, COUNT(*) as count "
                    "FROM candidate_links "
                    "WHERE dataset_id IS NOT NULL "
                    "GROUP BY dataset_id"
                )
            )
            
            analysis = list(result.fetchall())
            
            for dataset_id_value, count in analysis:
                stats["total_rows"] += count
                
                if validate_uuid(dataset_id_value):
                    stats["valid_uuids"] += count
                    logger.debug(
                        f"  ✓ Valid UUID: {dataset_id_value} ({count} rows)"
                    )
                else:
                    stats["invalid_values"] += count
                    invalid_values[dataset_id_value] = count
                    logger.info(
                        f"  ⚠️  Invalid value: '{dataset_id_value}' ({count} rows)"
                    )
            
            # Count NULL values separately
            null_result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM candidate_links "
                    "WHERE dataset_id IS NULL"
                )
            )
            stats["null_values"] = null_result.scalar() or 0
            
            logger.info(f"\n=== Current State ===")
            logger.info(f"Total candidate_links with dataset_id: {stats['total_rows']}")
            logger.info(f"Valid UUIDs: {stats['valid_uuids']}")
            logger.info(f"Invalid values: {stats['invalid_values']}")
            logger.info(f"NULL values: {stats['null_values']}")
            
            if stats["invalid_values"] == 0:
                logger.info("\n✅ All dataset_id values are already valid UUIDs!")
                return stats
            
            # Migrate invalid values
            logger.info(f"\n=== Migration Plan ===")
            
            for invalid_value, count in invalid_values.items():
                resolved_uuid = None
                resolution_method = None
                
                # Try slug first (most common case)
                if invalid_value in slug_to_uuid:
                    resolved_uuid = slug_to_uuid[invalid_value]
                    resolution_method = "slug"
                    stats["updated_by_slug"] += count
                # Try name second
                elif invalid_value in name_to_uuid:
                    resolved_uuid = name_to_uuid[invalid_value]
                    resolution_method = "name"
                    stats["updated_by_name"] += count
                # Try label last
                elif invalid_value in label_to_uuid:
                    resolved_uuid = label_to_uuid[invalid_value]
                    resolution_method = "label"
                    stats["updated_by_label"] += count
                
                if resolved_uuid:
                    logger.info(
                        f"  ✓ '{invalid_value}' ({resolution_method}) "
                        f"→ {resolved_uuid} ({count} rows)"
                    )
                    
                    if not dry_run:
                        try:
                            conn.execute(
                                text(
                                    "UPDATE candidate_links "
                                    "SET dataset_id = :uuid "
                                    "WHERE dataset_id = :old_value"
                                ),
                                {"uuid": resolved_uuid, "old_value": invalid_value},
                            )
                            conn.commit()
                            logger.debug(f"    Updated {count} rows")
                        except Exception as e:
                            logger.error(
                                f"    Failed to update '{invalid_value}': {e}"
                            )
                            stats["errors"] += count
                            conn.rollback()
                else:
                    logger.warning(
                        f"  ✗ Cannot resolve '{invalid_value}' ({count} rows)"
                    )
                    stats["unresolved"] += count
                    unresolved_values.append(invalid_value)
            
            if not dry_run:
                logger.info("\n=== Migration Complete ===")
            else:
                logger.info("\n=== Dry Run Complete ===")
            
            # Verify final state
            if not dry_run:
                logger.info("Verifying migration results...")
                verify_result = conn.execute(
                    text(
                        "SELECT DISTINCT dataset_id "
                        "FROM candidate_links "
                        "WHERE dataset_id IS NOT NULL"
                    )
                )
                
                invalid_remaining = []
                for (val,) in verify_result:
                    if not validate_uuid(val):
                        invalid_remaining.append(val)
                
                if invalid_remaining:
                    logger.error(
                        f"\n⚠️  WARNING: {len(invalid_remaining)} invalid "
                        f"dataset_id values remain:"
                    )
                    for val in invalid_remaining[:10]:
                        logger.error(f"   - {val}")
                else:
                    logger.info("\n✅ All dataset_id values are now valid UUIDs!")
    
    except Exception as e:
        logger.exception("Migration failed with error")
        stats["errors"] = -1
        return stats
    
    # Print summary
    logger.info("\n=== Summary ===")
    logger.info(f"Total rows processed: {stats['total_rows']}")
    logger.info(f"Already valid UUIDs: {stats['valid_uuids']}")
    logger.info(f"Updated via slug: {stats['updated_by_slug']}")
    logger.info(f"Updated via name: {stats['updated_by_name']}")
    logger.info(f"Updated via label: {stats['updated_by_label']}")
    
    if stats["unresolved"] > 0:
        logger.warning(f"Unresolved values: {stats['unresolved']}")
        logger.warning(f"Unresolved dataset identifiers: {unresolved_values}")
    
    if stats["errors"] > 0:
        logger.error(f"Errors: {stats['errors']}")
    
    return stats


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate dataset_id values to UUIDs"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying data",
    )
    
    args = parser.parse_args()
    
    stats = migrate_dataset_ids(dry_run=args.dry_run)
    
    # Return exit code based on results
    if stats["errors"] < 0:
        return 1
    elif stats["errors"] > 0:
        logger.warning("Migration completed with errors")
        return 1
    elif stats["unresolved"] > 0:
        logger.warning("Migration completed with unresolved values")
        return 0  # Not a failure, but needs attention
    else:
        logger.info("Migration completed successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
