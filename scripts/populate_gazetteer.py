"""Populate gazetteer table from publisher locations using OSM.

This background helper script iterates datasets and their mapped
`Source` records, geocodes publisher addresses (Nominatim / zippopotam.us
fallback) and queries Overpass to discover nearby schools, businesses,
landmarks, hospitals, and government buildings. Results are stored in the
`gazetteer` table linking back to `dataset_id`, `dataset_label`, and
`source_id` for provenance.

Usage:
    python scripts/populate_gazetteer.py --db sqlite:///data/mizzou.db
    python scripts/populate_gazetteer.py \
        --db sqlite:///data/mizzou.db \
        --dataset <dataset_slug>

Be respectful to OSM: this script sleeps between requests and retries on
transient errors.
"""

import argparse
import uuid
import json
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import requests  # type: ignore
from sqlalchemy import (  # type: ignore
    MetaData,
    Table,
    create_engine,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.orm import sessionmaker  # type: ignore

# Make sure `src` package is importable when running as a script
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))


class GazetteerTelemetry:
    """Telemetry tracking for gazetteer population process."""

    def __init__(self, log_file: str | None = None, enable_console: bool = True):
        self.log_file = log_file or "gazetteer_telemetry.log"
        self.enable_console = enable_console
        self.setup_logging()

    def setup_logging(self):
        """Setup telemetry logging."""
        self.logger = logging.getLogger("gazetteer_telemetry")
        self.logger.setLevel(logging.INFO)

        # Remove existing handlers to avoid duplicates
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        # File handler for telemetry
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setLevel(logging.INFO)

        # JSON formatter for structured telemetry
        formatter = logging.Formatter("%(message)s")
        file_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)

        # Console handler for development/testing (optional)
        if self.enable_console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # Allow propagation for pytest caplog to work
        self.logger.propagate = True

    def log_enrichment_attempt(
        self, source_id: str, source_name: str, city: str, county: str, state: str
    ):
        """Log the start of an enrichment attempt."""
        telemetry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": "enrichment_attempt",
            "source_id": source_id,
            "source_name": source_name,
            "location_data": {"city": city, "county": county, "state": state},
        }
        self.logger.info(json.dumps(telemetry))

    def log_geocoding_result(
        self,
        source_id: str,
        method: str,
        address_used: str,
        success: bool,
        lat: float | None = None,
        lon: float | None = None,
        error: str | None = None,
    ):
        """Log geocoding attempt results."""
        telemetry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": "geocoding_result",
            "source_id": source_id,
            "geocoding": {
                # "street_address", "city_county", "zip_code"
                "method": method,
                "address_used": address_used,
                "success": success,
                "coordinates": {"lat": lat, "lon": lon} if success else None,
                "error": error,
            },
        }
        self.logger.info(json.dumps(telemetry))

    def log_osm_query_result(
        self,
        source_id: str,
        total_elements: int,
        categories_data: dict[str, int],
        query_groups_used: int,
        radius_miles: int,
    ):
        """Log OSM query results."""
        telemetry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": "osm_query_result",
            "source_id": source_id,
            "osm_data": {
                "total_elements": total_elements,
                "categories": categories_data,
                "query_groups_used": query_groups_used,
                "radius_miles": radius_miles,
            },
        }
        self.logger.info(json.dumps(telemetry))

    def log_enrichment_result(
        self,
        source_id: str,
        success: bool,
        total_inserted: int = 0,
        categories_inserted: dict[str, int] | None = None,
        failure_reason: str | None = None,
        processing_time_seconds: float | None = None,
    ):
        """Log final enrichment results."""
        telemetry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": "enrichment_result",
            "source_id": source_id,
            "result": {
                "success": success,
                "total_inserted": total_inserted,
                "categories_inserted": categories_inserted or {},
                "failure_reason": failure_reason,
                "processing_time_seconds": processing_time_seconds,
            },
        }
        self.logger.info(json.dumps(telemetry))


# Global telemetry instance
telemetry = GazetteerTelemetry()


