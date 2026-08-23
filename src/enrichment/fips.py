"""FIPS/GEOID resolution ladder (decided 2026-08-21).

Precise coordinates are not the target; the deepest available Census GEOID is:

    state (2) -> county (5) -> place (7) -> tract (11) / block (15)

State, county and place resolve from the bundled Census gazetteer files —
local, exact, no API, no model call. Tract and block need a real street
address (house number present) and use the free Census geocoder; that upgrade
is attempted only when such an address was extracted.

Names in the place gazetteer carry an LSAD suffix ("Columbia city",
"Ashland city", "Whiteside village"); matching strips it. Two places in one
state can share a bare name — the first (lowest GEOID) wins and the ambiguity
is preserved in the level being 'place' rather than deeper.
"""

from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from src.enrichment.resolve import norm

# `reference/` rather than `data/`: .gitignore excludes every directory named
# `data`, so these two files were never committed and the enrichment tests
# failed in CI on FileNotFoundError while passing on any machine that held a
# copy. Reference data the code cannot run without belongs in the repository.
DATA = Path(__file__).parent / "reference"

# LSAD descriptors appearing as name suffixes in the place gazetteer.
_SUFFIX = re.compile(
    r"\s+(city|town|village|borough|cdp|municipality|comunidad|"
    r"zona urbana|urban county|metro government|metropolitan government|"
    r"unified government|consolidated government)$",
    re.IGNORECASE,
)

STATE_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
    "PR": "72",
}

STATE_NAME_TO_USPS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "puerto rico": "PR",
}


def _usps(state: str | None) -> str | None:
    """Accept a USPS code or a full state name; extracted components carry
    both ("MO" and "Missouri")."""
    if not state:
        return None
    value = state.strip()
    if len(value) == 2 and value.isalpha():
        return value.upper()
    return STATE_NAME_TO_USPS.get(value.lower())


_places: dict[tuple[str, str], tuple[str, float, float]] | None = None
_counties: dict[tuple[str, str], tuple[str, float, float]] | None = None


def _strip_suffix(name: str) -> str:
    return _SUFFIX.sub("", name).strip()


def _load() -> None:
    global _places, _counties
    if _places is not None:
        return
    places: dict[tuple[str, str], tuple[str, float, float]] = {}
    with open(DATA / "census_places.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row["USPS"], norm(_strip_suffix(row["NAME"])))
            if key not in places:  # first (lowest GEOID) wins on bare-name ties
                places[key] = (
                    row["GEOID"],
                    float(row["INTPTLAT"]),
                    float(row["INTPTLONG"]),
                )
    counties: dict[tuple[str, str], tuple[str, float, float]] = {}
    with open(DATA / "census_counties.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            bare = norm(
                re.sub(
                    r"\s+(county|parish|borough|census area|"
                    r"municipality|municipio|city and borough|"
                    r"planning region|city)$",
                    "",
                    row["NAME"],
                    flags=re.IGNORECASE,
                )
            )
            counties[(row["USPS"], bare)] = (
                row["GEOID"],
                float(row["INTPTLAT"]),
                float(row["INTPTLONG"]),
            )
    _places, _counties = places, counties


@dataclass(frozen=True)
class GeoidResult:
    geoid: str
    level: str  # state | county | place | tract | block
    lat: float | None
    lon: float | None
    # ZCTA (the Census's ZIP) rides along on block-level resolutions: it is a
    # real GEOID that joins to ACS like every other rung, and the block lookup
    # already pays for the request that carries it (decided 2026-08-21).
    zcta: str | None = None


def place_geoid(city: str, state: str) -> GeoidResult | None:
    _load()
    assert _places is not None
    usps = _usps(state)
    if usps is None:
        return None
    # Look up the name as given first: stripping the LSAD suffix from input
    # mangles real names ending in a descriptor — "Platte City" is not
    # "Platte", "Kansas City" is not "Kansas". The stripped form is only a
    # fallback for inputs that arrive as "Columbia city".
    hit = _places.get((usps, norm(city))) or _places.get(
        (usps, norm(_strip_suffix(city)))
    )
    if hit is None:
        return None
    return GeoidResult(hit[0], "place", hit[1], hit[2])


def county_geoid(county: str, state: str) -> GeoidResult | None:
    _load()
    assert _counties is not None
    usps = _usps(state)
    if usps is None:
        return None
    bare = norm(re.sub(r"\s+county$", "", county, flags=re.IGNORECASE))
    hit = _counties.get((usps, bare))
    if hit is None:
        return None
    return GeoidResult(hit[0], "county", hit[1], hit[2])


def state_geoid(state: str) -> GeoidResult | None:
    fips = STATE_FIPS.get(_usps(state) or "")
    return GeoidResult(fips, "state", None, None) if fips else None


_HOUSE_NUMBER = re.compile(r"^\d+\s+\S")


def block_geoid(
    address: str, city: str | None, state: str | None, timeout: int = 10
) -> GeoidResult | None:
    """15-digit block GEOID from the free Census geocoder. Attempted only for
    addresses with a house number; any failure returns None and the ladder
    stays at the level already reached."""
    if not _HOUSE_NUMBER.match(address or ""):
        return None
    oneline = ", ".join(x for x in (address, city, state) if x)
    url = (
        "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?"
        + urllib.parse.urlencode(
            {
                "address": oneline,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "layers": "all",
                "format": "json",
            }
        )
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
        matches = data["result"]["addressMatches"]
        if not matches:
            return None
        match = matches[0]
        geographies = match["geographies"]
        block_key = next(
            (k for k in geographies if "Census Blocks" in k), None
        )  # the key carries the vintage, e.g. "2020 Census Blocks"
        blocks = geographies.get(block_key) or []
        if not blocks:
            return None
        geoid = blocks[0]["GEOID"][:15]
        zcta_key = next((k for k in geographies if "ZIP Code Tabulation" in k), None)
        zctas = geographies.get(zcta_key) or []
        zcta = (zctas[0].get("GEOID") or "")[:5] or None if zctas else None
        coords = match.get("coordinates") or {}
        return GeoidResult(geoid, "block", coords.get("y"), coords.get("x"), zcta)
    except Exception:
        return None


def resolve_geoid(
    *,
    point_city: str | None,
    state: str | None,
    county: str | None,
    street_address: str | None,
    address_city: str | None,
    census_lookup: bool = True,
) -> GeoidResult | None:
    """The ladder: block when a real address resolves, else place, else county,
    else state."""
    if census_lookup and street_address:
        block = block_geoid(street_address, address_city or point_city, state)
        if block:
            return block
    if point_city and state:
        place = place_geoid(point_city, state)
        if place:
            return place
    if county and state:
        result = county_geoid(county, state)
        if result:
            return result
    if state:
        return state_geoid(state)
    return None
