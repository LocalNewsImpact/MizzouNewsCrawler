"""Places a person adds, because no survey will ever have them all.

The gazetteer is assembled from OSM and the federal school surveys, and
between them they still miss the name a newsroom actually prints.
Missouri articles say `Tolton` 297 times, `Tolton Catholic` 25 and
`Tolton Catholic High School` 6; OSM records the school as `Father Tolton
Catholic High School` and the index holds only that. Nothing matched, so
a story about the school located nothing.

Some of that is fixable by rule -- an honorific stripped, an abbreviation
expanded. `Tolton` alone is not: indexing bare surnames automatically is
how `Battle` becomes a PERSON and `Clark` becomes a filling station. It
takes somebody who knows the beat to say that in Missouri, Tolton is
Columbia.

A manual entry is an ordinary gazetteer feature with `manual` as its
source, so the index, the gate and the matcher need to know nothing about
it. What it adds is provenance: who added it, when, and why.

THE INDEX IS UPDATED FOR THAT NAME ALONE. A full rebuild reads every
feature in the state; a curator adding one school should not pay for
that, and should not have to remember to run it afterwards either.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.utils.gazetteer_names import is_matchable_gazetteer_name, normalize_name

logger = logging.getLogger(__name__)

SOURCE = "manual"


class Refused(ValueError):
    """The entry was not added, with the reason a curator needs to read."""


_EXISTS = text("""
    SELECT f.name, f.place_name, f.osm_type
      FROM gazetteer_features f
     WHERE f.state = :state AND f.name_norm = :name_norm
     LIMIT 3
""")

_PLACE = text("""
    SELECT place_geoid, place_name, county_geoid
      FROM gazetteer_features
     WHERE state = :state AND place_geoid IS NOT NULL
       AND lower(place_name) = lower(:place)
     LIMIT 1
""")

_INSERT = text("""
    INSERT INTO gazetteer_features
      (id, state, osm_type, osm_id, name, name_norm, category, lat, lon,
       place_geoid, place_name, county_geoid, geocoded_at, tags)
    VALUES
      (:id, :state, :source, :entry_id, :name, :name_norm, :category, NULL, NULL,
       :place_geoid, :place_name, :county_geoid, :now, CAST(:tags AS JSON))
""")

#: Recount ONE name, the way `rebuild_name_index` counts all of them --
#: including the unplaced features that would otherwise make a name with
#: many bearers look like a name with one.
_REINDEX = text("""
    INSERT INTO gazetteer_name_places
      (state, name_norm, place_count, place_geoid, place_name, updated_at)
    SELECT state, name_norm,
           count(DISTINCT place_geoid)
             + CASE WHEN count(*) FILTER (WHERE place_geoid IS NULL) > 0
                    THEN 1 ELSE 0 END,
           CASE WHEN count(DISTINCT place_geoid) = 1
                 AND count(*) FILTER (WHERE place_geoid IS NULL) = 0
                THEN min(place_geoid) END,
           CASE WHEN count(DISTINCT place_geoid) = 1
                 AND count(*) FILTER (WHERE place_geoid IS NULL) = 0
                THEN min(place_name) END,
           :now
      FROM gazetteer_features
     WHERE state = :state AND name_norm = :name_norm
     GROUP BY state, name_norm
    HAVING count(DISTINCT place_geoid) > 0
    ON CONFLICT (state, name_norm) DO UPDATE
       SET place_count = EXCLUDED.place_count,
           place_geoid = EXCLUDED.place_geoid,
           place_name = EXCLUDED.place_name,
           updated_at = EXCLUDED.updated_at
""")

_ADDED = text("""
    SELECT f.id, f.state, f.name, f.name_norm, f.category, f.place_name,
           f.place_geoid, f.tags, f.created_at,
           np.place_count, np.place_name AS resolves_to
      FROM gazetteer_features f
      LEFT JOIN gazetteer_name_places np
        ON np.state = f.state AND np.name_norm = f.name_norm
     WHERE f.osm_type = :source
       AND (CAST(:state AS text) IS NULL OR f.state = CAST(:state AS text))
     ORDER BY f.created_at DESC
     LIMIT :limit
