"""Re-check already-written geography against the article it came from.

The gate in `grounding` runs on the write path, so it protects what is
enriched from now on. It does nothing for the 20,521 rows already in the
database, 97.4% of which are March -- the month BigQuery treats as
authoritative. This re-reads each stored code as a place name and asks
the same question the gate asks, and removes what the article does not
support.

WHY THE LADDER HAS TO BE REBUILT AND NOT MERELY PRUNED.

`article_geoids.source` records how each code got there: `point` and
`mention` are claims about the article, `county_rollup` is derived from
them by `build_story_geoids`, `scope_state` comes from the scope
classification, and `human` is what a person put in. County rollups are
the largest category in the table -- 17,819 rows against 16,796 mentions
-- because every place mention contributes the county it sits in. So
dropping an unsupported city and stopping there leaves its county
standing, which is the whole complaint: a Mexico graduation story and a
Rolla arrest, filed under Boone, would still be filed under Boone.

Rollups are therefore discarded and recomputed from the survivors, by
the same `county_of_place` crosswalk the write path uses.

WHAT IS NEVER TOUCHED.

`human` rows. A person's contribution is not a model claim and is not
re-litigated by a heuristic. `scope_state` likewise: it says the story is
statewide, which is a classification rather than an assertion that a
place was named. And a code whose name cannot be read back out of the
gazetteer is left exactly as it is -- unverifiable is not the same as
unsupported, and a backfill that cannot see something must not delete it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.enrichment.fips import county_of_place, name_for
from src.enrichment.grounding import grounded

#: (geoid, level, is_primary, source)
GeoidRow = tuple[str, str | None, bool, str | None]

#: Sources that are not claims about the article's text.
NOT_A_TEXT_CLAIM = frozenset({"human", "scope_state"})

#: Neither is a state rung. It is reached by the ladder rather than
#: asserted, and a story does not have to print the word "Missouri" to be
#: in Missouri -- testing it as a name drops 2,070 rows for saying "MO",
#: which is a state abbreviation and not a sentence anybody writes.
NOT_A_TEXT_LEVEL = frozenset({"state"})


@dataclass
class Regrounded:
    """What survives for one article, and what does not."""

    kept: list[GeoidRow] = field(default_factory=list)
    dropped: list[GeoidRow] = field(default_factory=list)
    unverifiable: list[GeoidRow] = field(default_factory=list)
    point_cleared: bool = False

    @property
    def mention_codes(self) -> list[str]:
        """What `article_enrichment.geoids` should now hold: the flat
        column carries only non-primary codes (decided 2026-08-21)."""
        out: list[str] = []
        for geoid, _level, primary, _source in self.kept:
            if not primary and geoid not in out:
                out.append(geoid)
        return out


def bare_name(geoid: str | None) -> str | None:
    """The place name behind a stored code, without its state suffix."""
    label = name_for(geoid)
    return label.rsplit(",", 1)[0].strip() if label else None


def regrounded(
    rows: list[GeoidRow],
    *,
    content: str | None,
    title: str | None = None,
    publication_city: str | None = None,
    institution_places: list[str] | None = None,
) -> Regrounded:
    """Which of an article's stored codes its own text still supports."""
    result = Regrounded()
    survivors: list[str] = []

    for row in rows:
        geoid, level, primary, source = row
        if source in NOT_A_TEXT_CLAIM or level in NOT_A_TEXT_LEVEL:
            result.kept.append(row)
            continue
        if source == "county_rollup":
            continue  # derived; recomputed from the survivors below
        name = bare_name(geoid)
        if name is None:
            result.unverifiable.append(row)
            result.kept.append(row)
            continue
        if grounded(
            name,
            content=content,
            title=title,
            publication_city=publication_city,
            institution_places=institution_places,
        ):
            result.kept.append(row)
            if level == "place":
                survivors.append(geoid)
        else:
            result.dropped.append(row)
            if primary or source == "point":
                result.point_cleared = True

    # Rebuild the county rung from what is left, mirroring
    # `build_story_geoids`: one county per surviving place, never where a
    # tract or block already carries its digits.
    have = {geoid for geoid, _l, _p, _s in result.kept}
    for geoid in survivors:
        hit = county_of_place(geoid)
        if hit is None or hit[0] in have:
            continue
        county = hit[0]
        if any(len(o) in (11, 15) and o.startswith(county) for o in have):
            continue
        result.kept.append((county, "county", False, "county_rollup"))
        have.add(county)

    # Stored rollups the survivors no longer justify.
    for row in rows:
        if row[3] == "county_rollup" and row[0] not in have:
            result.dropped.append(row)

    return result
