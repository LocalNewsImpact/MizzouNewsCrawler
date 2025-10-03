"""
API endpoints for gazetteer telemetry data and management.

Provides endpoints for:
- Overall gazetteer processing statistics
- Per-publisher telemetry breakdowns
- OSM category analysis
- Address editing and re-processing capabilities
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class GazetteerStats(BaseModel):
    """Overall gazetteer telemetry statistics."""

    total_enrichment_attempts: int
    successful_geocoding: int
    failed_geocoding: int
    geocoding_success_rate: float
    total_osm_elements: int
    publishers_processed: int
    avg_elements_per_publisher: float
    # e.g., {"street_address": 45, "city_county": 12}
    geocoding_methods: dict[str, int]
    # e.g., {"businesses": 1200, "schools": 450}
    top_categories: dict[str, int]


class PublisherTelemetry(BaseModel):
    """Per-publisher telemetry breakdown."""

    source_id: str
    source_name: str
    city: str
    county: str
    state: str
    geocoding_method: str | None = None
    geocoding_success: bool | None = None
    address_used: str | None = None
    coordinates: dict[str, float] | None = None
    total_osm_elements: int | None = None
    osm_categories: dict[str, int] | None = None
    enrichment_success: bool | None = None
    processing_time_seconds: float | None = None
    failure_reason: str | None = None
    last_processed: datetime | None = None


class AddressEditRequest(BaseModel):
    """Request to update address information for re-processing."""

    source_id: str
    new_address: str
    new_city: str | None = None
    new_county: str | None = None
    new_state: str | None = None
    notes: str | None = None


class ReprocessRequest(BaseModel):
    """Request to re-run gazetteer processing for specific sources."""

    source_ids: list[str]
    force_reprocess: bool = False
    use_updated_addresses: bool = True


class TelemetryLogEntry(BaseModel):
    """Single entry from gazetteer telemetry log."""

    timestamp: datetime
    event: str
    source_id: str
    data: dict[str, Any]


def get_db_connection():
    """Get database connection for gazetteer data."""
    # Get the database path relative to the project root
    base_dir = Path(__file__).resolve().parents[1]  # Go up to project root
    db_path = base_dir / "data" / "mizzou.db"
    return sqlite3.connect(str(db_path))


def parse_telemetry_log() -> list[TelemetryLogEntry]:
    """Parse gazetteer_telemetry.log JSON entries."""
    base_dir = Path(__file__).resolve().parents[2]
    log_path = base_dir / "gazetteer_telemetry.log"

    if not log_path.exists():
        return []

    entries = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        entry = TelemetryLogEntry(
                            timestamp=datetime.fromisoformat(data["timestamp"]),
                            event=data["event"],
                            source_id=data["source_id"],
                            data=data,
                        )
                        entries.append(entry)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        # Skip malformed lines
                        continue
    except FileNotFoundError:
        pass

    return entries


def get_gazetteer_stats() -> GazetteerStats:
    """Calculate overall gazetteer telemetry statistics."""
    entries = parse_telemetry_log()

    # Group entries by source_id and event
    by_source = {}
    for entry in entries:
        source_id = entry.source_id
        if source_id not in by_source:
            by_source[source_id] = {}
        by_source[source_id][entry.event] = entry.data

    # Calculate statistics
    total_attempts = len([s for s in by_source.values() if "enrichment_attempt" in s])
    successful_geocoding = len(
        [
            s
            for s in by_source.values()
            if (
                "geocoding_result" in s
                and s["geocoding_result"].get("geocoding", {}).get("success", False)
            )
        ]
    )
    failed_geocoding = len(
        [
            s
            for s in by_source.values()
            if (
                "geocoding_result" in s
                and not s["geocoding_result"].get("geocoding", {}).get("success", False)
            )
        ]
    )

    total_geocoding = successful_geocoding + failed_geocoding
    geocoding_success_rate = (
        successful_geocoding / total_geocoding if total_geocoding > 0 else 0
    )

    # Geocoding methods
    geocoding_methods = {}
    for source_data in by_source.values():
        if "geocoding_result" in source_data:
            geocoding = source_data["geocoding_result"].get("geocoding", {})
            method = geocoding.get("method")
            if method:
                geocoding_methods[method] = geocoding_methods.get(method, 0) + 1

    # OSM statistics
    total_osm_elements = 0
    all_categories = {}
    for source_data in by_source.values():
        if "osm_query_result" in source_data:
            osm_data = source_data["osm_query_result"].get("osm_data", {})
            total_osm_elements += osm_data.get("total_elements", 0)
            categories = osm_data.get("categories", {})
            for cat, count in categories.items():
                all_categories[cat] = all_categories.get(cat, 0) + count

    # Top 10 categories
    sorted_categories = sorted(all_categories.items(), key=lambda x: x[1], reverse=True)
    top_categories = dict(sorted_categories[:10])

    avg_elements = total_osm_elements / total_attempts if total_attempts > 0 else 0

    return GazetteerStats(
        total_enrichment_attempts=total_attempts,
        successful_geocoding=successful_geocoding,
        failed_geocoding=failed_geocoding,
        geocoding_success_rate=round(geocoding_success_rate, 3),
        total_osm_elements=total_osm_elements,
        publishers_processed=total_attempts,
        avg_elements_per_publisher=round(avg_elements, 1),
        geocoding_methods=geocoding_methods,
        top_categories=top_categories,
    )


def get_publisher_telemetry() -> list[PublisherTelemetry]:
    """Get per-publisher telemetry breakdown."""
    entries = parse_telemetry_log()

    # Group entries by source_id
    by_source = {}
    for entry in entries:
        source_id = entry.source_id
        if source_id not in by_source:
            by_source[source_id] = {}
        by_source[source_id][entry.event] = entry.data

    publishers = []
    for source_id, events in by_source.items():
        # Base data from enrichment_attempt
        if "enrichment_attempt" not in events:
            continue

        attempt_data = events["enrichment_attempt"]
        location_data = attempt_data.get("location_data", {})

        publisher = PublisherTelemetry(
            source_id=source_id,
            source_name=attempt_data.get("source_name", "Unknown"),
            city=location_data.get("city", ""),
            county=location_data.get("county", ""),
            state=location_data.get("state", ""),
        )

        # Add geocoding data
        if "geocoding_result" in events:
            geocoding_data = events["geocoding_result"].get("geocoding", {})
            publisher.geocoding_method = geocoding_data.get("method")
            publisher.geocoding_success = geocoding_data.get("success")
            publisher.address_used = geocoding_data.get("address_used")
            publisher.coordinates = geocoding_data.get("coordinates")

        # Add OSM data
        if "osm_query_result" in events:
            osm_data = events["osm_query_result"].get("osm_data", {})
            publisher.total_osm_elements = osm_data.get("total_elements")
            publisher.osm_categories = osm_data.get("categories", {})

        # Add enrichment results
        if "enrichment_result" in events:
            result_data = events["enrichment_result"].get("result", {})
            publisher.enrichment_success = result_data.get("success")
            publisher.processing_time_seconds = result_data.get(
                "processing_time_seconds"
            )
            publisher.failure_reason = result_data.get("failure_reason")

        # Set last processed time (latest timestamp)
        if events:
            latest_timestamp = max(
                [
                    datetime.fromisoformat(event_data["timestamp"])
                    for event_data in events.values()
                    if "timestamp" in event_data
                ]
            )
            publisher.last_processed = latest_timestamp

        publishers.append(publisher)

    return sorted(
        publishers, key=lambda p: p.last_processed or datetime.min, reverse=True
    )


def get_failed_publishers() -> list[PublisherTelemetry]:
    """Get publishers with geocoding or enrichment failures."""
    all_publishers = get_publisher_telemetry()

    failed_publishers = [
        p
        for p in all_publishers
        if (
            p.geocoding_success is False
            or p.enrichment_success is False
            or p.total_osm_elements == 0
        )
    ]

    return failed_publishers


def update_publisher_address(source_id: str, address_data: AddressEditRequest) -> bool:
    """Update address information for a publisher in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Update candidate_links table with new address information
        update_fields = []
        params = []

        if address_data.new_address:
            update_fields.append("address = ?")
            params.append(address_data.new_address)

        if address_data.new_city:
            update_fields.append("city = ?")
            params.append(address_data.new_city)

        if address_data.new_county:
            update_fields.append("county = ?")
            params.append(address_data.new_county)

        if address_data.new_state:
            update_fields.append("state = ?")
            params.append(address_data.new_state)

        if not update_fields:
            return False

        params.append(source_id)

        query = f"""
            UPDATE candidate_links
            SET {", ".join(update_fields)}, last_modified = CURRENT_TIMESTAMP
            WHERE id = ?
        """

        cursor.execute(query, params)

        # Log the address update
        if address_data.notes:
            cursor.execute(
                """
                INSERT OR REPLACE INTO gazetteer_address_updates
                (source_id, old_address, new_address, notes, updated_at)
                VALUES (?, '', ?, ?, CURRENT_TIMESTAMP)
            """,
                (source_id, address_data.new_address, address_data.notes),
            )

        conn.commit()
        return cursor.rowcount > 0

    except sqlite3.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def trigger_gazetteer_reprocess(
    source_ids: list[str], force: bool = False
) -> dict[str, Any]:
    """Trigger gazetteer re-processing for specific sources."""
    # This would integrate with the existing gazetteer processing scripts
    # For now, return a placeholder response

    return {
        "status": "queued",
        "source_ids": source_ids,
        "force_reprocess": force,
        "estimated_completion": (
            datetime.now() + timedelta(minutes=len(source_ids) * 2)
        ),
        "message": (f"Queued {len(source_ids)} sources for gazetteer re-processing"),
    }


def ensure_address_updates_table():
    """Ensure the gazetteer_address_updates table exists."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS gazetteer_address_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            old_address TEXT,
            new_address TEXT,
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES candidate_links (id)
        )
    """
    )

    conn.commit()
    conn.close()
