"""Build a POI extract for the gazetteer from a Geofabrik state PBF.

Filters a state's OSM extract (https://download.geofabrik.de, per-state
.osm.pbf files) down to the named POIs matching CATEGORY_FILTER_MAP — the
same 61 tag filters the Overpass path queries — and writes them to a CSV
the gazetteer builder can serve locally via OSM_POI_CSV. This removes the
Overpass dependency: public instances rate-limit and fail2ban bulk use
(2026-08-21: three egress IPs banned mid-run), while a state extract is a
one-time download of tens to hundreds of MB.

Usage:
    python scripts/build_osm_poi_extract.py \
        --pbf missouri-latest.osm.pbf --out data/osm_poi_mo.csv

Ways are located at the mean of their node coordinates — adequate for
distance-from-publisher bucketing, which is the only geometry the
gazetteer uses. Unnamed features are dropped: the gazetteer only stores
named entities.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import osmium

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from scripts.populate_gazetteer import CATEGORY_FILTER_MAP  # noqa: E402


def build_matcher() -> dict[str, set[str]]:
    """key -> accepted values ('*' accepts any) across all categories."""
    matcher: dict[str, set[str]] = {}
    for filters in CATEGORY_FILTER_MAP.values():
        for f in filters:
            if "=" not in f:
                continue
            key, value = f.split("=", 1)
            matcher.setdefault(key, set()).add(value)
    return matcher


def matches(tags: dict[str, str], matcher: dict[str, set[str]]) -> bool:
    for key, values in matcher.items():
        v = tags.get(key)
        if v is not None and ("*" in values or v in values):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", required=True, help="state .osm.pbf extract")
    parser.add_argument("--out", required=True, help="output CSV path")
    args = parser.parse_args()

    matcher = build_matcher()
    rows = 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["osm_type", "osm_id", "name", "lat", "lon", "tags"])

        fp = osmium.FileProcessor(args.pbf).with_locations()
        for obj in fp:
            if not obj.is_node() and not obj.is_way():
                continue
            tags = {t.k: t.v for t in obj.tags}
            if "name" not in tags or not matches(tags, matcher):
                continue
            if obj.is_node():
                lat, lon = obj.lat, obj.lon
                osm_type = "node"
            else:
                locs = [n.location for n in obj.nodes if n.location.valid()]
                if not locs:
                    continue
                lat = sum(loc.lat for loc in locs) / len(locs)
                lon = sum(loc.lon for loc in locs) / len(locs)
                osm_type = "way"
            writer.writerow(
                [
                    osm_type,
                    obj.id,
                    tags["name"],
                    f"{lat:.7f}",
                    f"{lon:.7f}",
                    json.dumps(tags, ensure_ascii=False),
                ]
            )
            rows += 1

    print(f"wrote {rows} named POIs to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
