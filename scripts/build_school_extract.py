#!/usr/bin/env python3
"""Build a state's school extract and upload it, once.

The loader reads two static files from the bucket and makes no request of
its own -- this is the script that produces them, run when a dataset
introduces a state the gazetteer has not seen.

    python scripts/build_school_extract.py MO
    python scripts/build_school_extract.py VT --no-upload

Three sources, all public:

    CCD     public schools, via the Urban Institute's mirror of the NCES
            Common Core of Data
    PSS     private schools, via the NCES school-locations service
    Census  the place gazetteer, which turns a school's city into the
            place geoid the index answers with

Schools recorded as closed are dropped. Everything else is written as-is:
the loader owns name variants and place resolution, so this file stays a
faithful copy of what the surveys say.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

FIPS = {
    "AL": 1, "AK": 2, "AZ": 4, "AR": 5, "CA": 6, "CO": 8, "CT": 9, "DE": 10,
    "DC": 11, "FL": 12, "GA": 13, "HI": 15, "ID": 16, "IL": 17, "IN": 18,
    "IA": 19, "KS": 20, "KY": 21, "LA": 22, "ME": 23, "MD": 24, "MA": 25,
    "MI": 26, "MN": 27, "MS": 28, "MO": 29, "MT": 30, "NE": 31, "NV": 32,
    "NH": 33, "NJ": 34, "NM": 35, "NY": 36, "NC": 37, "ND": 38, "OH": 39,
    "OK": 40, "OR": 41, "PA": 42, "RI": 44, "SC": 45, "SD": 46, "TN": 47,
    "TX": 48, "UT": 49, "VT": 50, "VA": 51, "WA": 53, "WV": 54, "WI": 55,
    "WY": 56,
}

CCD = ("https://educationdata.urban.org/api/v1/schools/ccd/directory/2022/"
       "?fips={fips}&limit=20000")
PSS = ("https://services1.arcgis.com/Ua5sjt3LWTPigjyD/arcgis/rest/services/"
       "Private_School_Locations_Current/FeatureServer/0/query"
       "?where=STATE%3D%27{state}%27&outFields=*&f=json&resultRecordCount=20000")
CENSUS = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
          "2023_Gazetteer/2023_gaz_place_{fips:02d}.txt")

#: CCD status 2 is closed and 6 is inactive; the rest are operating in
#: some form. A closed school still appears in stories about it, but its
#: city is no longer a place the school puts a story in.
OPEN_STATUS = {1, 3, 4, 5, 7, 8}

GCS_BUCKET = "mizzou-osm-extracts"
GCS_PREFIX = "schools"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()


def public_schools(state: str) -> list[dict]:
    fips = FIPS[state]
    payload = json.loads(_get(CCD.format(fips=fips)))
    rows = []
    for school in payload.get("results", []):
        if school.get("school_status") not in OPEN_STATUS:
            continue
        rows.append({
            "source": "ccd",
            "school_id": school["ncessch"],
            "name": school.get("school_name") or "",
            "city": school.get("city_location") or "",
            "state": school.get("state_location") or state,
            "county_geoid": str(school.get("county_code") or "").zfill(5),
            "lat": school.get("latitude") or "",
            "lon": school.get("longitude") or "",
        })
    return rows


def private_schools(state: str) -> list[dict]:
    payload = json.loads(_get(PSS.format(state=state)))
    rows = []
    for feature in payload.get("features", []):
        a = feature.get("attributes", {})
        rows.append({
            "source": "pss",
            "school_id": f"pss-{a.get('OBJECTID')}",
            "name": a.get("NAME") or "",
            "city": a.get("CITY") or "",
            "state": a.get("STATE") or state,
            "county_geoid": str(a.get("CNTY") or "").zfill(5),
            "lat": a.get("LAT") or "",
            "lon": a.get("LON") or "",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", help="two-letter state code, e.g. MO")
    parser.add_argument("--out", default=".", help="where to write the files")
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    state = args.state.strip().upper()
    if state not in FIPS:
        print(f"unknown state {state!r}", file=sys.stderr)
        return 2

    schools = public_schools(state) + private_schools(state)
    if not schools:
        print(f"no schools returned for {state}", file=sys.stderr)
        return 1

    out = Path(args.out)
    schools_path = out / f"schools_{state}.csv"
    with open(schools_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(schools[0].keys()))
        writer.writeheader()
        writer.writerows(schools)

    census_path = out / f"census_places_{state}.txt"
    census_path.write_bytes(_get(CENSUS.format(fips=FIPS[state])))

    public = sum(1 for s in schools if s["source"] == "ccd")
    print(f"{state}: {public} public, {len(schools) - public} private")
    print(f"  {schools_path}")
    print(f"  {census_path}")

    if args.no_upload:
        return 0
    from google.cloud import storage  # type: ignore[attr-defined]

    bucket = storage.Client().bucket(GCS_BUCKET)
    for path in (schools_path, census_path):
        bucket.blob(f"{GCS_PREFIX}/{path.name}").upload_from_filename(str(path))
        print(f"  uploaded gs://{GCS_BUCKET}/{GCS_PREFIX}/{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
