"""Points the gate refused once and would now keep.

`reground` only removes: it re-reads stored geography and deletes what the
article does not support. Nothing runs the other way. So when the evidence
improves -- a school the gazetteer had never heard of, a short form no
story spells out -- the places the model had already designated stay
refused, because the decision was taken at enrichment and nothing revisits
it.

Re-enriching would revisit it and is the wrong tool. Measured over 279
articles on 2026-09-16: the model, asked the same question twice with the
same prompt, moved 34 of 167 points and demoted 32 of them from a city to
the county around it. The churn is larger than the effect.

This does not ask the model anything. The claim is already stored in
`article_places` with its geoid; the only thing that changed is whether
the gate can defend it. So it reads the claim, asks `grounded` once, and
writes the point where the answer is now yes.

    text alone                18 of 710
    OSM institutions          92
    + federal schools        157
    + short forms            169

`point_method` records `restored` so a row written this way is
distinguishable from one the model placed, and `point_support` records
WHICH clause kept it, as the write path does.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.enrichment.grounding import support_for

logger = logging.getLogger(__name__)

METHOD = "restored"

#: A claim the model designated, on a local story that has no point. The
#: scope filter is the model's own judgement that the story HAS a single
#: local setting; a regional story with no point is not a failure.
_CANDIDATES = text("""
    SELECT p.article_id,
           COALESCE(NULLIF(p.city, ''), p.county) AS place,
           p.full_name, p.geoid, p.geoid_level, p.lat, p.lon,
           a.title, COALESCE(a.raw, a.text, '') AS content,
           s.city AS publication_city
      FROM article_places p
      JOIN article_enrichment e ON e.article_id = p.article_id
      JOIN articles a ON a.id = p.article_id
      LEFT JOIN candidate_links cl ON cl.id = a.candidate_link_id
      LEFT JOIN sources s ON s.id = cl.source_id
     WHERE p.is_point
       AND p.geoid IS NOT NULL
       AND e.point_geoid IS NULL
       AND e.scope IN ('city_municipality', 'neighborhood_community')
       AND COALESCE(NULLIF(p.city, ''), p.county) IS NOT NULL
     ORDER BY p.article_id
""")

_INSTITUTIONS = text("""
    SELECT DISTINCT np.place_name
      FROM article_entities ae
      JOIN articles a ON a.id = ae.article_id
      JOIN candidate_links cl ON cl.id = a.candidate_link_id
      JOIN source_gazetteer_scope sc ON sc.source_id = cl.source_id
      JOIN gazetteer_name_places np
        ON np.state = sc.state AND np.name_norm = ae.entity_norm
     WHERE ae.article_id = :id
       AND np.place_count = 1
       AND np.place_name IS NOT NULL
""")

_WRITE = text("""
    UPDATE article_enrichment
       SET point_place = :place,
           point_geoid = :geoid,
           point_geoid_level = :level,
           point_lat = :lat,
           point_lon = :lon,
           point_method = :method,
           point_support = :support
     WHERE article_id = :id
       AND point_geoid IS NULL
""")


def restorable(session: Session, *, limit: int | None = None) -> list[dict]:
    """Every refused point the gate would now keep, newest evidence applied.

    One article can carry several designated claims. The FIRST that the
    gate accepts wins, in the order the model wrote them, because a second
    point would be a second answer to a question with one.
    """
    rows = session.execute(_CANDIDATES).mappings().all()
    cache: dict[str, list[str]] = {}
    taken: set[str] = set()
    out: list[dict] = []
    for row in rows:
        article_id = row["article_id"]
        if article_id in taken:
            continue
        if article_id not in cache:
            cache[article_id] = [
                r[0] for r in session.execute(_INSTITUTIONS, {"id": article_id})
            ]
        support = support_for(
            row["place"],
            content=row["content"],
            title=row["title"],
            publication_city=row["publication_city"],
            institution_places=cache[article_id],
        )
        if not support:
            continue
        taken.add(article_id)
        out.append(
            {
                "id": article_id,
                "place": row["place"],
                "full_name": row["full_name"],
                "geoid": row["geoid"],
                "level": row["geoid_level"],
                "lat": row["lat"],
                "lon": row["lon"],
                "support": support,
            }
        )
        if limit and len(out) >= limit:
            break
    return out


def restore(
    session: Session, *, dry_run: bool = True, limit: int | None = None
) -> dict:
    """Write those points. `dry_run` reports and writes nothing."""
    found = restorable(session, limit=limit)
    counts = {"candidates": len(found), "written": 0, "named": 0, "institution": 0}
    for row in found:
        counts[row["support"]] = counts.get(row["support"], 0) + 1
    if dry_run:
        counts["dry_run"] = 1
        return counts

    now = datetime.now(timezone.utc)
    for row in found:
        result = session.execute(
            _WRITE,
            {
                "id": row["id"],
                "place": row["place"],
                "geoid": row["geoid"],
                "level": row["level"],
                "lat": row["lat"],
                "lon": row["lon"],
                "method": METHOD,
                "support": row["support"],
            },
        )
        # `rowcount` is on the CursorResult an UPDATE actually returns;
        # `Session.execute` is typed as the wider `Result`, which has no
        # such attribute. Asked for rather than asserted.
        counts["written"] += getattr(result, "rowcount", 0) or 0
    session.commit()
    logger.info(
        "restored %d points (%d named, %d institution) at %s",
        counts["written"],
        counts["named"],
        counts["institution"],
        now,
    )
    return counts
