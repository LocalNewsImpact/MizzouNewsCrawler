"""Helpers for reading typed source state columns in tests.

Centralizes column queries so migration from legacy JSON keys to typed columns
doesn't require bespoke SQL in every test. Returns a dict with the new column
names; legacy tests can still map to old keys if needed.
"""

from typing import Any, Dict
import json

from sqlalchemy import text
from sqlalchemy.engine import Engine


def read_source_state(engine: Engine, source_id: str) -> Dict[str, Any]:
    """Return typed RSS / effectiveness state for a source.

    Columns:
      rss_consecutive_failures (int)
      rss_transient_failures (JSON -> list)
      rss_missing_at (datetime or None)
      rss_last_failed_at (datetime or None)
      last_successful_method (str or None)
      no_effective_methods_consecutive (int)
      no_effective_methods_last_seen (datetime or None)
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                  rss_consecutive_failures,
                  rss_transient_failures,
                  rss_missing_at,
                  rss_last_failed_at,
                  last_successful_method,
                  no_effective_methods_consecutive,
                  no_effective_methods_last_seen
                FROM sources WHERE id = :id
                """
            ),
            {"id": source_id},
        ).fetchone()
    if not row:
        return {}
    # Normalize JSON/text columns for SQLite (which may return JSON as str)
    transient = row[1]
    if isinstance(transient, str):
        # Detect serialized list vs JSON string of list by first char
        try:
            if transient.strip().startswith("["):
                transient = json.loads(transient)
            else:
                # In some SQLite cases the JSON list of dicts can arrive as a
                # string representation already suitable for json.loads
                transient = json.loads(transient)
        except Exception:
            transient = []

    return {
        "rss_consecutive_failures": row[0],
        "rss_transient_failures": transient or [],
        "rss_missing_at": row[2],
        "rss_last_failed_at": row[3],
        "last_successful_method": row[4],
        "no_effective_methods_consecutive": row[5],
        "no_effective_methods_last_seen": row[6],
    }


def legacy_mapping(state: Dict[str, Any]) -> Dict[str, Any]:
    """Optional helper to expose legacy JSON key names for transitional tests."""
    out = dict(state)
    if "rss_missing_at" in state:
        out["rss_missing"] = (
            state["rss_missing_at"].isoformat() if state["rss_missing_at"] else None
        )
    if "rss_last_failed_at" in state:
        out["rss_last_failed"] = (
            state["rss_last_failed_at"].isoformat()
            if state["rss_last_failed_at"]
            else None
        )
    return out
