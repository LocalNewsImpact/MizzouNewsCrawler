#!/usr/bin/env python3
"""
Update existing Source records to include state information from CSV.

This script fixes the missing "state" field in Source metadata that was
causing geocoding failures. It reads the CSV and updates the metadata
for existing sources.
"""

import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import Source


def main():
    """Update Source metadata with state information from CSV."""

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Database setup
    engine = create_engine("sqlite:///data/mizzou.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Read the CSV file
        csv_path = "sources/publinks.csv"
        logger.info(f"Reading CSV from {csv_path}")
        df = pd.read_csv(csv_path)

        logger.info(f"Loaded {len(df)} rows from CSV")

        updated_count = 0

        # Process each row in the CSV
        for _, row in df.iterrows():
            try:
                # Extract host from url_news for matching
                parsed_url = urlparse(row["url_news"])
                host_norm = parsed_url.netloc.lower().strip()

                # Find the source with this host
                source = (
                    session.query(Source).filter(Source.host_norm == host_norm).first()
                )

                if source:
                    # Get current metadata
                    current_meta = source.meta or {}

                    # Check if state is already present and correct
                    current_state = current_meta.get("state")
                    csv_state = row.get("State", "MO")

                    if current_state != csv_state:
                        # Update metadata with state information
                        current_meta["state"] = csv_state

                        # Update the source record
                        source.meta = current_meta

                        logger.info(
                            f"Updated {source.canonical_name} ({host_norm}): "
                            f"state = {csv_state}"
                        )
                        updated_count += 1
                    else:
                        logger.debug(
                            f"Skipped {source.canonical_name} ({host_norm}): "
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

        # Commit all changes
        session.commit()
        logger.info(
            f"Successfully updated {updated_count} source records "
            "with state information"
        )

        # Show summary of state values
        logger.info("State distribution in updated records:")
        state_query = session.execute(
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
        session.rollback()
        return 1
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
