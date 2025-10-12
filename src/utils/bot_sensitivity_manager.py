"""Bot Sensitivity Manager - Adaptive crawling behavior based on bot detection.

This module provides centralized management of bot sensitivity ratings for publishers,
enabling adaptive rate limiting and backoff behavior based on bot detection encounters.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text

from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)


# Sensitivity level configurations (1-10 scale)
BOT_SENSITIVITY_CONFIG = {
    1: {  # Very permissive
        "inter_request_min": 0.5,
        "inter_request_max": 1.5,
        "batch_sleep": 5.0,
        "captcha_backoff_base": 300,
        "captcha_backoff_max": 1800,
        "max_backoff": 120,
        "request_timeout": 10,
    },
    2: {  # Low sensitivity
        "inter_request_min": 1.0,
        "inter_request_max": 3.0,
        "batch_sleep": 10.0,
        "captcha_backoff_base": 450,
        "captcha_backoff_max": 2400,
        "max_backoff": 180,
        "request_timeout": 15,
    },
    3: {  # Below moderate
        "inter_request_min": 2.0,
        "inter_request_max": 5.0,
        "batch_sleep": 20.0,
        "captcha_backoff_base": 600,
        "captcha_backoff_max": 3600,
        "max_backoff": 240,
        "request_timeout": 20,
    },
    4: {  # Slightly cautious
        "inter_request_min": 3.0,
        "inter_request_max": 8.0,
        "batch_sleep": 30.0,
        "captcha_backoff_base": 900,
        "captcha_backoff_max": 4200,
        "max_backoff": 300,
        "request_timeout": 20,
    },
    5: {  # Moderate (default)
        "inter_request_min": 5.0,
        "inter_request_max": 12.0,
        "batch_sleep": 60.0,
        "captcha_backoff_base": 1200,
        "captcha_backoff_max": 5400,
        "max_backoff": 300,
        "request_timeout": 20,
    },
    6: {  # Cautious
        "inter_request_min": 8.0,
        "inter_request_max": 18.0,
        "batch_sleep": 90.0,
        "captcha_backoff_base": 1800,
        "captcha_backoff_max": 7200,
        "max_backoff": 600,
        "request_timeout": 25,
    },
    7: {  # Very cautious
        "inter_request_min": 12.0,
        "inter_request_max": 25.0,
        "batch_sleep": 120.0,
        "captcha_backoff_base": 2400,
        "captcha_backoff_max": 9000,
        "max_backoff": 900,
        "request_timeout": 30,
    },
    8: {  # Highly sensitive
        "inter_request_min": 20.0,
        "inter_request_max": 35.0,
        "batch_sleep": 180.0,
        "captcha_backoff_base": 3600,
        "captcha_backoff_max": 10800,
        "max_backoff": 1200,
        "request_timeout": 30,
    },
    9: {  # Extremely sensitive
        "inter_request_min": 30.0,
        "inter_request_max": 50.0,
        "batch_sleep": 300.0,
        "captcha_backoff_base": 5400,
        "captcha_backoff_max": 14400,
        "max_backoff": 1800,
        "request_timeout": 30,
    },
    10: {  # Maximum caution
        "inter_request_min": 45.0,
        "inter_request_max": 90.0,
        "batch_sleep": 600.0,
        "captcha_backoff_base": 7200,
        "captcha_backoff_max": 21600,
        "max_backoff": 3600,
        "request_timeout": 30,
    },
}

# Event type -> (sensitivity_increase, max_sensitivity, base_cooldown_hours)
# Base cooldown is for low sensitivity (1-4), increases for higher sensitivity
SENSITIVITY_ADJUSTMENT_RULES = {
    "403_forbidden": (2, 10, 1.0),  # 1hr base, scales up
    "captcha_detected": (3, 10, 2.0),  # 2hr base, scales up
    "rate_limit_429": (1, 8, 0.5),  # 30min base, scales up
    "connection_timeout": (1, 7, 0.5),  # 30min base, scales up
    "multiple_failures": (2, 9, 1.5),  # 1.5hr base, scales up
}

# Known bot-sensitive publishers (pre-configured)
# Add known aggressive bot detectors here with their sensitivity levels (1-10)
KNOWN_SENSITIVE_PUBLISHERS = {
    # Example: "example.com": 10,
}


class BotSensitivityManager:
    """Manage bot sensitivity ratings and adaptive crawling behavior."""

    def __init__(self):
        """Initialize the bot sensitivity manager."""
        self.db = DatabaseManager()

    def get_sensitivity_config(
        self, host: str, source_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Get rate limiting configuration based on bot sensitivity.

        Args:
            host: Domain/host name
            source_id: Optional source ID (will look up if not provided)

        Returns:
            Configuration dict with rate limiting parameters
        """
        sensitivity = self.get_bot_sensitivity(host, source_id)
        return BOT_SENSITIVITY_CONFIG.get(sensitivity, BOT_SENSITIVITY_CONFIG[5])

    def get_bot_sensitivity(
        self, host: str, source_id: Optional[str] = None
    ) -> int:
        """Get current bot sensitivity rating for a host.

        Args:
            host: Domain/host name
            source_id: Optional source ID to avoid lookup

        Returns:
            Bot sensitivity rating (1-10 scale), default 5
        """
        # Check known sensitive publishers first
        if host in KNOWN_SENSITIVE_PUBLISHERS:
            return KNOWN_SENSITIVE_PUBLISHERS[host]

        # Query database for source-specific sensitivity
        try:
            with self.db.get_session() as session:
                if source_id:
                    query = text(
                        "SELECT bot_sensitivity FROM sources WHERE id = :source_id"
                    )
                    result = session.execute(query, {"source_id": source_id})
                else:
                    query = text(
                        "SELECT bot_sensitivity FROM sources "
                        "WHERE host = :host OR host_norm = :host_norm "
                        "LIMIT 1"
                    )
                    result = session.execute(
                        query, {"host": host, "host_norm": host.lower()}
                    )

                row = result.fetchone()
                if row and row[0] is not None:
                    return int(row[0])

        except Exception as e:
            logger.warning(
                f"Error fetching bot sensitivity for {host}: {e}, using default"
            )

        return 5  # Default moderate sensitivity

    def record_bot_detection(
        self,
        host: str,
        url: str,
        event_type: str,
        http_status_code: Optional[int] = None,
        response_indicators: Optional[dict] = None,
        source_id: Optional[str] = None,
    ) -> int:
        """Record a bot detection event and adjust sensitivity.

        Args:
            host: Domain/host name
            url: URL where bot was detected
            event_type: Type of detection ('403_forbidden', 'captcha_detected', etc.)
            http_status_code: HTTP status code if applicable
            response_indicators: Detection signals found
            source_id: Optional source ID

        Returns:
            New sensitivity level after adjustment
        """
        # Get or create source
        if not source_id:
            source_id = self._get_or_create_source_id(host)

        # Get current sensitivity
        current_sensitivity = self.get_bot_sensitivity(host, source_id)

        # Determine new sensitivity
        new_sensitivity = self._calculate_adjusted_sensitivity(
            current_sensitivity, event_type, host
        )

        # Record event
        event_id = str(uuid.uuid4())
        adjustment_reason = (
            f"Bot detection: {event_type} "
            f"(increased from {current_sensitivity} to {new_sensitivity})"
        )

        try:
            with self.db.get_session() as session:
                # Insert bot detection event
                insert_event = text(
                    """
                    INSERT INTO bot_detection_events (
                        id, source_id, host, url, event_type,
                        http_status_code, response_indicators,
                        previous_sensitivity, new_sensitivity,
                        adjustment_reason, detected_at
                    ) VALUES (
                        :id, :source_id, :host, :url, :event_type,
                        :http_status, :indicators,
                        :prev_sensitivity, :new_sensitivity,
                        :reason, CURRENT_TIMESTAMP
                    )
                    """
                )
                session.execute(
                    insert_event,
                    {
                        "id": event_id,
                        "source_id": source_id,
                        "host": host,
                        "url": url,
                        "event_type": event_type,
                        "http_status": http_status_code,
                        "indicators": (
                            json.dumps(response_indicators)
                            if response_indicators
                            else None
                        ),
                        "prev_sensitivity": current_sensitivity,
                        "new_sensitivity": new_sensitivity,
                        "reason": adjustment_reason,
                    },
                )

                # Update source sensitivity if it changed
                if new_sensitivity != current_sensitivity:
                    update_source = text(
                        """
                        UPDATE sources
                        SET bot_sensitivity = :new_sensitivity,
                            bot_sensitivity_updated_at = CURRENT_TIMESTAMP,
                            bot_encounters = bot_encounters + 1,
                            last_bot_detection_at = CURRENT_TIMESTAMP
                        WHERE id = :source_id
                        """
                    )
                    session.execute(
                        update_source,
                        {
                            "new_sensitivity": new_sensitivity,
                            "source_id": source_id,
                        },
                    )

                    logger.warning(
                        f"Bot detection on {host}: {event_type} - "
                        f"Sensitivity increased {current_sensitivity} -> "
                        f"{new_sensitivity}"
                    )
                else:
                    # Still increment encounter count even if sensitivity didn't change
                    update_encounters = text(
                        """
                        UPDATE sources
                        SET bot_encounters = bot_encounters + 1,
                            last_bot_detection_at = CURRENT_TIMESTAMP
                        WHERE id = :source_id
                        """
                    )
                    session.execute(update_encounters, {"source_id": source_id})

                    logger.info(
                        f"Bot detection on {host}: {event_type} - "
                        f"Sensitivity unchanged (cooldown or at max)"
                    )

                session.commit()

        except Exception as e:
            logger.error(f"Error recording bot detection for {host}: {e}")

        return new_sensitivity

    def _calculate_adjusted_sensitivity(
        self, current: int, event_type: str, host: str
    ) -> int:
        """Calculate new sensitivity level based on event.

        Args:
            current: Current sensitivity level
            event_type: Type of bot detection event
            host: Domain/host name

        Returns:
            New sensitivity level (1-10)
        """
        # Get adjustment rules for this event type
        if event_type not in SENSITIVITY_ADJUSTMENT_RULES:
            logger.warning(f"Unknown event type: {event_type}, no adjustment")
            return current

        increase, max_cap, base_cooldown = SENSITIVITY_ADJUSTMENT_RULES[event_type]

        # Calculate adaptive cooldown based on current sensitivity
        # Low sensitivity (1-4): use base cooldown (30min - 2hr)
        # Medium sensitivity (5-6): 2x base cooldown
        # High sensitivity (7-8): 4x base cooldown
        # Very high (9-10): 8x base cooldown (up to 16-48hr)
        if current <= 4:
            cooldown_hours = base_cooldown
        elif current <= 6:
            cooldown_hours = base_cooldown * 2
        elif current <= 8:
            cooldown_hours = base_cooldown * 4
        else:
            cooldown_hours = base_cooldown * 8

        # Check if we're in cooldown period
        if self._is_in_cooldown(host, cooldown_hours):
            logger.info(
                f"Sensitivity adjustment in cooldown for {host} "
                f"({cooldown_hours:.1f}h window, current sensitivity: {current})"
            )
            return current

        # Calculate new sensitivity
        new_sensitivity = min(current + increase, max_cap)

        return new_sensitivity

    def _is_in_cooldown(self, host: str, cooldown_hours: float) -> bool:
        """Check if host is in cooldown period for sensitivity adjustments.

        Args:
            host: Domain/host name
            cooldown_hours: Cooldown period in hours (can be fractional)

        Returns:
            True if in cooldown, False otherwise
        """
        try:
            with self.db.get_session() as session:
                query = text(
                    """
                    SELECT bot_sensitivity_updated_at
                    FROM sources
                    WHERE host = :host OR host_norm = :host_norm
                    LIMIT 1
                    """
                )
                result = session.execute(
                    query, {"host": host, "host_norm": host.lower()}
                )
                row = result.fetchone()

                if row and row[0]:
                    last_update = row[0]
                    cooldown_end = last_update + timedelta(hours=cooldown_hours)
                    return datetime.utcnow() < cooldown_end

        except Exception as e:
            logger.warning(f"Error checking cooldown for {host}: {e}")

        return False

    def _get_or_create_source_id(self, host: str) -> str:
        """Get source ID for host, create if doesn't exist.

        Args:
            host: Domain/host name

        Returns:
            Source ID
        """
        try:
            with self.db.get_session() as session:
                # Try to find existing source
                query = text(
                    """
                    SELECT id FROM sources
                    WHERE host = :host OR host_norm = :host_norm
                    LIMIT 1
                    """
                )
                result = session.execute(
                    query, {"host": host, "host_norm": host.lower()}
                )
                row = result.fetchone()

                if row:
                    return str(row[0])

                # Create new source if not found
                source_id = str(uuid.uuid4())
                insert = text(
                    """
                    INSERT INTO sources (id, host, host_norm, bot_sensitivity)
                    VALUES (:id, :host, :host_norm, 5)
                    """
                )
                session.execute(
                    insert,
                    {
                        "id": source_id,
                        "host": host,
                        "host_norm": host.lower(),
                    },
                )
                session.commit()

                logger.info(f"Created new source record for {host}: {source_id}")
                return source_id

        except Exception as e:
            logger.error(f"Error getting/creating source for {host}: {e}")
            # Return a fallback ID (should not happen in practice)
            return str(uuid.uuid4())

    def get_bot_encounter_stats(self, host: Optional[str] = None) -> dict[str, Any]:
        """Get bot encounter statistics.

        Args:
            host: Optional host to filter by

        Returns:
            Statistics dictionary
        """
        try:
            with self.db.get_session() as session:
                if host:
                    query = text(
                        """
                        SELECT
                            COUNT(*) as total_events,
                            COUNT(DISTINCT event_type) as event_types,
                            MAX(detected_at) as last_detection,
                            AVG(new_sensitivity) as avg_new_sensitivity
                        FROM bot_detection_events
                        WHERE host = :host
                        """
                    )
                    result = session.execute(query, {"host": host})
                else:
                    query = text(
                        """
                        SELECT
                            COUNT(*) as total_events,
                            COUNT(DISTINCT host) as affected_hosts,
                            COUNT(DISTINCT event_type) as event_types,
                            MAX(detected_at) as last_detection
                        FROM bot_detection_events
                        """
                    )
                    result = session.execute(query)

                row = result.fetchone()
                if row:
                    if host:
                        return {
                            "total_events": row[0] or 0,
                            "event_types": row[1] or 0,
                            "last_detection": str(row[2]) if row[2] else None,
                            "avg_sensitivity": float(row[3]) if row[3] else 5.0,
                        }
                    else:
                        return {
                            "total_events": row[0] or 0,
                            "affected_hosts": row[1] or 0,
                            "event_types": row[2] or 0,
                            "last_detection": str(row[3]) if row[3] else None,
                        }

        except Exception as e:
            logger.error(f"Error fetching bot encounter stats: {e}")

        return {"total_events": 0}
