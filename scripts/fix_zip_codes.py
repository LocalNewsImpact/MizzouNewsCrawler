#!/usr/bin/env python3
"""
Fix ZIP codes stored as floats in Source metadata.

This script converts ZIP codes from float format (e.g., 64108.0)
to proper string format (e.g., "64108") in Source metadata.
"""

import json
import logging
import sys

from sqlalchemy import create_engine, text


def main():
    """Fix ZIP codes in Source metadata."""

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Database setup
    engine = create_engine("sqlite:///data/mizzou.db")

    try:
        updated_count = 0

        # Process sources with ZIP codes that need fixing
        with engine.begin() as conn:
            # Get all sources with metadata that might have zip codes
            result = conn.execute(
                text(
                    "SELECT id, canonical_name, metadata FROM sources WHERE metadata IS NOT NULL"
                )
            )

            for source_id, name, meta_str in result.fetchall():
                try:
                    # Parse metadata
                    meta = json.loads(meta_str) if meta_str else {}

                    # Check if zip exists and needs fixing
                    zip_code = meta.get("zip")
                    if zip_code is not None:
                        # Convert to string and remove .0 if it's a float
                        if isinstance(zip_code, float):
                            # Convert float to int to remove decimal, then to string
                            fixed_zip = (
                                str(int(zip_code))
                                if zip_code == int(zip_code)
                                else str(zip_code)
                            )
                        elif isinstance(zip_code, (int, str)):
                            # Convert to string and strip whitespace
                            fixed_zip = str(zip_code).strip()
                        else:
                            # Unknown type, convert to string
                            fixed_zip = str(zip_code)

                        # Only update if the zip actually changed
                        if str(zip_code) != fixed_zip:
                            meta["zip"] = fixed_zip

                            # Update the source record
                            new_meta_str = json.dumps(meta)
                            conn.execute(
                                text(
                                    "UPDATE sources SET metadata = :metadata WHERE id = :id"
                                ),
                                {"metadata": new_meta_str, "id": source_id},
                            )

                            logger.info(
                                f"Fixed ZIP for {name}: {zip_code} -> {fixed_zip}"
                            )
                            updated_count += 1

                except Exception as e:
                    logger.error(f"Error processing source {name}: {e}")
                    continue

        logger.info(f"Successfully fixed ZIP codes for {updated_count} sources")

        # Show summary of ZIP formats
        logger.info("ZIP code samples after fix:")
        with engine.begin() as conn:
            sample_query = conn.execute(
                text(
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
            )

            for row in sample_query.fetchall():
                logger.info(f"  {row[0]}: '{row[1]}'")

    except Exception as e:
        logger.error(f"Failed to fix ZIP codes: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