def geocode_address_nominatim(address: str) -> dict[str, float] | None:
    """Geocode an address string with Nominatim (OpenStreetMap).

    Returns a dict with 'lat' and 'lon' or None on failure.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "jsonv2", "limit": 1}
    headers = {"User-Agent": "mizzou-gazetteer/1.0 (contact: dev@example.com)"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                return {
                    "lat": float(data[0]["lat"]),
                    "lon": float(data[0]["lon"]),
                }
    except Exception:
        return None
    return None


# Import ORM models after ensuring `src` is on sys.path
from src.models import Dataset, GeocodeCache  # noqa: E402

# Expose create_engine at module level so tests can monkeypatch/import it
# Tests expect scripts.populate_gazetteer.create_engine to exist.
# Default to SQLAlchemy's create_engine implementation.
__all__ = ["create_engine"]

# Keep a reference to the original SQLAlchemy create_engine so we can
# detect when tests have monkeypatched the module-level name.
ORIGINAL_CREATE_ENGINE = create_engine


def zippopotamus_zip_lookup(zip5: str) -> dict[str, float] | None:
    try:
        r = requests.get(f"http://api.zippopotam.us/us/{zip5}", timeout=6)
        if r.status_code == 200:
            d = r.json()
            return {
                "lat": float(d["places"][0]["latitude"]),
                "lon": float(d["places"][0]["longitude"]),
            }
    except Exception:
        return None
    return None


def has_existing_osm_data(session, dataset_id, source_id, min_categories=3):
    """
    Check if a source already has sufficient OSM data in the gazetteer.

    Args:
        session: Database session
        dataset_id: ID of the dataset
        source_id: ID of the source to check
        min_categories: Minimum number of different categories required (default: 3)

    Returns:
        bool: True if source has sufficient existing OSM data
    """
    try:
        from sqlalchemy import text

        # Count distinct categories for this source
        query = text(
            """
            SELECT COUNT(DISTINCT category) as category_count,
                   COUNT(*) as total_entities
            FROM gazetteer
            WHERE dataset_id = :dataset_id
            AND source_id = :source_id
        """
        )

        result = session.execute(
            query, {"dataset_id": dataset_id, "source_id": source_id}
        ).fetchone()

        if result:
            category_count = result.category_count or 0
            total_entities = result.total_entities or 0

            # Consider data sufficient if we have multiple categories and
            # a reasonable entity count
            has_sufficient = category_count >= min_categories and total_entities >= 10

            if has_sufficient:
                print(
                    "    ✓ Existing OSM data found: %s categories, %s entities"
                    % (category_count, total_entities)
                )
                return True
            else:
                print(
                    "    ⚠ Insufficient OSM data: %s categories, %s entities"
                    % (category_count, total_entities)
                )
                return False

        return False

    except Exception as e:
        print(f"    Error checking existing OSM data: {e}")
        return False


def enrich_publisher_by_uuid(
    session, publisher_uuid, force=False, radius_miles=20, dry_run=False
):
    """
    On-demand OSM enrichment for a specific publisher by UUID.
    Used when pipeline needs immediate data for processing.

    Args:
        session: Database session
        publisher_uuid: UUID of the publisher to enrich (source.id)
        force: If True, skip existing data check and re-process
        radius_miles: Coverage radius for OSM queries
        dry_run: If True, don't write to database

    Returns:
        bool: True if enrichment was performed, False if not found/skipped
    """
    from sqlalchemy import text

    # Find source by UUID and get dataset info through dataset_sources
    source_query = text(
        """
        SELECT s.id as source_id, s.canonical_name, s.city, s.county,
               d.id as dataset_id, d.slug as dataset_slug
        FROM sources s
        JOIN dataset_sources ds ON s.id = ds.source_id
        JOIN datasets d ON ds.dataset_id = d.id
        WHERE s.id = :publisher_uuid
        LIMIT 1
    """
    )

    result = session.execute(
        source_query, {"publisher_uuid": publisher_uuid}
    ).fetchone()

    if not result:
        print(f"❌ No publisher found with UUID: {publisher_uuid}")
        return False

    source_id = result.source_id
    dataset_id = result.dataset_id
    canonical_name = result.canonical_name
    city = result.city
    county = result.county
    dataset_slug = result.dataset_slug

    print(f"🎯 Found publisher: {canonical_name}")
    print(f"   Location: {city}, {county}")
    print(f"   Dataset: {dataset_slug}")

    if dry_run:
        print("  DRY RUN: Would perform OSM enrichment")
        return True

    # Use existing enrichment function with proper IDs
    return enrich_publisher_osm_data(
        session, dataset_id, source_id, force, radius_miles
    )


def enrich_publisher_osm_data(
    session, dataset_id, source_id, force=False, radius_miles=20
):
    """
    On-demand OSM enrichment for a specific publisher/source.
    Used when pipeline needs immediate data for processing.

    Args:
        session: Database session
        force: If True, skip existing data check and re-process
        radius_miles: Coverage radius for OSM queries

    Returns:
        bool: True if enrichment was performed, False if skipped
    """
    print(f"  On-demand OSM enrichment for source {source_id}")

    # Check for existing data unless forced
    if not force and has_existing_osm_data(session, dataset_id, source_id):
        print("    Skipping: sufficient OSM data already exists")
        return False

    # Get source details
    query = text(
        """
        SELECT s.*, ds.legacy_host_id
        FROM sources s
        JOIN dataset_sources ds ON s.id = ds.source_id
        WHERE s.id = :source_id AND ds.dataset_id = :dataset_id
    """
    )

    result = session.execute(
        query, {"source_id": source_id, "dataset_id": dataset_id}
    ).fetchone()

    if not result:
        print(f"    Error: source {source_id} not found in dataset {dataset_id}")
        return False

    src = dict(result._mapping)

    # Parse JSON metadata if it's a string
    import json

    if isinstance(src.get("metadata"), str):
        try:
            src["metadata"] = json.loads(src["metadata"])
        except (json.JSONDecodeError, TypeError):
            src["metadata"] = {}

    # Process this single source using existing logic
    print(f"    Processing: {src.get('canonical_name', src.get('host'))}")

    # Use the existing geocoding and OSM processing logic
    # [This would call the same logic as the bulk processor but for one source]
    success = _process_single_source_osm(
        session, src, dataset_id, radius_miles, dry_run=False
    )

    if success:
        print(f"    ✓ OSM enrichment completed for source {source_id}")
    else:
        print(f"    ✗ OSM enrichment failed for source {source_id}")

    return success


def _process_single_source_osm(session, src, dataset_id, radius_miles, dry_run=False):
    """
    Process OSM data for a single source. Extracted for reuse between
    bulk processing and on-demand enrichment.
    """
    start_time = time.time()
    source_id = src.get("id")
    host_or_name = src.get("canonical_name") or src.get("host")

    # Extract location data for telemetry
    city = src.get("city", "")
    county = src.get("county", "")
    state = src.get("metadata", {}).get("state", "MO") if src.get("metadata") else "MO"

    # Log enrichment attempt
    telemetry.log_enrichment_attempt(
        source_id, host_or_name, str(city), str(county), str(state)
    )

    try:
        print(f"    Processing source: {host_or_name} ({source_id})")

        # Get dataset label for proper gazetteer records
        dataset_query = text("SELECT label FROM datasets WHERE id = :dataset_id")
        dataset_result = session.execute(
            dataset_query, {"dataset_id": dataset_id}
        ).fetchone()
        dataset_label = dataset_result.label if dataset_result else None

        # Check for existing OSM data
        if source_id and has_existing_osm_data(session, dataset_id, source_id):
            print("      Skipping: sufficient OSM data already exists")
            return True

        # Get the category map (same as in bulk processing)
        category_map = {
            "schools": [
                "amenity=school",
                "amenity=university",
                "amenity=college",
                "amenity=kindergarten",
            ],
            "government": [
                "amenity=townhall",
                "amenity=courthouse",
                "amenity=police",
                "amenity=fire_station",
                "amenity=post_office",
                "office=government",
            ],
            "healthcare": [
                "amenity=hospital",
                "amenity=clinic",
                "amenity=pharmacy",
                "amenity=dentist",
                "amenity=veterinary",
            ],
            "businesses": [
                "shop=supermarket",
                "shop=department_store",
                "amenity=restaurant",
                "amenity=bank",
                "shop=mall",
                "amenity=fuel",
            ],
            "landmarks": [
                "amenity=library",
                "leisure=park",
                "tourism=attraction",
                "amenity=community_centre",
                "historic=building",
                "historic=monument",
                "historic=memorial",
                "historic=ruins",
                "historic=archaeological_site",
            ],
            "sports": [
                "leisure=sports_centre",
                "leisure=stadium",
                "leisure=pitch",
                "leisure=golf_course",
                "sport=american_football",
                "sport=baseball",
                "sport=basketball",
            ],
            "transportation": [
                "railway=station",
                "aeroway=aerodrome",
                "highway=motorway_junction",
                "amenity=parking",
                "man_made=bridge",
                "public_transport=station",
            ],
            "religious": [
                "amenity=place_of_worship",
                "building=church",
                "building=cathedral",
            ],
            "entertainment": [
                "amenity=theatre",
                "amenity=cinema",
                "amenity=bar",
                "amenity=pub",
                "leisure=fitness_centre",
                "tourism=hotel",
            ],
            "economic": [
                "landuse=industrial",
                "landuse=commercial",
                "landuse=construction",
                "office=company",
                "amenity=marketplace",
                "shop=car",
            ],
            "emergency": [
                "amenity=social_facility",
                "emergency=phone",
                "amenity=shelter",
            ],
        }

        # Determine centroid: prefer full address, then ZIP, then city
        latlon = None

        # First try full address if we have street address info
        state = src.get("metadata") and src.get("metadata", {}).get("state")
        # Default to Missouri for news sources if state not specified
        if not state:
            state = "MO"

        # Try to build the most complete address possible
        meta = src.get("metadata", {})
        address_parts = []

        # Use street address if available
        address1 = meta.get("address1", "")
        # Convert to string and handle None/NaN values
        address1_str = str(address1) if address1 is not None else ""
        if (
            address1_str
            and address1_str.strip()
            and address1_str.lower() not in ["nan", "n/a", ""]
        ):
            address_parts.append(address1_str.strip())

            # Add city if available
            city = src.get("city")
            # Convert to string and handle None/NaN values
            city_str = str(city) if city is not None else ""
            if (
                city_str
                and city_str.strip()
                and city_str.lower() not in ["nan", "n/a", ""]
            ):
                address_parts.append(city_str.strip())
            else:
                # Fallback to canonical name if no city
                name = src.get("canonical_name")
                # Convert to string and handle None/NaN values
                name_str = str(name) if name is not None else ""
                if (
                    name_str
                    and name_str.strip()
                    and name_str.lower() not in ["nan", "n/a", ""]
                ):
                    address_parts.append(name_str.strip())

            # Add state
            address_parts.append(state)

            # Add zip code if available
            zip_code = meta.get("zip", "")
            if (
                zip_code
                and str(zip_code).strip()
                and str(zip_code).lower() not in ["nan", "n/a", ""]
            ):
                address_parts.append(str(zip_code).strip())

            addr = ", ".join(address_parts) if address_parts else None

            if addr:
                # Try cached geocode first
                grow = get_cached_geocode(session, "nominatim", addr)
                if (
                    grow
                    and getattr(grow, "status", None) == "ready"
                    and grow.lat is not None
                ):
                    latlon = (grow.lat, grow.lon)
                    telemetry.log_geocoding_result(
                        source_id, "street_address", addr, True, grow.lat, grow.lon
                    )
                else:
                    # Geocode and cache the result
                    gres = geocode_address_nominatim(addr)
                    if gres:
                        latlon = (gres["lat"], gres["lon"])
                        telemetry.log_geocoding_result(
                            source_id,
                            "street_address",
                            addr,
                            True,
                            gres["lat"],
                            gres["lon"],
                        )
                        set_cached_geocode(
                            session,
                            "nominatim",
                            addr,
                            gres.get("lat"),
                            gres.get("lon"),
                            "city",
                            gres,
                        )
                    else:
                        # Failed to geocode - mark as error
                        set_cached_geocode(
                            session,
                            "nominatim",
                            addr,
                            None,
                            None,
                            None,
                            None,
                            success=False,
                        )

        # If no street address was available, try city + county + state
        if not latlon:
            city = src.get("city")
            county = src.get("county")
            city_str = str(city) if city is not None else ""
            county_str = str(county) if county is not None else ""

            if (
                city_str
                and city_str.strip()
                and city_str.lower() not in ["nan", "n/a", ""]
            ):
                # Build city-based address
                city_parts = [city_str.strip()]

                # Add county if available
                if (
                    county_str
                    and county_str.strip()
                    and county_str.lower() not in ["nan", "n/a", ""]
                ):
                    county_name = county_str.strip()
                    if not county_name.lower().endswith("county"):
                        county_name += " County"
                    city_parts.append(county_name)

                # Add state
                city_parts.append(state)

                city_addr = ", ".join(city_parts)
                print(f"      Trying city-based geocoding: {city_addr}")

                # Try cached geocode first
                grow = get_cached_geocode(session, "nominatim", city_addr)
                if (
                    grow
                    and getattr(grow, "status", None) == "ready"
                    and grow.lat is not None
                ):
                    latlon = (grow.lat, grow.lon)
                    telemetry.log_geocoding_result(
                        source_id, "city_county", city_addr, True, grow.lat, grow.lon
                    )
                else:
                    # Geocode and cache the result
                    gres = geocode_address_nominatim(city_addr)
                    if gres:
                        latlon = (gres["lat"], gres["lon"])
                        telemetry.log_geocoding_result(
                            source_id,
                            "city_county",
                            city_addr,
                            True,
                            gres["lat"],
                            gres["lon"],
                        )
                        set_cached_geocode(
                            session,
                            "nominatim",
                            city_addr,
                            gres.get("lat"),
                            gres.get("lon"),
                            "city",
                            gres,
                        )
                    else:
                        telemetry.log_geocoding_result(
                            source_id,
                            "city_county",
                            city_addr,
                            False,
                            error="Nominatim geocoding failed",
                        )
                        # Failed to geocode - mark as error
                        set_cached_geocode(
                            session,
                            "nominatim",
                            city_addr,
                            None,
                            None,
                            None,
                            None,
                            success=False,
                        )

        # If city-based geocoding failed, try ZIP code lookup
        if not latlon:
            zip_code = src.get("metadata") and src.get("metadata", {}).get("zip")
            if not zip_code:
                zip_code = src.get("metadata") and src.get("metadata", {}).get(
                    "zip_code"
                )

            if zip_code:
                z = str(zip_code)[:5]
                zres = zippopotamus_zip_lookup(z)
                if zres:
                    if isinstance(zres, dict):
                        latlon = (zres["lat"], zres["lon"])
                        telemetry.log_geocoding_result(
                            source_id, "zip_code", z, True, zres["lat"], zres["lon"]
                        )
                else:
                    telemetry.log_geocoding_result(
                        source_id,
                        "zip_code",
                        z,
                        False,
                        error="Zippopotamus lookup failed",
                    )

        if not latlon:
            print("      Could not determine centroid for source; skipping")
            # Calculate processing time
            processing_time = time.time() - start_time
            telemetry.log_enrichment_result(
                source_id,
                False,
                failure_reason="No geocoding method succeeded",
                processing_time_seconds=processing_time,
            )
            return False

        lat, lon = float(latlon[0]), float(latlon[1])
        coverage_miles = radius_miles or 20

        print(f"      Geocoded to: {lat}, {lon} (radius: {coverage_miles} miles)")

        # Use efficient grouped queries
        print("      Querying OSM data...")
        all_results = query_overpass_grouped_categories(
            lat, lon, miles_to_meters(coverage_miles), category_map
        )

        total_inserted = 0

        telemetry.log_osm_query_result(
            source_id=source_id,
            total_elements=sum(len(elements) for elements in all_results.values()),
            categories_data={
                cat: len(all_results.get(cat, [])) for cat in category_map.keys()
            },
            query_groups_used=len(category_map.keys()),
            radius_miles=coverage_miles,
        )

        # Process results for each category and insert into database
        for cat in category_map.keys():
            elements = all_results.get(cat, [])
            print(f"      Processing category: {cat} ({len(elements)} elements)")

            if dry_run:
                print(f"        DRY-RUN: Would process {len(elements)} items for {cat}")
                continue

            inserts = []

            for el in elements:
                tags = el.get("tags", {}) or {}
                name = tags.get("name")
                if not name:
                    continue

                osm_type = el.get("type")
                osm_id = str(el.get("id"))

                # Get coordinates (center for ways, lat/lon for nodes)
                if "center" in el and el["center"]:
                    el_lat = float(el["center"]["lat"])
                    el_lon = float(el["center"]["lon"])
                else:
                    el_lat = float(el.get("lat") or 0)
                    el_lon = float(el.get("lon") or 0)

                name_norm = normalize_name(name)

                distance = None
                try:
                    distance = haversine_miles(lat, lon, el_lat, el_lon)
                except Exception:
                    distance = None

                inserts.append(
                    {
                        "id": str(uuid.uuid4()),
                        "dataset_id": dataset_id,
                        "dataset_label": dataset_label,
                        "source_id": src.get("id"),
                        "data_id": dataset_id,
                        "host_id": (
                            src.get("legacy_host_id")
                            or src.get("source_id")
                            or src.get("id")
                        ),
                        "osm_type": osm_type,
                        "osm_id": osm_id,
                        "name": name,
                        "name_norm": name_norm,
                        "category": cat,
                        "lat": el_lat,
                        "lon": el_lon,
                        "tags": tags,
                        "distance_miles": distance,
                    }
                )

            # Insert into database if we have data
            if inserts:
                print(f"        Inserting {len(inserts)} items for category {cat}")

                # Use ORM for idempotent inserts
                from src.models import Gazetteer

                inserted_count = 0
                for row in inserts:
                    # Check if this exact OSM item already exists
                    # for this source
                    exists_stmt = select(Gazetteer).where(
                        Gazetteer.source_id == row.get("source_id"),
                        Gazetteer.dataset_id == row.get("dataset_id"),
                        Gazetteer.osm_type == row.get("osm_type"),
                        Gazetteer.osm_id == row.get("osm_id"),
                    )
                    exists = session.execute(exists_stmt).scalars().first()
                    if exists:
                        continue

                    # Explicitly set a UUID for the primary key to avoid situations
                    # where ORM-side defaults are not applied and id=None is sent.
                    g = Gazetteer(
                        id=str(uuid.uuid4()),
                        dataset_id=row.get("dataset_id"),
                        dataset_label=row.get("dataset_label"),
                        source_id=row.get("source_id"),
                        data_id=row.get("data_id"),
                        host_id=row.get("host_id"),
                        osm_type=row.get("osm_type"),
                        osm_id=row.get("osm_id"),
                        name=row.get("name"),
                        name_norm=row.get("name_norm"),
                        category=row.get("category"),
                        lat=row.get("lat"),
                        lon=row.get("lon"),
                        tags=row.get("tags"),
                        distance_miles=row.get("distance_miles"),
                    )
                    session.add(g)
                    inserted_count += 1

                if inserted_count > 0:
                    try:
                        session.commit()
                        total_inserted += inserted_count
                        print(f"        Successfully inserted {inserted_count} items")
                    except Exception as e:
                        print(f"        Insert failed: {e}")
                        session.rollback()
                        return False
                else:
                    print("        No new items to insert (all existed)")
            else:
                print(f"        No valid items found for category {cat}")

        print(f"      Total new items inserted: {total_inserted}")

        # Return True if we processed successfully
        # Final telemetry and result reporting
        end_time = time.time()
        processing_time = end_time - start_time

        # (even if 0 items were inserted due to existing data)
        if total_inserted > 0:
            telemetry.log_enrichment_result(
                source_id=source_id,
                success=True,
                total_inserted=total_inserted,
                processing_time_seconds=processing_time,
                failure_reason=None,
            )
            print(
                f"      ✓ Successfully enriched source with "
                f"{total_inserted} gazetteer entries"
            )
            return True
        else:
            # Check if we had any OSM results at all
            total_elements = sum(
                len(all_results.get(cat, [])) for cat in category_map.keys()
            )
            if total_elements == 0:
                telemetry.log_enrichment_result(
                    source_id=source_id,
                    success=False,
                    total_inserted=0,
                    processing_time_seconds=processing_time,
                    failure_reason="No OSM data found",
                )
                print(f"      ⚠ No OSM data found in {coverage_miles}-mile radius")
                return False
            else:
                telemetry.log_enrichment_result(
                    source_id=source_id,
                    success=True,
                    total_inserted=total_elements,
                    processing_time_seconds=processing_time,
                    failure_reason=None,
                )
                print(
                    f"      ✓ Found {total_elements} OSM elements but "
                    f"all already existed in database"
                )
                return True

    except Exception as e:
        end_time = time.time()
        processing_time = end_time - start_time

        telemetry.log_enrichment_result(
            source_id=source_id,
            success=False,
            total_inserted=0,
            processing_time_seconds=processing_time,
            failure_reason=str(e),
        )
        print(f"      Error processing source: {e}")
        return False


def miles_to_meters(miles):
    """Convert miles to meters for OSM queries"""
    return int(miles * 1609.34)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two points."""
    # convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    # Earth radius in miles
    r = 3958.8
    return c * r


