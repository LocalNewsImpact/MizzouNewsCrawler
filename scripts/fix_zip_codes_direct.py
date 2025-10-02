#!/usr/bin/env python3
"""
Fix ZIP codes stored as floats in Source metadata - Direct SQL approach.

This script converts ZIP codes from float format (e.g., 64108.0)
to proper string format (e.g., "64108") in Source metadata.
"""

import json
import logging
import sqlite3
import sys


def main():
    """Fix ZIP codes in Source metadata."""

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Database setup
    conn = sqlite3.connect("data/mizzou.db")

    try:
        updated_count = 0

        # Get all sources with metadata that might have zip codes
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, canonical_name, metadata FROM sources WHERE metadata IS NOT NULL"
        )

        for source_id, name, meta_str in cursor.fetchall():
            try:
                # Parse metadata
                meta = json.loads(meta_str) if meta_str else {}

                # Check if zip exists and needs fixing
                zip_code = meta.get("zip")
                if zip_code is not None:
                    original_zip = str(zip_code)

                    # Convert to string and remove .0 if it's a float or string ending in .0
                    if isinstance(zip_code, float):
                        # Convert float to int to remove decimal, then to string
                        if zip_code == int(zip_code):
                            fixed_zip = str(int(zip_code))
                        else:
                            fixed_zip = str(zip_code)
                    elif isinstance(zip_code, str) and zip_code.endswith(".0"):
                        # Remove .0 from string representation
                        try:
                            float_val = float(zip_code)
                            if float_val == int(float_val):
                                fixed_zip = str(int(float_val))
                            else:
                                fixed_zip = zip_code
                        except ValueError:
                            fixed_zip = zip_code.strip()
                    elif isinstance(zip_code, (int, str)):
                        # Convert to string and strip whitespace
                        fixed_zip = str(zip_code).strip()
                    else:
                        # Unknown type, convert to string
                        fixed_zip = str(zip_code)

                    # Only update if the zip actually changed
                    if original_zip != fixed_zip:
                        meta["zip"] = fixed_zip

                        # Update the source record
                        new_meta_str = json.dumps(meta)
                        cursor.execute(
                            "UPDATE sources SET metadata = ? WHERE id = ?",
                            (new_meta_str, source_id),
                        )

                        logger.info(
                            f"Fixed ZIP for {name}: {original_zip} -> {fixed_zip}"
                        )
                        updated_count += 1

            except Exception as e:
                logger.error(f"Error processing source {name}: {e}")
                continue

        # Commit changes
        conn.commit()

        logger.info(f"Successfully fixed ZIP codes for {updated_count} sources")

        # Show summary of ZIP formats
        logger.info("ZIP code samples after fix:")
        cursor.execute(
            """
            SELECT 
                canonical_name,
                json_extract(metadata, '$.zip') as zip_code
            FROM sources 
            WHERE json_extract(metadata, '$.zip') IS NOT NULL 
                AND json_extract(metadata, '$.zip') != ''
            LIMIT 5
        """
        )

        for row in cursor.fetchall():
            logger.info(f"  {row[0]}: '{row[1]}'")

    except Exception as e:
        logger.error(f"Failed to fix ZIP codes: {e}")
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
