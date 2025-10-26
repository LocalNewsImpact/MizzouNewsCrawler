#!/usr/bin/env python3
"""
Backfill final_field_attribution for existing telemetry entries.

This script reconstructs the field attribution data from existing telemetry
by analyzing which method successfully extracted each field that ended up
in the final result.
"""

import json
import logging
import sqlite3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def determine_field_attribution(
    field_extraction: dict[str, dict[str, bool]], extracted_fields: dict[str, bool]
) -> dict[str, str]:
    """
    Determine which method provided each field in the final result.

    Logic:
    1. For each field that was successfully extracted (extracted_fields[field] == True)
    2. Find the first method that successfully extracted that field
    3. Use priority order: newspaper4k > beautifulsoup > selenium
    4. For fields that weren't extracted, mark as 'none'
    """
    attribution = {}

    # Priority order for methods (first successful method wins)
    method_priority = ["newspaper4k", "beautifulsoup", "selenium"]

    # Standard fields to check
    fields = ["title", "author", "content", "publish_date", "metadata"]

    for field in fields:
        # Check if this field was successfully extracted in the final result
        if extracted_fields.get(field, False):
            # Find the first method (by priority) that extracted this field
            attributed_method = None
            for method in method_priority:
                if method in field_extraction and field_extraction[method].get(
                    field, False
                ):
                    attributed_method = method
                    break

            # If no method claimed success but field exists, attribute to first attempted method
            if not attributed_method:
                # This might happen with metadata which is often not tracked in field_extraction
                for method in method_priority:
                    if method in field_extraction:
                        attributed_method = method
                        break

            attribution[field] = attributed_method or "unknown"
        else:
            # Field was not successfully extracted
            attribution[field] = "none"

    return attribution


def backfill_telemetry_attribution(
    db_path: str = "./data/mizzou.db", dry_run: bool = True
):
    """Backfill final_field_attribution for existing telemetry entries."""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get entries that need backfilling
        cursor.execute("""
            SELECT id, field_extraction, extracted_fields 
            FROM extraction_telemetry_v2 
            WHERE final_field_attribution IS NULL
            AND field_extraction IS NOT NULL
            ORDER BY id
        """)

        entries = cursor.fetchall()
        logger.info(f"Found {len(entries)} entries to backfill")

        backfilled_count = 0
        error_count = 0

        for entry_id, field_extraction_json, extracted_fields_json in entries:
            try:
                # Parse the JSON data
                field_extraction = json.loads(field_extraction_json or "{}")
                extracted_fields = json.loads(extracted_fields_json or "{}")

                # Determine field attribution
                attribution = determine_field_attribution(
                    field_extraction, extracted_fields
                )
                attribution_json = json.dumps(attribution)

                if dry_run:
                    # Just log what we would do
                    logger.debug(
                        f"ID {entry_id}: Would set attribution to {attribution}"
                    )
                else:
                    # Update the database
                    cursor.execute(
                        """
                        UPDATE extraction_telemetry_v2 
                        SET final_field_attribution = ? 
                        WHERE id = ?
                    """,
                        (attribution_json, entry_id),
                    )

                backfilled_count += 1

                if backfilled_count % 100 == 0:
                    logger.info(f"Processed {backfilled_count} entries...")

            except Exception as e:
                logger.error(f"Error processing entry {entry_id}: {e}")
                error_count += 1

        if not dry_run:
            conn.commit()

        logger.info(
            f"Backfill complete: {backfilled_count} entries processed, {error_count} errors"
        )

        # Show some examples
        if dry_run and backfilled_count > 0:
            logger.info("Sample attributions that would be created:")
            cursor.execute("""
                SELECT id, field_extraction, extracted_fields 
                FROM extraction_telemetry_v2 
                WHERE final_field_attribution IS NULL
                AND field_extraction IS NOT NULL
                LIMIT 3
            """)

            samples = cursor.fetchall()
            for entry_id, field_extraction_json, extracted_fields_json in samples:
                field_extraction = json.loads(field_extraction_json or "{}")
                extracted_fields = json.loads(extracted_fields_json or "{}")
                attribution = determine_field_attribution(
                    field_extraction, extracted_fields
                )

                print(f"\nEntry {entry_id}:")
                print(f"  Field extraction: {field_extraction}")
                print(f"  Extracted fields: {extracted_fields}")
                print(f"  Would set attribution: {attribution}")

    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        dry_run = False
        logger.warning("EXECUTING BACKFILL - this will modify the database")
    else:
        logger.info("DRY RUN - use --execute to actually update the database")

    backfill_telemetry_attribution(dry_run=dry_run)
