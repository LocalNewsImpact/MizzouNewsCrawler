"""Wire reporters database lookup for detecting known wire service authors."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# Cache for wire reporters loaded from database
_wire_reporters_cache: dict[str, tuple[str, str]] | None = None


def _load_wire_reporters() -> dict[str, tuple[str, str]]:
    """Load wire reporters from byline_cleaning_telemetry table.

    Queries bylines that have been flagged as wire service content.
    Returns dict mapping lowercase author name to (service_name, confidence).
    """
    global _wire_reporters_cache

    if _wire_reporters_cache is not None:
        return _wire_reporters_cache

    try:
        from src.models.database import DatabaseManager
        from sqlalchemy import text

        db = DatabaseManager()
        reporters = {}

        with db.get_session() as session:
            # Query bylines marked as wire service content
            # Group by final_authors_display to get unique wire reporters
            query = text(
                """
                SELECT DISTINCT final_authors_display,
                       COALESCE(human_label, 'Wire Service') as service_name
                FROM byline_cleaning_telemetry
                WHERE has_wire_service = true
                  AND final_authors_display IS NOT NULL
                  AND final_authors_display != ''
            """
            )

            results = session.execute(query).fetchall()

            for author_display, service_name in results:
                if author_display:
                    # Store with lowercase key for case-insensitive matching
                    reporters[author_display.lower().strip()] = (service_name, "high")

        _wire_reporters_cache = reporters
        return reporters
    except (ImportError, AttributeError, Exception) as e:
        # Return empty dict if database unavailable or module not found
        # Log error for debugging but don't crash
        import logging

        logging.getLogger(__name__).debug(
            f"Failed to load wire reporters from database: {e}"
        )
        _wire_reporters_cache = {}
        return {}


def clear_wire_reporters_cache():
    """Clear the wire reporters cache (useful for testing)."""
    global _wire_reporters_cache
    _wire_reporters_cache = None


def set_wire_reporters_cache(reporters: dict[str, tuple[str, str]]):
    """Set wire reporters cache directly (for testing)."""
    global _wire_reporters_cache
    _wire_reporters_cache = reporters


def is_wire_reporter(author: str) -> tuple[str, str] | None:
    """Check if author is a known wire reporter.

    Args:
        author: Author name to check

    Returns:
        Tuple of (service_name, confidence) if match found, None otherwise
    """
    if not author:
        return None

    author_lower = author.lower().strip()

    # Load reporters from database
    reporters = _load_wire_reporters()

    # Direct match
    if author_lower in reporters:
        return reporters[author_lower]

    # Try partial matching for multi-author bylines
    # e.g., "John Smith and Jane Doe" where "John Smith" is a wire reporter
    for reporter_name, (service, confidence) in reporters.items():
        # Match if reporter name appears as complete word in byline
        pattern = r"\b" + re.escape(reporter_name) + r"\b"
        if re.search(pattern, author_lower, re.IGNORECASE):
            return (service, confidence)

    return None
