"""
Publisher-Specific Geographic Filtering for MizzouNewsCrawler
===========================================================

This enhanced version uses actual publisher locations from publinks.csv
to create location-specific gazetteers based on each publisher's coverage area.
Enhanced with OpenStreetMap data for local businesses, schools, and landmarks.
"""

import random
import re
import time
from typing import Any

import pandas as pd

# os not required
import requests


class PublisherGeoFilter:
    """
    Geographic filter that creates publisher-specific gazetteers based on
    actual publisher locations and estimated coverage areas.
    """

    def __init__(self, publinks_path: str = "sources/publinks.csv"):
        self.publinks_path = publinks_path
        self.publishers = {}
        self.publisher_gazetteers = {}

        # Coverage radius by media type (in miles)
        self.coverage_radius_by_type = {
            "daily": {"metro": 30, "small_city": 18},  # Daily papers
            "weekly": 12,  # Weekly papers
            "bi-weekly": 12,  # Bi-weekly papers
            "tri-weekly": 15,  # Tri-weekly papers
            "video_broadcast": 45,  # TV stations
            "audio_broadcast": 40,  # Radio stations
            "digital_native": 25,  # Digital-first outlets
            "print native": 15,  # Default for print
        }

        # Dynamic geographic data for building gazetteers (per publisher)
        self.publisher_local_geography = {}
        self._load_publisher_data()

        # OSM Overpass API endpoint
        self.overpass_url = "http://overpass-api.de/api/interpreter"

        # Define OSM queries for different entity types
        self.osm_queries = {
            "schools": ["amenity=school", "amenity=university", "amenity=college"],
            "government": [
                "amenity=townhall",
                "amenity=courthouse",
                "amenity=police",
                "amenity=fire_station",
            ],
            "healthcare": [
                "amenity=hospital",
                "amenity=clinic",
                "amenity=doctors",
                "amenity=pharmacy",
            ],
            "businesses": [
                "shop=supermarket",
                "shop=department_store",
                "amenity=restaurant",
                "amenity=bank",
            ],
            "landmarks": [
                "amenity=library",
                "leisure=park",
                "tourism=attraction",
                "amenity=community_centre",
            ],
        }

    def _normalize_name(self, s: str) -> str:
        """Normalize a place or institution name for matching.

        This mirrors the inline normalize_name used in the gazetteer builder
        but is available to other methods (detection, matching).
        """
        if not s:
            return ""
        s = s.replace("\u2019", "'")
        s = s.replace("\u2018", "'")
        s = s.replace("\u2013", "-")
        s = s.replace("\u2014", "-")
        s = re.sub(r"[^\w\s'-]", " ", s)
        s = re.sub(r"\s+", " ", s)
        return s.strip().lower()

    def _load_state_lookup_tables(self):
        """Load state-specific patterns and institutions from lookup tables."""
        state_patterns = {}
        state_institutions = {}

        # Load regional patterns
        try:
            patterns_df = pd.read_csv("lookups/state_regional_patterns.csv")
            for _, row in patterns_df.iterrows():
                state = row["state"].lower()
                pattern = row["region_pattern"].lower()
                if state not in state_patterns:
                    state_patterns[state] = []
                state_patterns[state].append(pattern)
        except Exception as e:
            print(f"Warning: Could not load regional patterns: {e}")

        # Load institutions
        try:
            institutions_df = pd.read_csv("lookups/state_institutions.csv")
            for _, row in institutions_df.iterrows():
                state = row["state"].lower()
                institution = row["institution_name"].lower()
                if state not in state_institutions:
                    state_institutions[state] = []
                state_institutions[state].append(institution)
        except Exception as e:
            print(f"Warning: Could not load institutions: {e}")

        return state_patterns, state_institutions

    def _load_publisher_local_geography(
        self, host_id: str, city: str, county: str, state: str = ""
    ):
        """Load geographic data specific to a publisher's location.

        This creates location-specific gazetteers based on the publisher's
        actual city, county, and state rather than hardcoded Missouri data.
        """
        if host_id in self.publisher_local_geography:
            return  # Already loaded

        # Normalize location names
        city = city.strip().lower() if city else ""
        county = county.strip().lower() if county else ""
        state = state.strip().lower() if state else ""

        # Initialize geography for this publisher
        local_geography = {
            "cities": {},
            "counties": {},
            "regions": {},
            "institutions": {},
        }

        # If we have city information, create regional patterns
        if city:
            # Add the publisher's city
            local_geography["cities"][city] = None  # Coordinates TBD from OSM

            # Create regional patterns based on the city
            if county:
                # Add county-based regions
                local_geography["regions"][f"{county} county"] = None
                if state:
                    county_state = f"{county} county {state}"
                    local_geography["regions"][county_state] = None

            # Add common regional patterns for the area
            if city and state:
                local_geography["regions"][f"{city} {state}"] = None
                local_geography["regions"][f"{city} area"] = None
                local_geography["regions"][f"greater {city}"] = None

            # Add state-specific patterns if we have state info
            if state:
                # Load state-specific patterns from lookup tables
                lookup_data = self._load_state_lookup_tables()
                state_patterns, state_institutions = lookup_data

                # Add state-specific regional patterns from lookup table
                if state in state_patterns:
                    for pattern in state_patterns[state]:
                        local_geography["regions"][pattern] = None

                # Add state-specific institutions from lookup table
                if state in state_institutions:
                    for institution in state_institutions[state]:
                        local_geography["institutions"][institution] = None

                # State university patterns (most states have these)
                univ_key = f"university of {state}"
                state_univ_key = f"{state} state university"
                state_key = f"{state} university"
                local_geography["institutions"][univ_key] = None
                local_geography["institutions"][state_univ_key] = None
                local_geography["institutions"][state_key] = None

        self.publisher_local_geography[host_id] = local_geography

    def _get_publisher_local_signals(self, host_id: str) -> list:
        """Get local institutional signals for a specific publisher."""
        if host_id not in self.publisher_local_geography:
            return []

        geography = self.publisher_local_geography[host_id]
        signals = []

        # Collect all local terms for this publisher
        signals.extend(geography["cities"].keys())
        signals.extend(geography["counties"].keys())
        signals.extend(geography["regions"].keys())
        signals.extend(geography["institutions"].keys())

        return [signal for signal in signals if signal]  # Filter empties

    def _load_publisher_data(self):
        """Load publisher data from publinks.csv."""
        try:
            df = pd.read_csv(self.publinks_path)
            for _, row in df.iterrows():
                # Convert host_id to string, handling float values
                host_id = row["host_id"]
                if pd.isna(host_id):
                    continue
                else:
                    host_id = str(int(float(host_id)))

                # Handle NaN values in text fields
                city = row.get("city", "")
                if pd.isna(city):
                    city = ""
                else:
                    city = str(city)

                county = row.get("county", "")
                if pd.isna(county):
                    county = ""
                else:
                    county = str(county)

                self.publishers[host_id] = {
                    "name": str(row.get("name", "")),
                    "city": city,
                    "county": county,
                    "address1": str(row.get("address1", "")),
                    "address2": str(row.get("address2", "")),
                    "zip": str(row.get("zip", "")),
                    "frequency": str(row.get("frequency", "")),
                    "media_type": str(row.get("media_type", "")),
                    "coverage_radius": self._calculate_coverage_radius(row),
                    # Load cached gazetteer data if available
                    "cached_geographic_entities": self._parse_cached_list(
                        row.get("cached_geographic_entities", "")
                    ),
                    "cached_institutions": self._parse_cached_list(
                        row.get("cached_institutions", "")
                    ),
                    # OSM category columns
                    "cached_schools": self._parse_cached_list(
                        row.get("cached_schools", "")
                    ),
                    "cached_government": self._parse_cached_list(
                        row.get("cached_government", "")
                    ),
                    "cached_healthcare": self._parse_cached_list(
                        row.get("cached_healthcare", "")
                    ),
                    "cached_businesses": self._parse_cached_list(
                        row.get("cached_businesses", "")
                    ),
                    "cached_landmarks": self._parse_cached_list(
                        row.get("cached_landmarks", "")
                    ),
                }
        except Exception as e:
            print(
                f"Warning: Could not load publisher data from {self.publinks_path}: {e}"
            )
            self.publishers = {}

    def _parse_cached_list(self, cached_string: str) -> list:
        """Parse a pipe-separated string into a list."""
        if pd.isna(cached_string) or not cached_string.strip():
            return []
        items = str(cached_string).split("|")
        return [item.strip() for item in items if item.strip()]

    def _list_to_cached_string(self, items: list) -> str:
        """Convert a list to pipe-separated string for CSV storage."""
        if not items:
            return ""
        return "|".join(sorted(items))

    def save_gazetteer_cache(
        self,
        host_id: str,
        geographic_entities: list,
        institutions: list,
        osm_entities: dict = None,
    ):
        """Save computed gazetteer data back to publinks CSV for caching."""
        try:
            df = pd.read_csv(self.publinks_path)

            # Find the publisher row by host ID and update with cached data
            # Convert host_id to int if it's numeric for proper matching
            try:
                host_id_val = int(host_id)
            except ValueError:
                host_id_val = host_id

            mask = df["host_id"] == host_id_val
            if mask.any():
                geo_string = self._list_to_cached_string(geographic_entities)
                inst_string = self._list_to_cached_string(institutions)

                # Ensure columns exist as string type to avoid dtype warnings
                if "cached_geographic_entities" not in df.columns:
                    df["cached_geographic_entities"] = ""
                if "cached_institutions" not in df.columns:
                    df["cached_institutions"] = ""

                df.loc[mask, "cached_geographic_entities"] = geo_string
                df.loc[mask, "cached_institutions"] = inst_string

                # Save OSM categories in separate columns
                if osm_entities:
                    for category, entities in osm_entities.items():
                        column_name = f"cached_{category}"
                        # Ensure column exists as string type
                        if column_name not in df.columns:
                            df[column_name] = ""
                        entity_string = self._list_to_cached_string(entities)
                        df.loc[mask, column_name] = entity_string

                # Save back to CSV
                df.to_csv(self.publinks_path, index=False)
                print(f"Updated cached gazetteer for {host_id}")
        except Exception as e:
            print(f"Warning: Could not save gazetteer cache for {host_id}: {e}")

    def _query_osm_entities(
        self,
        lat: float,
        lon: float,
        radius_miles: int,
        entity_type: str,
    ) -> list[str]:
        """Query OpenStreetMap for entities within radius of coordinates.

        Uses retries with exponential backoff and jitter to handle errors.
        """
        max_retries = 3
        base_delay = 2.0  # Start with 2 seconds

        for attempt in range(max_retries):
            try:
                # Convert miles to meters for OSM query
                radius_meters = int(radius_miles * 1609.34)

                # Build Overpass query for this entity type
                queries = self.osm_queries.get(entity_type, [])
                if not queries:
                    return []

                # Construct Overpass QL query
                query_parts = []
                for query in queries:
                    query_parts.append(
                        f"node[{query}](around:{radius_meters},{lat},{lon});"
                    )
                    query_parts.append(
                        f"way[{query}](around:{radius_meters},{lat},{lon});"
                    )

                overpass_query = f"""
                [out:json][timeout:45];
                (
                    {" ".join(query_parts)}
                );
                out center meta;
                """

                # Add delay before request (progressive backoff)
                if attempt > 0:
                    # Exponential backoff + jitter
                    delay = base_delay * (2**attempt) + 1
                    print(f"    Retrying {entity_type} after {delay:.1f}s delay...")
                    time.sleep(delay)

                # Make API request with longer timeout
                response = requests.post(
                    self.overpass_url, data={"data": overpass_query}, timeout=60
                )

                if response.status_code == 200:
                    data = response.json()
                    entities = []

                    for element in data.get("elements", []):
                        name = element.get("tags", {}).get("name")
                        # Filter short/empty names
                        if name and len(name.strip()) > 2:
                            entities.append(name.strip().lower())

                    # Remove duplicates and return
                    return list(set(entities))

                elif response.status_code in [429, 504, 503, 502]:
                    # Rate limited or server error - retry with backoff
                    print(
                        f"OSM server busy ({response.status_code}) for "
                        f"{entity_type}, attempt {attempt + 1}/{max_retries}"
                    )
                    if attempt < max_retries - 1:
                        continue
                    else:
                        print(f"Max retries reached for {entity_type}")
                        return []
                else:
                    print(f"OSM query failed for {entity_type}: {response.status_code}")
                    return []

            except requests.exceptions.Timeout:
                print(
                    f"OSM query timeout for {entity_type}, "
                    f"attempt {attempt + 1}/{max_retries}"
                )
                if attempt < max_retries - 1:
                    continue
                else:
                    return []
            except Exception as e:
                print(f"Warning: OSM query failed for {entity_type}: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    return []

        return []

    def _get_osm_entities_for_publisher(
        self,
        lat: float,
        lon: float,
        radius: int,
    ) -> dict[str, list[str]]:
        """Get all OSM entities for a publisher location."""
        all_entities = {}

        for entity_type in self.osm_queries.keys():
            print(f"  Querying OSM for {entity_type}...")
            entities = self._query_osm_entities(lat, lon, radius, entity_type)
            all_entities[entity_type] = entities

            # Be more respectful to OSM servers - delay with jitter
            delay = 3 + random.uniform(0, 2)  # 3-5 second random delay
            time.sleep(delay)

        return all_entities

    def _calculate_coverage_radius(self, publisher_row) -> int:
        """Calculate coverage radius for a publisher based on type and size."""
        media_type = str(publisher_row.get("media_type", "")).lower()
        frequency = str(publisher_row.get("frequency", "")).lower()
        city = str(publisher_row.get("city", "")).lower()

        # Determine if it's a metro market
        metro_cities = {"kansas city", "st. louis", "saint louis", "springfield"}
        is_metro = any(metro in city for metro in metro_cities)

        # Calculate radius based on media type
        if media_type == "video_broadcast":
            return self.coverage_radius_by_type["video_broadcast"]
        elif media_type == "audio_broadcast":
            return self.coverage_radius_by_type["audio_broadcast"]
        elif media_type == "digital_native":
            return self.coverage_radius_by_type["digital_native"]
        elif "daily" in frequency:
            return self.coverage_radius_by_type["daily"][
                "metro" if is_metro else "small_city"
            ]
        elif "weekly" in frequency:
            return self.coverage_radius_by_type["weekly"]
        elif "bi-weekly" in frequency:
            return self.coverage_radius_by_type["bi-weekly"]
        elif "tri-weekly" in frequency:
            return self.coverage_radius_by_type["tri-weekly"]
        else:
            return self.coverage_radius_by_type["print native"]

    def _calculate_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Calculate distance between two points (approximate) in miles."""
        # Simple distance calculation (approximate for moderate latitudes)
        lat_diff = lat1 - lat2
        lon_diff = lon1 - lon2
        # Rough conversion: 1 degree ≈ 69 miles
        return ((lat_diff**2) + (lon_diff**2)) ** 0.5 * 69

    def _get_zipcode_coordinates(self, zipcode: str) -> tuple:
        """Get coordinates for a zipcode using a REST API as fallback."""
        try:
            import requests

            # Clean up zipcode (remove any non-numeric characters)
            clean_zip = "".join(filter(str.isdigit, str(zipcode)))
            if len(clean_zip) < 5:
                return None

            # Use first 5 digits for lookup
            zip5 = clean_zip[:5]

            # Use the free zippopotam.us API for zipcode lookup
            response = requests.get(f"http://api.zippopotam.us/us/{zip5}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                lat = float(data["places"][0]["latitude"])
                lon = float(data["places"][0]["longitude"])
                print(f"Found coordinates for zipcode {zip5}: ({lat}, {lon})")
                return (lat, lon)
        except Exception as e:
            print(f"Warning: Could not get coordinates for zipcode {zipcode}: {e}")
        return None

    def build_publisher_gazetteer(self, host_id: str) -> set[str]:
        """Build a gazetteer for publisher based on location and coverage."""
        if host_id not in self.publishers:
            return set()

        if host_id in self.publisher_gazetteers:
            return self.publisher_gazetteers[host_id]

        publisher = self.publishers[host_id]

        # Check for cached gazetteer data first
        cached_geo = publisher.get("cached_geographic_entities", [])
        cached_inst = publisher.get("cached_institutions", [])
        cached_schools = publisher.get("cached_schools", [])
        cached_govt = publisher.get("cached_government", [])
        cached_health = publisher.get("cached_healthcare", [])
        cached_biz = publisher.get("cached_businesses", [])
        cached_landmarks = publisher.get("cached_landmarks", [])

        # Use cached data if basic geographic entities are available
        if cached_geo:
            gazetteer = set(
                cached_geo
                + cached_inst
                + cached_schools
                + cached_govt
                + cached_health
                + cached_biz
                + cached_landmarks
            )
            self.publisher_gazetteers[host_id] = gazetteer
            print(
                f"Using cached gazetteer for {host_id} "
                f"({len(gazetteer)} locations: {len(cached_geo)} geo, "
                f"{len(cached_inst)} institutions, {len(cached_schools)} "
                f"schools, {len(cached_govt)} govt, {len(cached_health)} "
                f"health, {len(cached_biz)} businesses, "
                f"{len(cached_landmarks)} landmarks)"
            )
            return gazetteer

        # Build fresh gazetteer
        pub_city = publisher["city"].lower()
        pub_county = publisher["county"].lower()
        pub_state = publisher.get("state", "").lower()  # Get state
        coverage_radius = publisher["coverage_radius"]

        # Load publisher-specific geography
        self._load_publisher_local_geography(host_id, pub_city, pub_county, pub_state)

        gazetteer = set()
        geographic_entities = set()
        institutions = set()

        # Always include publisher's own city and county (normalized)
        def normalize_name(s: str) -> str:
            if not s:
                return ""
            # Normalize common curly apostrophes and whitespace, lower-case
            s = s.replace("\u2019", "'")  # right single quote → '
            s = s.replace("\u2018", "'")  # left single quote → '
            s = s.replace("\u2013", "-")
            s = s.replace("\u2014", "-")
            s = re.sub(r"[^\w\s'-]", " ", s)
            s = re.sub(r"\s+", " ", s)
            return s.strip().lower()

        pub_city_norm = normalize_name(pub_city)
        pub_county_norm = normalize_name(pub_county)

        geographic_entities.add(pub_city_norm)
        geographic_entities.add(pub_county_norm)
        if pub_county_norm:
            geographic_entities.add(f"{pub_county_norm} county")

        # Add simple aliases for publisher city (e.g., G'ville, gville)
        def city_aliases(city: str) -> set[str]:
            aliases = set()
            if not city:
                return aliases
            aliases.add(city)
            # common contraction: replace 'gainesville' -> "g'ville" and
            # 'gville'
            if "gainesville" in city:
                aliases.add("g'ville")
                aliases.add("gville")
                aliases.add("gainsville")
            # handle common "saint" abbreviations
            if city.startswith("saint "):
                aliases.add(city.replace("saint ", "st. "))
                aliases.add(city.replace("saint ", "st "))
            if city.startswith("st. "):
                aliases.add(city.replace("st. ", "st "))
                aliases.add(city.replace("st. ", "saint "))
            # apostrophe variants
            if "'" in city and "’" not in city:
                aliases.add(city.replace("'", "’"))
            # fallback: abbreviation without punctuation
            aliases.add(re.sub(r"[^a-z0-9]", "", city))
            return {a for a in aliases if a}

        geographic_entities.update(city_aliases(pub_city_norm))

        # Get publisher's coordinates with fallback hierarchy
        pub_coords = None
        local_geography = self.publisher_local_geography.get(host_id, {})
        local_cities = local_geography.get("cities", {})
        local_regions = local_geography.get("regions", {})

        if pub_city in local_cities:
            pub_coords = local_cities[pub_city]
            print(f"Using city coordinates for {pub_city}")
        elif f"{pub_county} county" in local_regions:
            pub_coords = local_regions[f"{pub_county} county"]
            print(f"Using county coordinates for {pub_county} county")
        else:
            # Fallback to zipcode-based coordinates
            pub_zip = publisher.get("zip", "").strip()
            if pub_zip:
                pub_coords = self._get_zipcode_coordinates(pub_zip)
                if pub_coords:
                    print(f"Using zipcode coordinates for {pub_zip}")
                else:
                    print(
                        "Warning: Could not determine coordinates for"
                        f" publisher {host_id} (city: {pub_city})"
                    )
            else:
                print(
                    "Warning: No city, county, or zipcode available for"
                    f" publisher {host_id}"
                )

        if pub_coords:
            pub_lat, pub_lon = pub_coords

            # Add local geographic patterns for this publisher
            local_signals = self._get_publisher_local_signals(host_id)
            geographic_entities.update(local_signals)

            # OSM-based entities (dynamic by location) will be added below

            # Add OSM entities within coverage radius
            print(f"Fetching OSM entities for {host_id}...")
            osm_entities = self._get_osm_entities_for_publisher(
                pub_lat, pub_lon, coverage_radius
            )

            # Separate OSM entities by category
            osm_schools = set(osm_entities.get("schools", []))
            osm_government = set(osm_entities.get("government", []))
            osm_healthcare = set(osm_entities.get("healthcare", []))
            osm_businesses = set(osm_entities.get("businesses", []))
            osm_landmarks = set(osm_entities.get("landmarks", []))

            # Add schools to institutions, others to geographic entities
            institutions.update(osm_schools)
            geographic_entities.update(osm_government)
            geographic_entities.update(osm_healthcare)
            geographic_entities.update(osm_businesses)
            geographic_entities.update(osm_landmarks)

        # Combine all entities for final gazetteer
        # Normalize all gazetteer entries before returning
        def normalize_list_entries(entries: set[str]) -> set[str]:
            out = set()
            for e in entries:
                if not e:
                    continue
                out.add(normalize_name(e))
            return {o for o in out if o}

        geographic_entities = normalize_list_entries(geographic_entities)
        institutions = normalize_list_entries(institutions)

        gazetteer = geographic_entities.union(institutions)

        # Save computed gazetteer to cache with separate OSM categories
        osm_cache_data = {
            "schools": (list(osm_schools) if "osm_schools" in locals() else []),
            "government": (
                list(osm_government) if "osm_government" in locals() else []
            ),
            "healthcare": (
                list(osm_healthcare) if "osm_healthcare" in locals() else []
            ),
            "businesses": (
                list(osm_businesses) if "osm_businesses" in locals() else []
            ),
            "landmarks": (list(osm_landmarks) if "osm_landmarks" in locals() else []),
        }

        self.save_gazetteer_cache(
            host_id, list(geographic_entities), list(institutions), osm_cache_data
        )

        # Cache the gazetteer
        self.publisher_gazetteers[host_id] = gazetteer
        print(
            f"Built fresh gazetteer for {host_id} "
            f"({len(gazetteer)} total: {len(geographic_entities)} "
            f"geographic + {len(institutions)} institutions)"
        )
        if "osm_schools" in locals():
            print(
                "  OSM breakdown: "
                f"{len(osm_schools)} schools, {len(osm_government)} govt, "
                f"{len(osm_healthcare)} health, {len(osm_businesses)} "
                f"businesses, {len(osm_landmarks)} landmarks)"
            )
        return gazetteer

    def detect_geographic_signals(
        self,
        text: str,
        host_id: str,
        title: str | None = None,
        authors: str | None = None,
        authors_count: int | None = None,
    ) -> dict[str, Any]:
        """Detect geographic signals using publisher-specific gazetteer.

        Optional `title` and `authors` can be provided by scrapers to
        improve byline/title-based signals.
        """
        if not text or pd.isna(text):
            return {
                "has_geographic_signals": False,
                "detected_locations": [],
                "location_count": 0,
                "signal_strength": 0.0,
                "coverage_radius": (
                    self.publishers.get(host_id, {}).get("coverage_radius", 0)
                ),
            }

        # Get publisher-specific gazetteer
        gazetteer = self.build_publisher_gazetteer(host_id)
        if not gazetteer:
            return {
                "has_geographic_signals": False,
                "detected_locations": [],
                "location_count": 0,
                "signal_strength": 0.0,
                "coverage_radius": (
                    self.publishers.get(host_id, {}).get("coverage_radius", 0)
                ),
            }

        # Normalize text similarly to gazetteer entries
        def normalize_text(s: str) -> str:
            if not s:
                return ""
            s = s.replace("\u2019", "'")
            s = s.replace("\u2018", "'")
            s = s.replace("\u2013", "-")
            s = s.replace("\u2014", "-")
            s = re.sub(r"[^\w\s'-]", " ", s)
            s = re.sub(r"\s+", " ", s)
            return s.strip().lower()

        text_lower = normalize_text(str(text))
        text_original = str(text)
        detected_locations = []

        # Sort gazetteer by length (longest first) for better matching
        sorted_locations = sorted(gazetteer, key=len, reverse=True)

        # Find matches using word boundaries but also allow compact alias
        for location in sorted_locations:
            if not location:
                continue
            # exact word-boundary match
            pattern = r"\b" + re.escape(location) + r"\b"
            if re.search(pattern, text_lower, re.IGNORECASE):
                detected_locations.append(location)
                continue
            # fallback: compact match (no spaces/punctuation) for aliases
            compact_loc = re.sub(r"[^a-z0-9]", "", location)
            compact_text = re.sub(r"[^a-z0-9]", "", text_lower)
            if compact_loc and compact_loc in compact_text:
                detected_locations.append(location)

        # Remove duplicates while preserving order
        unique_locations = list(dict.fromkeys(detected_locations))

        # Heuristic extractions for place-like patterns not in gazetteer
        def extract_place_from_patterns(orig_text: str) -> list[str]:
            candidates = []
            # Fire department pattern
            m = re.search(
                r"([A-Z][\w'`\-]+(?:\s+[A-Z][\w'`\-]+)*)\s+"
                r"(?:Membership\s+)?Fire Department",
                orig_text,
            )
            if m:
                candidates.append(m.group(1))
                first_tok = m.group(1).split()[0]
                if first_tok:
                    candidates.append(first_tok)

            # Members of pattern
            m2 = re.search(r"Members of the ([A-Z][\w'`\-]+)", orig_text)
            if m2:
                candidates.append(m2.group(1))

            # Simple "in <Place>" patterns
            m3 = re.search(r"\bin\s+([A-Z][\w'`\-]+)\b", orig_text)
            if m3:
                candidates.append(m3.group(1))

            # Filter out obvious non-place tokens
            months = {
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            }
            blacklist = {
                "class",
                "team",
                "season",
                "game",
                "round",
                "match",
                "tournament",
                "district",
                "division",
                "group",
                "state",
                "county",
            }

            filtered = []
            for c in candidates:
                norm_c = c.strip().lower()
                if norm_c in months:
                    continue
                if norm_c in blacklist:
                    continue
                if len(re.sub(r"[^a-z0-9]", "", norm_c)) <= 2:
                    continue
                filtered.append(c)
            return filtered

        for raw_place in extract_place_from_patterns(text_original):
            norm = self._normalize_name(raw_place)
            if norm and norm not in unique_locations and len(norm) > 2:
                unique_locations.append(norm)

        # Calculate signal strength
        location_count = len(unique_locations)

        publisher_city = self.publishers.get(host_id, {}).get("city", "")
        publisher_city_norm = (
            publisher_city.replace("\u2019", "'") if publisher_city else ""
        )

        if location_count == 0:
            signal_strength = 0.0
        elif location_count == 1:
            signal_strength = 0.4
        elif location_count <= 3:
            signal_strength = 0.7
        else:
            signal_strength = 0.9

        # Boost single-location when it matches gazetteer
        if location_count == 1:
            loc = unique_locations[0]
            try:
                compact_loc = re.sub(r"[^a-z0-9]", "", loc)

                def compact(s: str) -> str:
                    return re.sub(r"[^a-z0-9]", "", s)

                is_geo = any(
                    (g in loc) or (loc in g) or (compact_loc == compact(g))
                    for g in gazetteer
                )
            except Exception:
                is_geo = False

            if is_geo:
                signal_strength = max(signal_strength, 0.6)

        # Publisher city boost
        try:
            pub_city_norm = self._normalize_name(publisher_city_norm)
        except Exception:
            pub_city_norm = publisher_city_norm

        if pub_city_norm:
            compact_pub = re.sub(r"[^a-z0-9]", "", pub_city_norm)
            if pub_city_norm in unique_locations or any(
                compact_pub == re.sub(r"[^a-z0-9]", "", ul) for ul in unique_locations
            ):
                signal_strength = max(signal_strength, 0.7)

        # Boost signal if locations appear early in title/headline
        combined_title = title if title else text
        first_100_chars = normalize_text(str(combined_title))[:100]
        title_matches = sum(
            1
            for loc in unique_locations
            if re.search(r"\b" + re.escape(loc) + r"\b", first_100_chars)
        )
        if title_matches > 0:
            signal_strength = min(1.0, signal_strength + 0.1)

        # Byline signal: prefer explicit authors value, fallback to regex.
        # We'll also check whether the byline area contains wire indicators
        # (AP, Reuters, Associated Press, etc.). If the byline or explicit
        # authors are present and there are no nearby wire markers, boost.
        byline_signal = 0.0
        byline_match = re.search(r"\bBy[:\s]+([A-Z][a-zA-Z.'\- ]{1,80})", text_original)
        if authors and isinstance(authors, str) and authors.strip():
            # Base strong signal for an explicit author
            byline_signal = max(byline_signal, 0.95)
            # strengthen if the same author appears multiple times on this host
            try:
                if isinstance(authors_count, int) and authors_count > 1:
                    byline_signal = max(byline_signal, 0.98)
            except Exception:
                pass
        elif byline_match:
            byline_signal = max(byline_signal, 0.8)

        # Detect wire indicators near the byline or author mention; absence
        # of such indicators is a positive signal for local byline.
        near_indicators = [
            "ap ",
            "associated press",
            "ap-wire",
            "reuters",
            "bloomberg",
            "npr news",
            "cnn",
        ]
        try:
            if byline_match:
                start, end = byline_match.span()
                snippet = text_original[
                    max(0, start - 80) : min(len(text_original), end + 80)
                ].lower()
                if not any(w in snippet for w in near_indicators):
                    byline_signal = max(byline_signal, 0.9)
            elif authors and isinstance(authors, str) and authors.strip():
                idx = text_original.lower().find(authors.strip().lower())
                if idx >= 0:
                    snippet = text_original[
                        max(0, idx - 80) : min(
                            len(text_original), idx + len(authors) + 80
                        )
                    ].lower()
                    if not any(w in snippet for w in near_indicators):
                        byline_signal = max(byline_signal, 0.9)
        except Exception:
            pass

        # publisher-name/byline detection
        pub = self.publishers.get(host_id, {})
        pub_name = (pub.get("name") or "").strip().lower()
        if pub_name and pub_name in text_lower:
            byline_signal = max(byline_signal, 0.9)

        # Treat generic 'Staff'/'Editor' bylines as local indicators.
        # Also, if the byline text is a fuzzy match for the publisher name
        # (e.g., "The Carthage News" or "Carthage News Online"), we boost.
        staff_terms = {"staff", "staff report", "editor", "staff writer"}
        try:
            candidate_byline = None
            if authors and isinstance(authors, str) and authors.strip():
                candidate_byline = authors.strip().lower()
            elif byline_match:
                candidate_byline = byline_match.group(1).strip().lower()

            if candidate_byline:
                cand = candidate_byline
                # direct staff/editor terms
                if any(st in cand for st in staff_terms):
                    byline_signal = max(byline_signal, 0.98)
                # fuzzy publisher-name match: check if publisher name tokens
                # are present in the byline (e.g., 'carthage news')
                elif pub_name:
                    pub_tokens = [t for t in re.split(r"\W+", pub_name) if t]
                    if pub_tokens and all(tok in cand for tok in pub_tokens[:2]):
                        # strong boost for a match to publisher name
                        byline_signal = max(byline_signal, 0.995)
        except Exception:
            pass

        # wire indicators to penalize - be more specific to avoid false
        # positives
        wire_indicators = [
            " ap ",
            "(ap)",
            "associated press",
            "reuters",
            "bloomberg",
            "npr news",
            "cnn",
            "ap-wire",
            "tribune news service",
            "mcclatchy",
            "gannett",
            "usa today network",
        ]
        wire_present = any(w in text_lower for w in wire_indicators)
        wire_penalty = 0.0 if not wire_present else -0.6

        # team/institution signal
        team_signal = 0.0
        if unique_locations:
            insts = set(self.publishers.get(host_id, {}).get("cached_institutions", []))
            inst_matches = sum(1 for ul in unique_locations if ul in insts)
            if inst_matches > 0:
                team_signal = min(0.6, 0.25 * inst_matches)
            else:
                team_keywords = [
                    "lady",
                    "cardinal",
                    "tigers",
                    "lions",
                    "eagles",
                    "bulldog",
                    "panther",
                    "diamond",
                ]
                if any(any(k in ul for k in team_keywords) for ul in unique_locations):
                    team_signal = 0.25

        # county signal
        county_signal = 0.0
        pub_county = (pub.get("county") or "").strip().lower()
        if pub_county and (
            pub_county in text_lower or f"{pub_county} county" in text_lower
        ):
            county_signal = 0.8

        # Combine into local probability
        local_probability = (
            signal_strength * 0.5
            + byline_signal * 0.2
            + team_signal * 0.1
            + county_signal * 0.2
        )
        local_probability = max(0.0, min(1.0, local_probability + wire_penalty))

        return {
            "has_geographic_signals": location_count > 0,
            "detected_locations": unique_locations,
            "location_count": location_count,
            "signal_strength": signal_strength,
            "local_probability": local_probability,
            "byline_signal": byline_signal,
            "wire_present": wire_present,
            "coverage_radius": (
                self.publishers.get(host_id, {}).get("coverage_radius", 0)
            ),
        }

    def enhance_local_wire_classification(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enhance local_wire classification using publisher-specific
        geographic signals.
        """
        df = df.copy()

        print("Applying publisher-specific geographic filtering...")

        # Apply geographic signal detection to all articles
        geo_results = []

        # Pre-compute per-host author occurrence counts. We normalize author
        # strings to lowercase to make counts robust. This map has structure:
        # { host_id_str: { author_lower: count, ... }, ... }
        authors_count_by_host: dict[str, dict[str, int]] = {}
        if "host_id" in df.columns and (
            "authors" in df.columns or "author" in df.columns
        ):
            # iterate rows to build counts
            for _, r in df.iterrows():
                h = r.get("host_id", "")
                if pd.isna(h):
                    continue
                try:
                    h = str(int(float(h)))
                except Exception:
                    h = str(h)
                a = r.get("authors", None) or r.get("author", None)
                if a is None:
                    continue
                # Split multi-author strings on common delimiters and count
                # each author separately. Normalize to lowercase for keys.
                raw_authors = str(a).strip()
                if not raw_authors:
                    continue
                # Common delimiters: comma, semicolon, '/', ' and '
                parts = re.split(
                    r"\s*(?:,|;|/|\band\b)\s*",
                    raw_authors,
                    flags=re.IGNORECASE,
                )
                for p in parts:
                    pval = p.strip().lower()
                    if not pval:
                        continue
                    authors_count_by_host.setdefault(h, {})
                    authors_count_by_host[h][pval] = (
                        authors_count_by_host[h].get(pval, 0) + 1
                    )

        for _, row in df.iterrows():
            # Convert host_id to string, handling float values
            host_id = row.get("host_id", "")
            if pd.isna(host_id):
                host_id = ""
            else:
                # Convert float to int to string to remove decimal
                try:
                    host_id = str(int(float(host_id)))
                except Exception:
                    host_id = str(host_id)

            text = row.get("news", "")
            # Thread title and authors metadata if available
            title = row.get("title", None)
            authors = row.get("authors", None) or row.get("author", None)
            # Ensure we pass strings or None explicitly
            if title is None:
                title_arg = None
            else:
                title_arg = str(title)
            if authors is None:
                authors_arg = None
                authors_lower = None
            else:
                authors_arg = str(authors)
                authors_lower = authors_arg.strip().lower()

            # compute authors_count for this host/author
            auth_count = 0
            if authors_lower and host_id in authors_count_by_host:
                auth_count = authors_count_by_host[host_id].get(authors_lower, 0)

            result = self.detect_geographic_signals(
                text,
                host_id,
                title=title_arg,
                authors=authors_arg,
                authors_count=auth_count,
            )
            geo_results.append(result)

        # Extract geographic signal components
        df["has_geographic_signals"] = [
            r["has_geographic_signals"] for r in geo_results
        ]
        df["detected_locations"] = [r["detected_locations"] for r in geo_results]
        df["location_count"] = [r["location_count"] for r in geo_results]
        df["geographic_signal_strength"] = [r["signal_strength"] for r in geo_results]
        # local_probability from detector
        df["local_probability"] = [
            r.get("local_probability", None) for r in geo_results
        ]
        # include whether a wire indicator was detected near byline/text
        df["wire_present"] = [r.get("wire_present", False) for r in geo_results]
        df["coverage_radius"] = [r["coverage_radius"] for r in geo_results]

        # Initialize wire and local_wire columns if they don't exist
        if "wire" not in df.columns:
            df["wire"] = 0
        if "local_wire" not in df.columns:
            df["local_wire"] = 0

        # Keep a copy of the basic local_wire for metrics
        df["local_wire_basic"] = df["local_wire"].copy()

        # We'll compute a three-way classification:
        # - 'local' : local story (not wire)
        # - 'wire'  : wire story (non-local)
        # - 'wire+local' : wire story that nevertheless contains local signals
        classifications = []

        # Terms indicating national/international or clearly non-local content
        non_local_terms = {
            "washington",
            "new york",
            "los angeles",
            "chicago",
            "boston",
            "san francisco",
            "atlanta",
            "seattle",
            "international",
            "europe",
            "china",
            "russia",
            "united kingdom",
            "uk",
            "canada",
            "mexico",
            "congress",
            "white house",
            "president",
            "national",
        }

        # Threshold for considering something 'local' based on
        # local_probability (lowered from 0.6 to 0.4 to reduce false negatives)
        LOCAL_PROB_THRESHOLD = 0.4

        for _, row in df.iterrows():
            # Convert host_id to string, handling float values
            host_id = row.get("host_id", "")
            if pd.isna(host_id):
                host_id = ""
            else:
                # Convert float to int to string to remove decimal
                try:
                    host_id = str(int(float(host_id)))
                except Exception:
                    host_id = str(host_id)

            text_lower = (row.get("news", "") or "").lower()

            # Determine whether a wire signal is present. We treat an
            # existing 'wire' flag or detected wire indicators as evidence.
            original_wire_flag = False
            if row.get("wire", 0) is not None:
                try:
                    original_wire_flag = bool(int(row.get("wire", 0)))
                except Exception:
                    original_wire_flag = bool(row.get("wire", 0))
            detector_wire = bool(row.get("wire_present", False))
            wire_indicated = original_wire_flag or detector_wire

            # Determine whether there is explicit non-local evidence
            non_local_evidence = False
            # 1) Broad national/international terms
            if any(term in text_lower for term in non_local_terms):
                non_local_evidence = True

            # 2) Detected place mentions outside publisher's local area
            detected = row.get("detected_locations", []) or []
            # Get publisher's local geography for comparison
            local_geography = self.publisher_local_geography.get(host_id, {})
            all_local_places = set()
            if local_geography:
                cities = local_geography.get("cities", {}).keys()
                counties = local_geography.get("counties", {}).keys()
                regions = local_geography.get("regions", {}).keys()
                institutions = local_geography.get("institutions", {}).keys()
                all_local_places.update(cities)
                all_local_places.update(counties)
                all_local_places.update(regions)
                all_local_places.update(institutions)

            for loc in detected:
                if not loc:
                    continue
                if loc not in all_local_places:
                    non_local_evidence = True
                    break

            # 3) If the detector explicitly marked wire_present and there are
            # no strong local signals, treat that as non-local evidence
            # unless countered by a high local_probability.
            local_prob = float(row.get("local_probability", 0.0) or 0.0)
            has_inst = bool(row.get("has_local_institutional_signals", False))

            # Check for publisher-specific local locations
            has_local_locations = False
            detected_locations = row.get("detected_locations", []) or []
            if detected_locations and all_local_places:
                # Check if any detected location is in this publisher's area
                local_matches = [
                    loc for loc in detected_locations if loc and loc in all_local_places
                ]
                has_local_locations = bool(local_matches)

            # Determine whether we consider the article to have a local signal
            local_signal = (
                local_prob >= LOCAL_PROB_THRESHOLD or has_inst or has_local_locations
            )

            # Final classification logic
            if wire_indicated:
                # Wire is indicated; decide if it is also local
                if local_signal:
                    cls = "wire+local"
                else:
                    # If explicit non-local evidence exists, mark wire
                    if non_local_evidence:
                        cls = "wire"
                    else:
                        # Prefer local if no non-local evidence despite wire
                        cls = "wire+local"
            else:
                # No wire signal; default to local unless explicit non-local
                if non_local_evidence and not local_signal:
                    cls = "wire"  # treat as effectively non-local/wire-like
                else:
                    cls = "local"

            classifications.append(cls)

        # Assign classification and update local_wire (1 for any local content)
        df["classification"] = classifications
        df["local_wire"] = df["classification"].apply(
            lambda c: 1 if c in ("local", "wire+local") else 0
        )

        # Print metrics
        counts = df["classification"].value_counts().to_dict()
        print("Publisher-specific geographic filtering results:")
        print(
            f"- Articles with geographic signals: {df['has_geographic_signals'].sum()}"
        )
        print(f"- Classification counts: {counts}")

        return df


def apply_publisher_geographic_filtering(
    df: pd.DataFrame,
    publinks_path: str = "sources/publinks.csv",
) -> pd.DataFrame:
    """Apply publisher-specific geographic filtering to the dataframe."""
    geo_filter = PublisherGeoFilter(publinks_path)
    return geo_filter.enhance_local_wire_classification(df)


# Example usage
if __name__ == "__main__":
    # Test with a specific publisher
    geo_filter = PublisherGeoFilter("sources/publinks.csv")

    # Test with Columbia Daily Tribune (host_id might be in your data)
    test_text = (
        "The Columbia City Council voted on downtown parking regulations "
        "near the University of Missouri campus."
    )

    # This would use publisher-specific gazetteer if we had the host_id
    print("Publisher-Specific Geographic Filtering Demo")
    print("=" * 50)

    # Show gazetteers for different publisher types
    for host_id in ["163", "203", "220"]:  # Examples from the CSV
        if host_id in geo_filter.publishers:
            pub = geo_filter.publishers[host_id]
            print(f"\nPublisher: {pub['name']} ({pub['city']}, {pub['county']})")
            print(
                f"Media type: {pub['media_type']}, "
                f"Coverage radius: {pub['coverage_radius']} miles"
            )

            gazetteer = geo_filter.build_publisher_gazetteer(host_id)
            print(f"Gazetteer size: {len(gazetteer)} locations")
            print(f"Sample locations: {list(gazetteer)[:5]}")