def query_overpass(
    lat: float, lon: float, radius_m: int, filters: list[str]
) -> list[dict]:
    """Run an Overpass QL query to fetch nodes/ways matching filters.

    Returns list of elements (dicts) each with tags and center coordinates.
    """
    overpass_url = "https://overpass-api.de/api/interpreter"
    # Build query parts
    parts = []
    for f in filters:
        parts.append(f"node[{f}](around:{radius_m},{lat},{lon});")
        parts.append(f"way[{f}](around:{radius_m},{lat},{lon});")

    q = """
    [out:json][timeout:60];
    (
    %s
    );
    out center tags;
    """ % ("\n".join(parts),)

    # Respectful delay
    time.sleep(1 + random.random() * 1.5)

    try:
        r = requests.post(overpass_url, data={"data": q}, timeout=60)
        if r.status_code == 200:
            return r.json().get("elements", [])
    except Exception:
        return []
    return []


def query_overpass_grouped_categories(
    lat: float, lon: float, radius_m: int, category_map: dict[str, list[str]]
) -> dict[str, list[dict]]:
    """Run 3-4 Overpass queries for logical category groups.

    Much more efficient than 11 individual calls, avoids complexity limits.
    Returns dict mapping category names to lists of elements.
    """

    # Define logical category groups to reduce API calls
    # Fixed historic=* wildcard issue with specific values
    category_groups = {
        "civic_essential": ["schools", "government", "healthcare", "emergency"],
        "commercial_recreation": ["businesses", "economic", "entertainment", "sports"],
        "infrastructure_culture": ["transportation", "landmarks", "religious"],
    }

    # Initialize results for all categories
    results = {cat: [] for cat in category_map.keys()}

    num_individual = len(category_map)
    print(f"    Using 3 optimized grouped queries instead of {num_individual}")

    for group_name, group_categories in category_groups.items():
        # Collect filters for this group
        group_filters = []
        for cat in group_categories:
            if cat in category_map:
                group_filters.extend(category_map[cat])

        if not group_filters:
            continue

        filter_count = len(group_filters)
        print(f"    Querying group '{group_name}' ({filter_count} filters)")

        # Query this group
        group_elements = query_overpass(lat, lon, radius_m, group_filters)
        element_count = len(group_elements)
        print(f"      Group '{group_name}' returned {element_count} elements")

        # Distribute elements back to their specific categories
        for element in group_elements:
            tags = element.get("tags", {}) or {}

            # Check which specific categories this element belongs to
            for cat in group_categories:
                if cat not in category_map:
                    continue

                element_matches_category = False
                for filter_str in category_map[cat]:
                    if "=" not in filter_str:
                        continue
                    key, value = filter_str.split("=", 1)

                    if key in tags:
                        if value == "*" or tags[key] == value:
                            element_matches_category = True
                            break

                # Add element to category if it matches any filter
                if element_matches_category:
                    results[cat].append(element)
            # If no explicit tag matched any category, try a conservative
            # fallback: match by name keywords (e.g. 'school' in name -> schools)
            if not any(element in results[c] for c in group_categories):
                name = tags.get("name", "") or ""
                name_lower = name.lower()
                if name_lower:
                    for cat in group_categories:
                        if cat not in category_map:
                            continue
                        # Look for any of the filter values in the name
                        for filter_str in category_map[cat]:
                            if "=" not in filter_str:
                                continue
                            _, value = filter_str.split("=", 1)
                            if value and value != "*" and value in name_lower:
                                results[cat].append(element)
                                break
                        else:
                            # Also match by simple category name
                            if cat in name_lower:
                                results[cat].append(element)
                                break

    return results


