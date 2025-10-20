"""Dataset resolution utilities for converting names/slugs to UUIDs."""

import logging
import uuid as uuid_lib
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def resolve_dataset_id(
    engine: Engine,
    dataset_identifier: Optional[str],
) -> Optional[str]:
    """Resolve dataset name, slug, or UUID to canonical UUID.

    This function accepts a dataset identifier in any of three forms:
    1. A valid UUID (returned as-is)
    2. A dataset slug (looked up in datasets table)
    3. A dataset name (looked up in datasets table)

    Args:
        engine: SQLAlchemy engine for database queries
        dataset_identifier: Name, slug, or UUID of dataset. Can be None.

    Returns:
        Dataset UUID as string, or None if dataset_identifier is None

    Raises:
        ValueError: If identifier is provided but dataset not found in database

    Examples:
        >>> # UUID pass-through
        >>> resolve_dataset_id(engine, "61ccd4d3-763f-4cc6-b85d-74b268e80a00")
        "61ccd4d3-763f-4cc6-b85d-74b268e80a00"

        >>> # Slug resolution
        >>> resolve_dataset_id(engine, "mizzou-missouri-state")
        "61ccd4d3-763f-4cc6-b85d-74b268e80a00"

        >>> # Name resolution
        >>> resolve_dataset_id(engine, "Mizzou Missouri State")
        "61ccd4d3-763f-4cc6-b85d-74b268e80a00"

        >>> # None handling
        >>> resolve_dataset_id(engine, None)
        None
    """
    # Handle None case - no dataset specified
    if not dataset_identifier:
        return None

    # Strip whitespace from identifier
    dataset_identifier = dataset_identifier.strip()
    if not dataset_identifier:
        return None

    # Check if already a valid UUID
    try:
        uuid_lib.UUID(dataset_identifier)
        logger.debug(
            "Dataset identifier is already a valid UUID: %s", dataset_identifier
        )
        return dataset_identifier
    except ValueError:
        # Not a UUID, need to look up by slug or name
        pass

    # Query database to find dataset by slug or name
    # Use parameterized query to prevent SQL injection
    with engine.connect() as conn:
        # Try exact match on slug first (most common case)
        result = conn.execute(
            text("SELECT id FROM datasets WHERE slug = :identifier LIMIT 1"),
            {"identifier": dataset_identifier},
        )
        row = result.fetchone()

        if row:
            dataset_uuid = str(row[0])
            logger.debug(
                "Resolved dataset slug '%s' to UUID: %s",
                dataset_identifier,
                dataset_uuid,
            )
            return dataset_uuid

        # Try exact match on name (case-sensitive)
        result = conn.execute(
            text("SELECT id FROM datasets WHERE name = :identifier LIMIT 1"),
            {"identifier": dataset_identifier},
        )
        row = result.fetchone()

        if row:
            dataset_uuid = str(row[0])
            logger.debug(
                "Resolved dataset name '%s' to UUID: %s",
                dataset_identifier,
                dataset_uuid,
            )
            return dataset_uuid

        # Try label column (case-sensitive)
        result = conn.execute(
            text("SELECT id FROM datasets WHERE label = :identifier LIMIT 1"),
            {"identifier": dataset_identifier},
        )
        row = result.fetchone()

        if row:
            dataset_uuid = str(row[0])
            logger.debug(
                "Resolved dataset label '%s' to UUID: %s",
                dataset_identifier,
                dataset_uuid,
            )
            return dataset_uuid

    # Dataset not found - raise error for explicit feedback
    raise ValueError(
        f"Dataset not found: '{dataset_identifier}'. "
        "Please check the dataset name, slug, or UUID."
    )
