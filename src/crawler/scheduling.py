"""Scheduling helpers for discovery cadence based on publisher frequency.

This module provides small, conservative heuristics to decide whether a
source is "due" for discovery based on:
- declared frequency strings stored on the Source or CandidateLink records
- last processed/collected timestamp from candidate_links.processed_at
- a safe default cadence when no metadata is available

Assumptions made:
- `frequency` values are free-form but commonly include tokens like
  'daily', 'weekly', 'bi-weekly', 'monthly', 'broadcast'. We normalize
  and interpret them into an approximate number of days between runs.
- If there is no recorded `processed_at` on candidate_links for a source,
  we fall back to the Source.meta['frequency'] or a default of 7 days.
- This file intentionally keeps heuristics simple and deterministic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from ..models.database import DatabaseManager

logger = logging.getLogger(__name__)


def parse_frequency_to_days(freq: str | None) -> float:
    """Convert a human frequency string to an approximate cadence in days.

    Returns a floating point number of days to use as a cadence. Conservative
    defaults are used for ambiguous inputs.
    """
    if not freq:
        return 7

    f = str(freq).lower()
    if "daily" in f or f == "day":
        # Daily outlets publish throughout the day; treat cadence as 12 hours
        return 0.5
    if "broadcast" in f:
        # Broadcast stations (radio/TV) operate continuously; treat as 12 hours
        return 0.5
    # Detect bi-weekly patterns before generic weekly
    if "bi-week" in f or "biweekly" in f or "every 2" in f:
        return 14
    if "weekly" in f or "week" in f:
        return 7
    if "tri-week" in f or "triweekly" in f:
        return 7  # 3x per 21-day window, default weekly with additional checks
    if "monthly" in f or "month" in f:
        return 30
    if "hour" in f or "hourly" in f:
        return 1

    # Fallback conservative default
    return 7


def _get_last_processed_date(
    db: DatabaseManager,
    source_id: str,
) -> datetime | None:
    """Query candidate_links for the most recent processed_at for a source.

    Returns None if no processed_at rows exist for this source.
    """
    try:
        with db.engine.connect() as conn:
            sql = (
                "SELECT MAX(processed_at) as last FROM candidate_links "
                "WHERE source_id = :sid"
            )
            res = conn.execute(text(sql), {"sid": source_id}).fetchone()
            if not res:
                return None
            last = res[0]
            if last is None:
                return None
            # SQLAlchemy/SQLite may return string; try to coerce
            if isinstance(last, str):
                try:
                    return datetime.fromisoformat(last)
                except Exception:
                    return None
            return last
    except Exception as exc:
        logger.debug(
            "Could not query last processed date for %s: %s",
            source_id,
            exc,
        )
        return None


def should_schedule_discovery(
    db: DatabaseManager,
    source_id: str,
    source_meta: dict | None = None,
    now: datetime | None = None,
) -> bool:
    """Decide whether a source is due for discovery.

    Heuristic:
    - Determine cadence in days from `source_meta['frequency']` if available,
      otherwise default to 7 days.
    - Get last processed date from candidate_links.processed_at for the source.
    - If no last processed date exists, return True (it's due).
    - If `now - last_processed >= cadence` return True else False.

    This keeps the decision simple and database-driven.
    """
    now = now or datetime.utcnow()

    cadence_days = 7
    try:
        if source_meta and isinstance(source_meta, dict):
            freq = source_meta.get("frequency") or source_meta.get("freq")
            cadence_days = parse_frequency_to_days(freq)
    except Exception:
        cadence_days = 7

    dbm = db
    last = _get_last_processed_date(dbm, source_id)

    # If there is no processed_at record in candidate_links, fall back
    # to `source_meta['last_discovery_at']` if available. This allows the
    # discovery CLI to record a lightweight timestamp and honor `--due-only`.
    if last is None:
        try:
            if source_meta and isinstance(source_meta, dict):
                last_disc = source_meta.get("last_discovery_at")
                if last_disc:
                    # last_discovery_at is expected to be an ISO string
                    try:
                        if isinstance(last_disc, str):
                            last = datetime.fromisoformat(last_disc)
                        elif isinstance(last_disc, datetime):
                            last = last_disc
                    except Exception:
                        last = None
        except Exception:
            last = None

    if last is None:
        # No record of prior processing: schedule it
        return True

    # Some DB drivers return naive datetime in UTC; ensure comparison
    # uses the same tz
    try:
        delta = now - last
    except Exception:
        # Fallback - schedule if we can't compute delta
        return True

    return delta >= timedelta(days=cadence_days)