""")


def add_place(
    session: Session,
    *,
    state: str,
    name: str,
    place: str,
    category: str = "manual",
    added_by: str,
    note: str = "",
) -> dict:
    """Record that `name`, in `state`, is in `place`.

    `place` is matched against places the gazetteer has already geocoded,
    so a manual entry cannot invent a town -- it can only point at one the
    corpus already knows, which is what the index answers with.
    """
    state = (state or "").strip().upper()
    name = (name or "").strip()
    place = (place or "").strip()
    if not state or not name or not place:
        raise Refused("a state, a name and a place are all required")
    if not added_by or not added_by.strip():
        raise Refused("every entry records who added it")

    if not is_matchable_gazetteer_name(name):
        raise Refused(
            f"{name!r} is a description rather than a name -- every word in it "
            "names a KIND of place, so it would match in every town"
        )

    name_norm = normalize_name(name)
    resolved = session.execute(_PLACE, {"state": state, "place": place}).first()
    if resolved is None:
        raise Refused(
            f"{place!r} is not a place the {state} gazetteer has geocoded. "
            "Use the name as the Census writes it."
        )
    place_geoid, place_name, county_geoid = resolved

    existing = session.execute(_EXISTS, {"state": state, "name_norm": name_norm}).all()
    for row in existing:
        if row.osm_type == SOURCE:
            raise Refused(f"{name!r} was already added by hand, to {row.place_name}")

    now = datetime.now(timezone.utc)
    entry_id = str(uuid.uuid4())
    session.execute(
        _INSERT,
        {
            "id": f"{state}:{SOURCE}:{entry_id}",
            "state": state,
            "source": SOURCE,
            "entry_id": entry_id,
            "name": name,
            "name_norm": name_norm,
            "category": category or "manual",
            "place_geoid": place_geoid,
            "place_name": place_name,
            "county_geoid": county_geoid,
            "now": now,
            "tags": _tags(added_by, note),
        },
    )
    session.execute(_REINDEX, {"state": state, "name_norm": name_norm, "now": now})
    session.commit()

    resolves = session.execute(
        text(
            "SELECT place_count, place_name FROM gazetteer_name_places "
            "WHERE state = :s AND name_norm = :n"
        ),
        {"s": state, "n": name_norm},
    ).first()
    return {
        "id": entry_id,
        "state": state,
        "name": name,
        "place": place_name,
        # A name already borne elsewhere in the state stays ambiguous, and
        # the entry is kept so the next reader can see it was considered.
        "resolves_to": resolves.place_name if resolves else None,
        "ambiguous": bool(resolves and resolves.place_count != 1),
        "shared_with": [r.name for r in existing],
    }


def _tags(added_by: str, note: str) -> str:
    import json

    return json.dumps({"added_by": added_by.strip(), "note": (note or "").strip()})


def added_places(
    session: Session, *, state: str | None = None, limit: int = 500
) -> list[dict]:
    """Everything added by hand, newest first."""
    import json

    rows = session.execute(
        _ADDED, {"source": SOURCE, "state": state, "limit": limit}
    ).all()
    out = []
    for row in rows:
        tags = row.tags if isinstance(row.tags, dict) else json.loads(row.tags or "{}")
        out.append(
            {
                "state": row.state,
                "name": row.name,
                "place": row.place_name,
                "category": row.category,
                "added_by": tags.get("added_by", ""),
                "note": tags.get("note", ""),
                "added_at": row.created_at,
                # What the INDEX says now, which is what the gate reads --
                # an entry can be present and still answer nothing.
                "resolves_to": row.resolves_to,
                "ambiguous": row.place_count is not None and row.place_count != 1,
            }
        )
    return out