def _fallback_to_individual_queries(
    lat: float, lon: float, radius_m: int, category_map: dict[str, list[str]]
) -> dict[str, list[dict]]:
    """Fallback to individual category queries if grouped queries fail."""
    print("    Using individual queries as fallback...")
    results = {}
    for cat, filters in category_map.items():
        elements = query_overpass(lat, lon, radius_m, filters)
        results[cat] = elements
    return results


def query_overpass_all_categories(
    lat: float, lon: float, radius_m: int, category_map: dict[str, list[str]]
) -> dict[str, list[dict]]:
    """Run a single Overpass QL query to fetch all categories at once.

    Returns dict mapping category names to lists of elements.
    More efficient than multiple separate API calls.
    """
    overpass_url = "https://overpass-api.de/api/interpreter"

    # Collect all unique filters from all categories
    all_filters = []
    for filters in category_map.values():
        all_filters.extend(filters)

    # Remove duplicates while preserving order
    unique_filters = []
    seen = set()
    for f in all_filters:
        if f not in seen:
            unique_filters.append(f)
            seen.add(f)

    # Build query parts for all filters
    parts = []
    for f in unique_filters:
        parts.append(f"node[{f}](around:{radius_m},{lat},{lon});")
        parts.append(f"way[{f}](around:{radius_m},{lat},{lon});")

    q = """
    [out:json][timeout:60];
    (
    %s
    );
    out center tags;
    """ % ("\n".join(parts),)

    # Respectful delay (single call instead of 11)
    time.sleep(1 + random.random() * 1.5)

    # Debug: print the query to see what's wrong
    print(f"    Generated query has {len(parts)} parts")
    if len(unique_filters) > 10:  # Only print for debugging if reasonable size
        print(f"    First few filters: {unique_filters[:5]}")

    try:
        r = requests.post(overpass_url, data={"data": q}, timeout=60)
        if r.status_code != 200:
            print(f"    Overpass API returned status {r.status_code}")
            if r.status_code == 400:
                print("    Query too complex, using individual queries")
                return _fallback_to_individual_queries(lat, lon, radius_m, category_map)
            return {}

        all_elements = r.json().get("elements", [])
        print(f"    Total elements returned: {len(all_elements)}")

        # Group elements by category based on their tags
        results = {cat: [] for cat in category_map.keys()}

        for element in all_elements:
            tags = element.get("tags", {}) or {}

            # Check which categories this element belongs to
            for cat, filters in category_map.items():
                for filter_str in filters:
                    # Parse filter string like "amenity=school" or "sport=*"
                    if "=" not in filter_str:
                        continue
                    key, value = filter_str.split("=", 1)

                    if key in tags:
                        if value == "*" or tags[key] == value:
                            results[cat].append(element)
                            # Don't add element multiple times to same category
                            break

        return results

    except Exception as e:
        print(f"    Error in Overpass query: {e}")
        return {}


