#!/usr/bin/env python3
"""
Update existing Source records to include state information from CSV - Direct SQL approach.

This script fixes the missing "state" field in Source metadata that was
causing geocoding failures. It reads the CSV and updates the metadata
for existing sources using direct SQL updates.
"""

import logging
import sys
from pathlib import Path
from urllib.parse import urlparse
import json

import pandas as pd
from sqlalchemy import create_engine, text


def main():
    """Update Source metadata with state information from CSV."""

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Database setup
    engine = create_engine("sqlite:///data/mizzou.db")

    try:
        # Read the CSV file
        csv_path = "sources/publinks.csv"
        logger.info(f"Reading CSV from {csv_path}")
        df = pd.read_csv(csv_path)

        logger.info(f"Loaded {len(df)} rows from CSV")

        updated_count = 0

        # Process each row in the CSV
        with engine.begin() as conn:
            for _, row in df.iterrows():
                try:
                    # Extract host from url_news for matching
                    if pd.isna(row["url_news"]):
                        continue

                    parsed_url = urlparse(str(row["url_news"]))
                    host_norm = parsed_url.netloc.lower().strip()

                    if not host_norm:
                        continue

                    # Get the current metadata for this source
                    result = conn.execute(
                        text(
                            "SELECT id, metadata FROM sources WHERE host_norm = :host_norm"
                        ),
                        {"host_norm": host_norm},
                    ).fetchone()

                    if result:
                        source_id, current_meta_str = result

                        # Parse current metadata
                        if current_meta_str:
                            current_meta = json.loads(current_meta_str)
                        else:
                            current_meta = {}

                        # Get state from CSV
                        csv_state = row.get("State", "MO")
                        if pd.isna(csv_state):
                            csv_state = "MO"

                        # Check if state needs to be updated
                        current_state = current_meta.get("state")

                        if current_state != csv_state:
                            # Update metadata with state information
                            current_meta["state"] = csv_state

                            # Update the source record with new metadata
                            new_meta_str = json.dumps(current_meta)
                            conn.execute(
                                text(
                                    "UPDATE sources SET metadata = :metadata WHERE id = :id"
                                ),
                                {"metadata": new_meta_str, "id": source_id},
                            )

                            # Get source name for logging
                            name_result = conn.execute(
                                text(
                                    "SELECT canonical_name FROM sources WHERE id = :id"
                                ),
                                {"id": source_id},
                            ).fetchone()

                            source_name = name_result[0] if name_result else "Unknown"

                            logger.info(
                                f"Updated {source_name} ({host_norm}): "
                                f"state = {csv_state}"
                            )
                            updated_count += 1
                        else:
                            logger.debug(
                                f"Skipped {host_norm}: "
                                f"state already correct ({current_state})"
                            )
                    else:
                        logger.warning(f"No source found for host {host_norm}")

                except Exception as e:
                    logger.error(
                        f"Error processing row for "
                        f"{row.get('url_news', 'unknown')}: {e}"
                    )
                    continue

        logger.info(
            f"Successfully updated {updated_count} source records "
            "with state information"
        )

        # Show summary of state values
        logger.info("State distribution in updated records:")
        with engine.begin() as conn:
            state_query = conn.execute(
                text(
                    """
                SELECT 
                    json_extract(metadata, '$.state') as state,
                    COUNT(*) as count
                FROM sources 
                WHERE json_extract(metadata, '$.state') IS NOT NULL
                GROUP BY json_extract(metadata, '$.state')
                ORDER BY count DESC
            """
                )
            )

            for row in state_query.fetchall():
                logger.info(f"  {row[0]}: {row[1]} records")

    except Exception as e:
        logger.error(f"Failed to update sources: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
