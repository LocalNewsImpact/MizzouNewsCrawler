"""One gazetteer per state, loaded on demand from the POI extracts.

`docs/STATEWIDE_GAZETTEER.md` states why the per-publisher gazetteer
cannot verify induced geography: every candidate sits within 22.2 miles
of one publisher, so any match resolves near that publisher and chain
evidence launders the publisher-city bias the grounding gate exists to
stop. It also costs recall -- "Mizzou Arena" is in the gazetteer,
resolved to Columbia, and invisible to every publisher further out -- and
stores 83,325 distinct features as 558,540 rows.

THE DATA ALREADY EXISTS. `scripts/build_osm_poi_extract.py` filters a
Geofabrik state PBF down to the same 61 tag filters the Overpass path
queries and writes a CSV; those CSVs are in
`gs://mizzou-osm-extracts/poi/`. Missouri holds 32,925 POIs, Washington
50,481, Kansas 18,325, Vermont 6,763. So this module downloads and
installs, rather than crawling anything.

ON DEMAND, NOT AHEAD OF TIME. A state is loaded the first time a source
in that state is seen. `ensure_state` is the entry point and is a no-op
once the state is present; loads are idempotent on
`(state, osm_type, osm_id)`.

WHY MISSOURI STATEWIDE IS ONLY 19% MORE FEATURES than the current
per-publisher build's 27,729: 247 publishers' 20-mile radii already cover
most of the populated state. The gain here is not data. It is scope,
ambiguity detection, and one row per feature instead of 6.7.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.enrichment.fips import STATE_FIPS, STATE_NAME_TO_USPS, _usps
from src.utils.gazetteer_names import is_matchable_gazetteer_name, normalize_name

logger = logging.getLogger(__name__)

GCS_BUCKET = "mizzou-osm-extracts"
GCS_PREFIX = "poi"

#: USPS -> the lowercase state name the extracts are filed under.
USPS_TO_EXTRACT_NAME = {code: name for name, code in STATE_NAME_TO_USPS.items()}

#: Rows per INSERT. 50,481 (Washington) one statement at a time is a
#: round trip per POI; this is one per thousand.
BATCH = 1000


def state_code(state: str | None) -> str | None:
    """A real USPS code, or None.

    `fips._usps` accepts ANY two alphabetic characters -- it is parsing a
    component, not validating one -- so it answers "ZZ" for "ZZ". Every
    write here is keyed on the state, so an unvalidated code silently
    creates a gazetteer for a state that does not exist. Checked against
    `STATE_FIPS`, which is the list.
    """
    code = _usps(state)
    return code if code in STATE_FIPS else None


def extract_name(state: str | None) -> str | None:
    """ "MO" or "Missouri" -> "missouri", the name in the bucket."""
    code = state_code(state)
    return USPS_TO_EXTRACT_NAME.get(code) if code else None


def extract_uri(state: str) -> str | None:
    name = extract_name(state)
    return f"gs://{GCS_BUCKET}/{GCS_PREFIX}/{name}.csv" if name else None


def _category_index() -> dict[tuple[str, str], str]:
    """(tag key, tag value) -> category, inverted from the builder's map.

    Read from `scripts/populate_gazetteer.py` rather than copied, so a
    category added to the Overpass path is understood here without anyone
    remembering to mirror it. `"*"` as the value accepts any.
    """
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from populate_gazetteer import CATEGORY_FILTER_MAP  # type: ignore

    index: dict[tuple[str, str], str] = {}
    for category, filters in CATEGORY_FILTER_MAP.items():
        for entry in filters:
            if "=" not in entry:
                continue
            key, value = entry.split("=", 1)
            index.setdefault((key.strip(), value.strip()), category)
    return index


def category_for(
    tags: dict, index: dict[tuple[str, str], str] | None = None
) -> str | None:
    """The gazetteer category a POI's tags put it in, or None.

    This is the field the grounding gate should read instead of spaCy's
    label: it comes from OSM's own tagging rather than from a statistical
    guess, and `en_core_web_sm` files `Columbia` as ORG 3,047 times and
    `story` as ORG 2,999.
    """
    if not isinstance(tags, dict):
        return None
    index = index if index is not None else _category_index()
    for key, value in tags.items():
        hit = index.get((key, str(value))) or index.get((key, "*"))
        if hit:
            return hit
    return None


def read_extract(handle: Iterable[str]) -> Iterator[dict]:
    """Rows of a POI extract, with tags decoded and the name normalised.

    Unmatchable names are dropped here rather than at match time, so the
    table never holds a pattern that would fire on every "a" in an
    article -- and so every consumer sees the same corpus.
    """
    index = _category_index()
    for row in csv.DictReader(handle):
        name = (row.get("name") or "").strip()
        if not is_matchable_gazetteer_name(name):
            continue
        try:
            tags = json.loads(row.get("tags") or "{}")
        except (TypeError, ValueError):
            tags = {}
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        yield {
            "osm_type": row.get("osm_type") or "",
            "osm_id": str(row.get("osm_id") or ""),
            "name": name,
            "name_norm": normalize_name(name),
            "category": category_for(tags, index),
            "lat": lat,
            "lon": lon,
            "tags": json.dumps(tags),
        }


def _storage_client():
    """The GCS client, behind a seam.

    Tests patch THIS rather than `google.cloud.storage.Client`. Patching
    that by name imports the real module, which then binds as an
    attribute of the `google.cloud` package -- and from that point
    `from google.cloud import storage` returns the real module however
    `sys.modules` is patched. tests/utils/test_raw_html_archive.py
    injects a stub exactly that way and started failing when this module
    imported the real one first.
    """
    from google.cloud import storage  # type: ignore[attr-defined]

    return storage.Client()


def download_extract(state: str) -> str:
    """The extract's text, from the bucket."""
    name = extract_name(state)
    if not name:
        raise ValueError(f"no extract name for state {state!r}")
    client = _storage_client()
    blob = client.bucket(GCS_BUCKET).blob(f"{GCS_PREFIX}/{name}.csv")
    if not blob.exists():
        raise FileNotFoundError(
            f"{extract_uri(state)} is not in the bucket. Build it with "
            f"scripts/build_osm_poi_extract.py from the Geofabrik PBF and upload it."
        )
    return blob.download_as_text()


