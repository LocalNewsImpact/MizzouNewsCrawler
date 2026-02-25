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

from ..models.database import DatabaseManager, safe_execute

logger = logging.getLogger(__name__)


def parse_frequency_to_publication_days(freq: str | None) -> float:
    """Convert a frequency string to expected publication cadence in days.

    This represents how often content is EXPECTED to be published, used for
    failure threshold calculations.

    Returns:
        Days between expected publications (7, 14, 30, etc.)
    """
    if not freq:
        return 7

    f = str(freq).lower()
    if "daily" in f or f == "day":
        return 1  # Content expected daily
    if "broadcast" in f:
        return 1  # Continuous content
    if "bi-week" in f or "biweekly" in f or "every 2" in f:
        return 14  # Content expected bi-weekly
    if "tri-week" in f or "triweekly" in f:
        return 7  # ~3x per 21 days
    if "weekly" in f or "week" in f:
        return 7  # Content expected weekly
    if "monthly" in f or "month" in f:
        return 30  # Content expected monthly
    if "hour" in f or "hourly" in f:
        return 0.25  # Hourly content

    return 7  # Default to weekly


def parse_frequency_to_discovery_days(freq: str | None) -> float:
    """Convert a frequency string to discovery check interval in days.

    This represents how often we ATTEMPT discovery, which is more aggressive
    than publication frequency to catch content as soon as it appears.

    Strategy:
    - Daily sites: Check every 6 hours (0.25 days)
    - Weekly sites: Check daily (1 day)
    - Bi-weekly sites: Check weekly (7 days)
    - Monthly sites: Check weekly (7 days)

    Returns:
        Days between discovery attempts
    """
    if not freq:
        return 7

    f = str(freq).lower()
    if "daily" in f or f == "day":
        return 0.25  # Check every 6 hours
    if "broadcast" in f:
        return 0.25  # Check every 6 hours
    if "bi-week" in f or "biweekly" in f or "every 2" in f:
        return 7  # Check weekly for bi-weekly pubs
    if "tri-week" in f or "triweekly" in f:
        return 3.5  # Check twice weekly
    if "weekly" in f or "week" in f:
        return 1  # Check daily for weekly pubs
    if "monthly" in f or "month" in f:
        return 7  # Check weekly for monthly pubs
    if "hour" in f or "hourly" in f:
        return 0.25  # Check every 6 hours

    return 7  # Default to weekly checks


def parse_frequency_to_days(freq: str | None) -> float:
    """Legacy function - redirects to discovery interval.

    Deprecated: Use parse_frequency_to_discovery_days() or
    parse_frequency_to_publication_days() explicitly.
    """
    return parse_frequency_to_discovery_days(freq)


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
            res = safe_execute(conn, text(sql), {"sid": source_id}).fetchone()
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

    cadence_days: float = 7.0
    try:
        if source_meta and isinstance(source_meta, dict):
            freq = source_meta.get("frequency") or source_meta.get("freq")
            cadence_days = parse_frequency_to_days(freq)
    except Exception:
        cadence_days = 7.0

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