def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u2019", "'")
    s = s.replace("\u2018", "'")
    s = s.replace("\u2013", "-")
    s = s.replace("\u2014", "-")
    import re

    s = re.sub(r"[^\w\s'\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def normalize_geocode_key(s: str) -> str:
    if not s:
        return ""
    ks = s.strip().lower()
    ks = ks.replace("\n", " ")
    ks = ks.replace("\t", " ")
    ks = " ".join(ks.split())
    return ks


def set_cached_geocode(
    session,
    provider: str,
    input_str: str,
    lat: float | None,
    lon: float | None,
    precision: str | None,
    raw_response: dict | None,
    success: bool = True,
    ttl_days: int = 365,
):
    """Update the geocode cache row for provider+normalized input."""
    norm = normalize_geocode_key(input_str)
    expires_at = None
    if success:
        expires_at = datetime.utcnow() + timedelta(days=ttl_days)

    # Use SQLAlchemy's update() so types like dict (JSON) and datetime are
    # adapted properly for the underlying DB driver (avoids sqlite3 binding
    # errors when passing Python objects directly).
    stmt = (
        update(GeocodeCache)
        .where(
            GeocodeCache.provider == provider,
            GeocodeCache.normalized_input == norm,
        )
        .values(
            lat=lat,
            lon=lon,
            precision=precision,
            raw_response=raw_response or {},
            status="ready" if success else "error",
            error=None,
            attempt_count=GeocodeCache.attempt_count + 1,
            updated_at=datetime.utcnow(),
            expires_at=expires_at,
        )
    )
    try:
        session.execute(stmt)
        session.commit()
    except Exception:
        session.rollback()


def get_cached_geocode(session, provider: str, input_str: str, wait_timeout: int = 30):
    """Return a GeocodeCache row if present; otherwise claim a row.

    Behavior:
    - If a 'ready' row exists return it immediately.
    - Otherwise attempt to INSERT an 'in_progress' claim (INSERT OR IGNORE).
    - If another process has already claimed it and it's still 'in_progress',
      poll with exponential backoff up to `wait_timeout` seconds and return the
      row when its status changes to 'ready' (or return the current row after
      timeout).

    Callers should perform the external geocode when the returned row has
    `status == 'in_progress'` and then call `set_cached_geocode()` to update
    the row to 'ready'.
    """
    norm = normalize_geocode_key(input_str)

    # If a ready row exists return it immediately
    ready_stmt = select(GeocodeCache).where(
        GeocodeCache.provider == provider,
        GeocodeCache.normalized_input == norm,
        GeocodeCache.status == "ready",
    )
    ready_row = session.execute(ready_stmt).scalars().first()
    if ready_row:
        return ready_row

    # Try to claim a row (INSERT OR IGNORE -> status='in_progress')
    ins_sql = (
        "INSERT OR IGNORE INTO geocode_cache "
        "(provider, input, normalized_input, status, "
        "attempt_count, created_at) "
        "VALUES (:provider, :input, :norm, 'in_progress', 0, "
        "CURRENT_TIMESTAMP)"
    )
    try:
        session.execute(
            text(ins_sql),
            {
                "provider": provider,
                "input": input_str,
                "norm": norm,
            },
        )
        session.commit()
    except Exception:
        session.rollback()

    # Fetch the claimed or existing row
    stmt = select(GeocodeCache).where(
        GeocodeCache.provider == provider,
        GeocodeCache.normalized_input == norm,
    )

    row = session.execute(stmt).scalars().first()
    if not row:
        return None

    # If it's in_progress, poll until ready or timeout using
    # exponential backoff
    if getattr(row, "status", None) == "in_progress" and wait_timeout > 0:
        waited = 0.0
        backoff = 0.5
        while waited < wait_timeout:
            time.sleep(backoff)
            waited += backoff
            backoff = min(backoff * 2, 5.0)
            row = session.execute(stmt).scalars().first()
            if row and getattr(row, "status", None) == "ready":
                return row

    # Return whatever we have (in_progress or ready)
    return row


def main(
    database_url: str,
    dataset_slug: str | None = None,
    address: str | None = None,
    radius_miles: float | None = None,
    dry_run: bool = False,
    publisher: str | None = None,
):
    # Prefer module-level create_engine when tests monkeypatch it. Tests
    # replace scripts.populate_gazetteer.create_engine with a function
    # that returns an in-memory engine. When unmodified, fall back to the
    # DatabaseManager which applies Cloud SQL connector logic and
    # configure the engine appropriately for normal runtime.
    if create_engine is not ORIGINAL_CREATE_ENGINE:
        # Tests provided an engine factory; call it with the database_url
        engine = create_engine(database_url)
        # Ensure ORM tables exist for in-memory engines used by tests
        try:
            from src.models import create_tables

            create_tables(engine)
        except Exception:
            # If create_tables is not available for some reason, continue
            pass
        Session = sessionmaker(bind=engine)
        session = Session()
    else:
        # Import DatabaseManager to handle Cloud SQL connector properly
        from src.models.database import DatabaseManager

        # Use DatabaseManager instead of direct create_engine
        # This ensures Cloud SQL connector is used when needed
        db_manager = DatabaseManager(database_url)
        engine = db_manager.engine  # Keep engine variable for downstream code
        Session = sessionmaker(bind=engine)
        session = Session()

    # Handle on-demand publisher enrichment
    if publisher:
        print(f"🎯 ON-DEMAND ENRICHMENT for publisher UUID: {publisher}")
        try:
            result = enrich_publisher_by_uuid(session, publisher, dry_run=dry_run)
            if result:
                print(f"✅ Successfully enriched publisher UUID {publisher}")
                if not dry_run:
                    session.commit()
                return
            else:
                print(f"❌ No data found for publisher UUID: {publisher}")
                return
        except Exception as e:
            print(f"❌ Error enriching publisher {publisher}: {e}")
            session.rollback()
            return
        finally:
            session.close()

    # Query datasets (optionally filtered)
    ds_q = select(Dataset)
    if dataset_slug:
        ds_q = ds_q.where(Dataset.slug == dataset_slug)

    datasets = session.execute(ds_q).scalars().all()

    # Overpass categories to fetch (map to our internal category label)
    category_map = {
        "schools": [
            "amenity=school",
            "amenity=university",
            "amenity=college",
            "amenity=kindergarten",
        ],
        "government": [
            "amenity=townhall",
            "amenity=courthouse",
            "amenity=police",
            "amenity=fire_station",
            "amenity=post_office",
            "office=government",
        ],
        "healthcare": [
            "amenity=hospital",
            "amenity=clinic",
            "amenity=pharmacy",
            "amenity=dentist",
            "amenity=veterinary",
        ],
        "businesses": [
            "shop=supermarket",
            "shop=department_store",
            "amenity=restaurant",
            "amenity=bank",
            "shop=mall",
            "amenity=fuel",
        ],
        "landmarks": [
            "amenity=library",
            "leisure=park",
            "tourism=attraction",
            "amenity=community_centre",
            "historic=building",
            "historic=monument",
            "historic=memorial",
            "historic=ruins",
            "historic=archaeological_site",
        ],
        "sports": [
            "leisure=sports_centre",
            "leisure=stadium",
            "leisure=pitch",
            "leisure=golf_course",
            "sport=american_football",
            "sport=baseball",
            "sport=basketball",
        ],
        "transportation": [
            "railway=station",
            "aeroway=aerodrome",
            "highway=motorway_junction",
            "amenity=parking",
            "man_made=bridge",
            "public_transport=station",
        ],
        "religious": [
            "amenity=place_of_worship",
            "building=church",
            "building=cathedral",
        ],
        "entertainment": [
            "amenity=theatre",
            "amenity=cinema",
            "amenity=bar",
            "amenity=pub",
            "leisure=fitness_centre",
            "tourism=hotel",
        ],
        "economic": [
            "landuse=industrial",
            "landuse=commercial",
            "landuse=construction",
            "office=company",
            "amenity=marketplace",
            "shop=car",
        ],
        "emergency": [
            "amenity=social_facility",
            "emergency=phone",
            "amenity=shelter",
        ],
    }

    # Quick single-address mode: geocode the provided address and run
    # Overpass queries for each category, printing results. This is a
    # lightweight test mode and will not write to the DB even if
    # dry_run is False (to avoid ambiguous provenance without source).
    if address:
        print(f"Running single-address mode for: {address}")
        gres = geocode_address_nominatim(address)
        if not gres:
            # If the address looks like a 5-digit zip, try zippopotam.us
            if len(address) == 5 and address.isdigit():
                gres = zippopotamus_zip_lookup(address)

        if not gres:
            print("  Could not geocode the address; aborting.")
            return

        lat, lon = float(gres["lat"]), float(gres["lon"])
        coverage_miles = radius_miles or 20

        # Use efficient grouped queries (3 calls instead of 11)
        print("  Using grouped category queries...")
        all_results = query_overpass_grouped_categories(
            lat, lon, miles_to_meters(coverage_miles), category_map
        )

        for cat in category_map.keys():
            elements = all_results.get(cat, [])
            print(f"  Querying Overpass for category: {cat}")
            if not elements:
                print("    no elements returned")
                continue
            print(f"    {len(elements)} elements returned; showing up to 5")
            shown = 0
            for el in elements:
                if shown >= 5:
                    break
                tags = el.get("tags", {}) or {}
                name = tags.get("name")
                if not name:
                    continue
                if "center" in el and el["center"]:
                    el_lat = float(el["center"]["lat"])
                    el_lon = float(el["center"]["lon"])
                else:
                    el_lat = float(el.get("lat") or 0)
                    el_lon = float(el.get("lon") or 0)
                dist = None
                try:
                    dist = haversine_miles(lat, lon, el_lat, el_lon)
                except Exception:
                    dist = None
                print(f"      {name} @ {el_lat},{el_lon} -> {dist:.2f} miles")
                shown += 1
        return

    for ds in datasets:
        print(f"Processing dataset: {ds.slug} ({ds.label})")

        # Get mapped sources for this dataset from dataset_sources join
        meta = MetaData()
        ds_src_tbl = Table("dataset_sources", meta, autoload_with=engine)
        sources_tbl = Table("sources", meta, autoload_with=engine)

        sel = (
            select(sources_tbl, ds_src_tbl.c.legacy_host_id)
            .select_from(
                ds_src_tbl.join(sources_tbl, ds_src_tbl.c.source_id == sources_tbl.c.id)
            )
            .where(ds_src_tbl.c.dataset_id == ds.id)
        )

        rows = session.execute(sel).fetchall()
        processed_count = 0
        skipped_count = 0

        for row in rows:
            # row contains both `sources` table columns and
            # dataset_sources.legacy_host_id (joined in the select)
            # SQLAlchemy Row object supports a _mapping attribute for a
            # mapping-like view which is safe to convert to dict.
            src = dict(row._mapping)
            host_or_name = src.get("canonical_name") or src.get("host")
            print(f"  Source: {host_or_name} ({src.get('id')})")

            # CONSERVATIVE BULK PROCESSING: Check for existing OSM data
            source_id = src.get("id")
            if source_id and has_existing_osm_data(session, ds.id, source_id):
                print("    Skipping: sufficient OSM data already exists")
                skipped_count += 1
                continue

            # Determine centroid: prefer source.city/source.county/zip
            latlon = None
            address_parts = []
            if src.get("city"):
                address_parts.append(src.get("city"))
            if src.get("county"):
                address_parts.append(src.get("county"))
            # No full street address in Source model; rely on ZIP or city
            zip_code = src.get("metadata") and src.get("metadata", {}).get("zip")
            if not zip_code:
                # try 'zip_code' field on candidate_links-like data
                zip_code = src.get("metadata") and src.get("metadata", {}).get(
                    "zip_code"
                )

            if zip_code:
                z = str(zip_code)[:5]
                zres = zippopotamus_zip_lookup(z)
                if zres:
                    if isinstance(zres, dict):
                        latlon = (zres["lat"], zres["lon"])
                    else:
                        latlon = None

            if not latlon:
                # Try geocoding city + state if present in meta; use cache
                state = src.get("metadata") and src.get("metadata", {}).get("state")
                addr = ", ".join(
                    [
                        p
                        for p in (
                            src.get("canonical_name"),
                            src.get("city"),
                            state,
                        )
                        if p
                    ]
                )
                if addr:
                    grow = get_cached_geocode(session, "nominatim", addr)
                    if (
                        grow
                        and getattr(grow, "status", None) == "ready"
                        and grow.lat is not None
                    ):
                        latlon = (grow.lat, grow.lon)
                    else:
                        gres = geocode_address_nominatim(addr)
                        if gres:
                            latlon = (gres["lat"], gres["lon"])
                            set_cached_geocode(
                                session,
                                "nominatim",
                                addr,
                                gres.get("lat"),
                                gres.get("lon"),
                                "city",
                                gres,
                            )

            if not latlon:
                print("    Could not determine centroid for source; skipping")
                continue

            lat, lon = float(latlon[0]), float(latlon[1])
            # Coverage radius: prefer CLI override, then dataset override
            # (not currently modeled), fallback to 20 miles
            coverage_miles = radius_miles or 20

            # Use efficient grouped queries (3 calls instead of 11)
            print("    Using grouped category queries...")
            all_results = query_overpass_grouped_categories(
                lat, lon, miles_to_meters(coverage_miles), category_map
            )

            # Process results for each category and insert into database
            for cat in category_map.keys():
                elements = all_results.get(cat, [])
                print(f"    Processing category: {cat}")
                inserts = []
                for el in elements:
                    tags = el.get("tags", {}) or {}
                    name = tags.get("name")
                    if not name:
                        continue
                    osm_type = el.get("type")
                    osm_id = str(el.get("id"))
                    # center may be present for ways; otherwise use lat/lon
                    # on node
                    if "center" in el and el["center"]:
                        el_lat = float(el["center"]["lat"])
                        el_lon = float(el["center"]["lon"])
                    else:
                        el_lat = float(el.get("lat") or 0)
                        el_lon = float(el.get("lon") or 0)

                    name_norm = normalize_name(name)

                    distance = None
                    try:
                        distance = haversine_miles(lat, lon, el_lat, el_lon)
                    except Exception:
                        distance = None

                    inserts.append(
                        {
                            "id": str(uuid.uuid4()),
                            "dataset_id": ds.id,
                            "dataset_label": ds.label,
                            "source_id": src.get("id"),
                            # Link back to ingestion identifiers
                            "data_id": ds.id,
                            "host_id": (
                                src.get("legacy_host_id")
                                or src.get("source_id")
                                or src.get("id")
                            ),
                            "osm_type": osm_type,
                            "osm_id": osm_id,
                            "name": name,
                            "name_norm": name_norm,
                            "category": cat,
                            "lat": el_lat,
                            "lon": el_lon,
                            "tags": tags,
                            "distance_miles": distance,
                            # Ensure NOT NULL constraint for direct
                            # INSERT path in Postgres
                            "created_at": datetime.utcnow(),
                        }
                    )

                # Debug: how many inserts prepared for this category
                print(f"      Prepared {len(inserts)} inserts for category {cat}")

                # Bulk insert idempotently: prefer INSERT OR IGNORE for sqlite
                if not inserts:
                    continue
                # Dry-run: print what would be inserted and skip DB writes
                if dry_run:
                    print(
                        "      DRY-RUN: %d items for %s (showing first 5):"
                        % (len(inserts), cat)
                    )
                    for r in inserts[:5]:
                        nm = r.get("name")
                        cat_s = r.get("category")
                        lat_s = r.get("lat")
                        lon_s = r.get("lon")
                        dist_s = r.get("distance_miles")
                        print(
                            "        %s (%s) at %s,%s -> %.2f miles"
                            % (nm, cat_s, lat_s, lon_s, dist_s or 0.0)
                        )
                    continue

                meta = MetaData()
                gaz_tbl = Table("gazetteer", meta, autoload_with=engine)
                try:
                    if "sqlite" in engine.dialect.name:
                        # Use ORM for idempotent inserts so SQLAlchemy handles
                        # JSON/datetime conversion and defaults.
                        from src.models import Gazetteer

                        for row in inserts:
                            exists_stmt = select(Gazetteer).where(
                                Gazetteer.source_id == row.get("source_id"),
                                Gazetteer.dataset_id == row.get("dataset_id"),
                                Gazetteer.osm_type == row.get("osm_type"),
                                Gazetteer.osm_id == row.get("osm_id"),
                            )
                            exists = session.execute(exists_stmt).scalars().first()
                            if exists:
                                continue

                            g = Gazetteer(
                                dataset_id=row.get("dataset_id"),
                                dataset_label=row.get("dataset_label"),
                                source_id=row.get("source_id"),
                                data_id=row.get("data_id"),
                                host_id=row.get("host_id"),
                                osm_type=row.get("osm_type"),
                                osm_id=row.get("osm_id"),
                                name=row.get("name"),
                                name_norm=row.get("name_norm"),
                                category=row.get("category"),
                                lat=row.get("lat"),
                                lon=row.get("lon"),
                                tags=row.get("tags"),
                                distance_miles=row.get("distance_miles"),
                            )
                            session.add(g)

                        try:
                            session.commit()
                        except Exception as e:
                            print(f"      ORM bulk insert failed: {e}")
                            session.rollback()
                    else:
                        # Defensive: ensure created_at exists for all rows
                        now_ts = datetime.utcnow()
                        for r in inserts:
                            r.setdefault("created_at", now_ts)
                        session.execute(insert(gaz_tbl), inserts)
                        session.commit()
                except Exception as e:
                    print(f"      Insert failed: {e}")
                    session.rollback()

            # Track successful processing
            processed_count += 1

        # Summary of bulk processing efficiency
        total_sources = processed_count + skipped_count
        if total_sources > 0:
            print("\n  BULK PROCESSING SUMMARY:")
            print(f"    Sources processed: {processed_count}")
            print(f"    Sources skipped (existing data): {skipped_count}")
            print(f"    Total sources: {total_sources}")
            print(
                f"    API call reduction: {skipped_count}/{total_sources} "
                f"sources had existing data"
            )

    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="sqlite:///data/mizzou.db")
    parser.add_argument(
        "--dataset",
        default=None,
        help=("Dataset slug to process (optional)"),
    )
    parser.add_argument(
        "--address",
        default=None,
        help=("Explicit address to geocode and run Overpass against (optional)"),
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=None,
        help=("Coverage radius in miles to use for Overpass queries."),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=("Do not write to DB; just print results from Overpass."),
    )
    args = parser.parse_args()

    # If an explicit address is supplied, perform a lightweight single-run
    # that geocodes the address, queries Overpass, and (by default) prints
    # results without inserting unless --dry-run is false.
    if args.address:
        main(
            args.db,
            dataset_slug=args.dataset,
            address=args.address,
            radius_miles=args.radius,
            dry_run=args.dry_run,
        )
    else:
        main(
            args.db,
            dataset_slug=args.dataset,
            address=None,
            radius_miles=args.radius,
            dry_run=args.dry_run,
        )
