"""Where each point of interest actually is, in Census terms.

The model infers geography from institutions a story names -- "a senior
at Mexico High School" locates a story in Mexico, "Southeast Missouri
State gymnastics" locates one in Cape Girardeau. That induction is
wanted: it reasons from evidence in the article, and it is not the
fabrication `grounding` exists to stop.

`grounding` could not tell the two apart while it asked only whether the
place NAME appeared in the text, so it deleted the induction along with
the fabrication -- 70 of the 803 points the first backfill cleared had an
institution in the article sitting in the very city removed.

The verifier is the gazetteer, which knows where each institution is.
What it lacked is which Census place that is. `tags->>'addr:city'` is an
OSM convenience field: present on 223,771 of 558,540 rows, absent on the
rest, and carrying a postal name ("Saint Louis") rather than a GEOID.

Every row has lat/lon, so this asks the Census geocoder once per point
and stores the answer. Only 11,440 gazetteer entries are ever matched to
an article and 6,481 of those lack `addr:city`, so the job that makes the
gate work is thousands of lookups, not half a million.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.enrichment.fips import bare_place_name

COORDINATES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

#: Both rungs in one request. Asking separately would double a job that
#: is already thousands of calls to somebody else's free service.
LAYERS = "Incorporated Places,Counties"
BENCHMARK = "Public_AR_Current"
VINTAGE = "Census2020_Current"

#: Modest, because this service is free and we are a guest on it.
CONCURRENCY = 4


@dataclass(frozen=True)
class Placement:
    """What a coordinate resolves to. All three may be None: a point in
    open water or outside any incorporated place has no place, and that
    is an answer rather than a failure."""

    place_geoid: str | None = None
    place_name: str | None = None
    county_geoid: str | None = None


def url_for(lat: float, lon: float) -> str:
    query = urllib.parse.urlencode(
        {
            "x": lon,
            "y": lat,
            "benchmark": BENCHMARK,
            "vintage": VINTAGE,
            "layers": LAYERS,
            "format": "json",
        }
    )
    return f"{COORDINATES_URL}?{query}"


def parse(payload: dict) -> Placement:
    """Read a geocoder response. Layer keys carry their vintage, so they
    are matched by substring rather than by an exact name that changes
    every ten years."""
    geographies = ((payload or {}).get("result") or {}).get("geographies") or {}

    def first(fragment: str) -> dict:
        key = next((k for k in geographies if fragment in k), None)
        rows = geographies.get(key) or [] if key else []
        return rows[0] if rows else {}

    place, county = first("Places"), first("Counties")
    name = place.get("NAME")
    return Placement(
        place_geoid=place.get("GEOID"),
        place_name=bare_place_name(name) if name else None,
        county_geoid=county.get("GEOID"),
    )


class _NotRecorded:
    """Keeps the call-telemetry shape when nothing is recording."""

    meta: dict = {}

    def failed(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@contextmanager
def _recorded(call_recorder: Any | None, subject_id: str | None) -> Iterator[Any]:
    if call_recorder is None:
        yield _NotRecorded()
        return
    with call_recorder.call(
        "census_geocoder",
        "coordinates",
        subject_type="gazetteer",
        subject_id=subject_id,
    ) as call:
        yield call


def resolve(
    lat: float,
    lon: float,
    *,
    timeout: int = 25,
    call_recorder: Any | None = None,
    subject_id: str | None = None,
) -> Placement | None:
    """The placement for one coordinate, or None when the call failed.

    None means "ask again"; an empty `Placement` means "asked, and this
    point is in no incorporated place". The backfill stamps
    `geocoded_at` for the second and leaves the row alone for the first.
    """
    with _recorded(call_recorder, subject_id) as call:
        try:
            with urllib.request.urlopen(url_for(lat, lon), timeout=timeout) as resp:
                payload = json.load(resp)
        except Exception as exc:  # noqa: BLE001 - recorded, then reported
            call.failed(type(exc).__name__)
            return None
        placement = parse(payload)
        call.meta["placed"] = placement.place_geoid is not None
        return placement


_PENDING = """
    SELECT g.id, g.lat, g.lon
      FROM gazetteer g
     WHERE g.geocoded_at IS NULL
       AND g.lat IS NOT NULL AND g.lon IS NOT NULL
"""

#: Only entries an article actually named are worth the call. 11,440 of
#: 558,540, which is the difference between a ten-minute job and a week.
_ONLY_MATCHED = """
       AND EXISTS (SELECT 1 FROM article_entities ae
                    WHERE ae.matched_gazetteer_id = g.id)
"""

_STORE = text("""
    UPDATE gazetteer
       SET place_geoid = :place_geoid,
           place_name = :place_name,
           county_geoid = :county_geoid,
           geocoded_at = :now
     WHERE id = :id
""")


def pending(
    session: Session, *, only_matched: bool = True, limit: int | None = None
) -> list[tuple[str, float, float]]:
    sql = _PENDING + (_ONLY_MATCHED if only_matched else "") + " ORDER BY g.id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [(r[0], r[1], r[2]) for r in session.execute(text(sql))]


def geocode(
    session: Session,
    *,
    only_matched: bool = True,
    limit: int | None = None,
    concurrency: int = CONCURRENCY,
    dry_run: bool = False,
    call_recorder: Any | None = None,
    on_batch: Any | None = None,
) -> dict[str, int]:
    """Resolve pending points and store what they resolve to."""
    rows = pending(session, only_matched=only_matched, limit=limit)
    counts = {"pending": len(rows), "placed": 0, "no_place": 0, "failed": 0}
    if not rows or dry_run:
        return counts

    now = datetime.now(timezone.utc)

    def one(row: tuple[str, float, float]) -> tuple[str, Placement | None]:
        gid, lat, lon = row
        return gid, resolve(lat, lon, call_recorder=call_recorder, subject_id=gid)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for index, (gid, placement) in enumerate(pool.map(one, rows), start=1):
            if placement is None:
                counts["failed"] += 1
                continue
            counts["placed" if placement.place_geoid else "no_place"] += 1
            session.execute(
                _STORE,
                {
                    "id": gid,
                    "place_geoid": placement.place_geoid,
                    "place_name": placement.place_name,
                    "county_geoid": placement.county_geoid,
                    "now": now,
                },
            )
            if index % 200 == 0:
                session.commit()
                if on_batch:
                    on_batch(index, counts)
    session.commit()
    return counts