_INSERT = text("""
    INSERT INTO gazetteer_features
      (id, state, osm_type, osm_id, name, name_norm, category, lat, lon, tags)
    VALUES
      (:id, :state, :osm_type, :osm_id, :name, :name_norm, :category,
       :lat, :lon, CAST(:tags AS JSON))
    ON CONFLICT (state, osm_type, osm_id) DO NOTHING
""")


def loaded_states(session: Session) -> set[str]:
    return {
        row[0]
        for row in session.execute(
            text("SELECT DISTINCT state FROM gazetteer_features")
        )
    }


def state_is_loaded(session: Session, state: str) -> bool:
    code = state_code(state)
    if not code:
        return False
    found = session.execute(
        text("SELECT 1 FROM gazetteer_features WHERE state = :s LIMIT 1"), {"s": code}
    ).first()
    return found is not None


def load_state(
    session: Session,
    state: str,
    *,
    path: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Install one state's features. Idempotent."""
    code = state_code(state)
    if not code:
        raise ValueError(f"unresolvable state {state!r}; it is never guessed")

    if path:
        handle: Iterable[str] = Path(path).read_text().splitlines()
    else:
        handle = io.StringIO(download_extract(code))

    counts = {"read": 0, "written": 0}
    batch: list[dict] = []
    for record in read_extract(handle):
        counts["read"] += 1
        if dry_run:
            continue
        batch.append({"id": str(uuid.uuid4()), "state": code, **record})
        if len(batch) >= BATCH:
            session.execute(_INSERT, batch)
            counts["written"] += len(batch)
            batch = []
    if batch and not dry_run:
        session.execute(_INSERT, batch)
        counts["written"] += len(batch)
    if not dry_run:
        session.commit()
    return counts


_REBUILD_INDEX = text("""
    INSERT INTO gazetteer_name_places
      (state, name_norm, place_count, place_geoid, place_name, updated_at)
    SELECT state, name_norm,
           -- AN UNPLACED FEATURE STILL COUNTS AGAINST THE NAME.
           --
           -- Filtering them out before counting made a name look
           -- unambiguous when it is not: `bethel church` has 52 features
           -- in Missouri, 51 of them without a place, and the index
           -- called it "unambiguously Wildwood". Every Missouri story
           -- naming a Bethel Church resolved there with total
           -- confidence -- the statewide collision §4e blamed for the
           -- Kennett church matching one at the other end of the state.
           --
           -- We do not know WHERE the unplaced ones are, only that they
           -- are other features wearing the same name, so they add one
           -- to the count rather than their own number: enough to deny
           -- the name a single answer, without inventing places.
           count(DISTINCT place_geoid)
             + CASE WHEN count(*) FILTER (WHERE place_geoid IS NULL) > 0
                    THEN 1 ELSE 0 END AS place_count,
           CASE WHEN count(DISTINCT place_geoid) = 1
                 AND count(*) FILTER (WHERE place_geoid IS NULL) = 0
                THEN min(place_geoid) END,
           CASE WHEN count(DISTINCT place_geoid) = 1
                 AND count(*) FILTER (WHERE place_geoid IS NULL) = 0
                THEN min(place_name) END,
           :now
      FROM gazetteer_features
     WHERE state = :state
     GROUP BY state, name_norm
    HAVING count(DISTINCT place_geoid) > 0
    ON CONFLICT (state, name_norm) DO UPDATE
       SET place_count = EXCLUDED.place_count,
           place_geoid = EXCLUDED.place_geoid,
           place_name = EXCLUDED.place_name,
           updated_at = EXCLUDED.updated_at
""")


def rebuild_name_index(session: Session, state: str) -> dict[str, int]:
    """Recount how many places each name occurs in, for §3.1.

    Runs after geocoding, because it counts `place_geoid`. A name with no
    geocoded feature contributes nothing and is absent from the index,
    which reads the same as ambiguous to a caller: no evidence.
    """
    code = state_code(state)
    if not code:
        raise ValueError(f"unresolvable state {state!r}")
    session.execute(
        text("DELETE FROM gazetteer_name_places WHERE state = :s"), {"s": code}
    )
    session.execute(_REBUILD_INDEX, {"state": code, "now": datetime.now(timezone.utc)})
    session.commit()
    row = session.execute(
        text(
            "SELECT count(*), count(*) FILTER (WHERE place_count = 1) "
            "FROM gazetteer_name_places WHERE state = :s"
        ),
        {"s": code},
    ).first()
    if row is None:
        return {"names": 0, "unambiguous": 0}
    return {"names": row[0] or 0, "unambiguous": row[1] or 0}


def ensure_state(
    session: Session, state: str, *, dry_run: bool = False
) -> dict[str, int]:
    """Load a state if it is not already present. The on-demand entry."""
    code = state_code(state)
    if not code:
        return {"read": 0, "written": 0, "skipped": 1}
    if state_is_loaded(session, code):
        return {"read": 0, "written": 0, "already": 1}
    logger.info("installing the %s gazetteer from %s", code, extract_uri(code))
    return load_state(session, code, dry_run=dry_run)


#: A secondary state needs this share of a source's own POIs to count as
#: within reach. The distribution chose it: 23 secondary states are at
#: 20% or more (Dos Mundos is 45% Kansas, Fox4KC 40%), 7 more at 10-20%,
#: then one in the 5-10% band and 17 below 5% -- several at a single POI.
#: Opening Kansas's 17,997 features to a Missouri paper on one spillover
#: POI is the error this guards.
BORDER_SHARE = 0.10

#: What a source's own 20-mile OSM build says it can reach. Joined to the
#: state-keyed features rather than modelled from boundaries: the build
#: already asked "what is within 20 miles of this newsroom", and the
#: answer carries a state now.
_REACH = text("""
    SELECT f.state, count(*) AS pois
      FROM gazetteer g
      JOIN gazetteer_features f
        ON f.osm_type = g.osm_type AND f.osm_id = g.osm_id
     WHERE g.source_id = :source_id
     GROUP BY f.state
""")


def reachable_states(
    session: Session, source_id: str, *, home: str | None = None
) -> list[dict]:
    """Which states a source may match against, and why.

    The home state is always in scope, even when the OSM build says
    nothing -- a source with no gazetteer yet still belongs somewhere.
    A state that is not home needs `BORDER_SHARE` of the build to join it.
    """
    rows = [(r[0], r[1]) for r in session.execute(_REACH, {"source_id": source_id})]
    total = sum(count for _state, count in rows) or 0
    home_code = state_code(home)

    scope: list[dict] = []
    for state, count in rows:
        share = (count / total) if total else 0.0
        if state == home_code or share >= BORDER_SHARE:
            scope.append(
                {
                    "state": state,
                    "is_home": state == home_code,
                    "pois": count,
                    "share": round(share, 4),
                }
            )
    if home_code and not any(entry["state"] == home_code for entry in scope):
        scope.append({"state": home_code, "is_home": True, "pois": 0, "share": 0.0})
    return sorted(scope, key=lambda entry: (not entry["is_home"], -entry["pois"]))


_STORE_SCOPE = text("""
    INSERT INTO source_gazetteer_scope
      (source_id, state, is_home, pois, share, computed_at)
    VALUES (:source_id, :state, :is_home, :pois, :share, :now)
    ON CONFLICT (source_id, state) DO UPDATE
       SET is_home = EXCLUDED.is_home,
           pois = EXCLUDED.pois,
           share = EXCLUDED.share,
           computed_at = EXCLUDED.computed_at
""")


def store_scope(session: Session, source_id: str, scope: list[dict]) -> int:
    """Record a source's scope, so a later question about why an article
    matched another state's place has a dated answer."""
    session.execute(
        text("DELETE FROM source_gazetteer_scope WHERE source_id = :s"),
        {"s": source_id},
    )
    now = datetime.now(timezone.utc)
    for entry in scope:
        session.execute(_STORE_SCOPE, {"source_id": source_id, "now": now, **entry})
    return len(scope)


def scope_for(session: Session, source_id: str) -> list[str]:
    """The states this source's entities may be matched against.

    Empty means no scope is recorded, and the caller must match nothing
    rather than everything: a source whose state could not be resolved is
    skipped with a reason, never given the whole country.
    """
    return [
        row[0]
        for row in session.execute(
            text(
                "SELECT state FROM source_gazetteer_scope "
                "WHERE source_id = :s ORDER BY is_home DESC, pois DESC"
            ),
            {"s": source_id},
        )
    ]
