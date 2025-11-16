"""Stub for wire reporters database - minimal implementation for testing."""


def is_wire_reporter(author: str) -> tuple[str, str] | None:
    """Check if author is a known wire reporter.

    Args:
        author: Author name to check

    Returns:
        Tuple of (service_name, confidence) if match found, None otherwise
    """
    # Minimal stub - returns None (no wire reporter detected)
    # Real implementation would check against database of known reporters
    return None
