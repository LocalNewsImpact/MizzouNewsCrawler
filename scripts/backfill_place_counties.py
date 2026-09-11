#!/usr/bin/env python3
"""Give every already-enriched place mention the county it sits in.

A place GEOID does not encode its county. State prefixes county, county
prefixes tract and block, so every other rung of the ladder can be read
off the code -- but 2938000 says state 29 and place 38000 and nothing
about which county that is. Enrichment therefore recorded a place and
stopped, and a story that named only a town was absent from every count
of stories touching a county.

Measured on March 2026 Missouri before this ran: 82 stories published in
Osage County, of which only 19 had any county-level geography at all.

This adds the missing rows to ``article_geoids`` and nothing else:

  * It only INSERTS. No row is updated or deleted, so a re-run is a
    no-op and a mistake here cannot destroy an existing claim.
  * Rolled-up counties carry ``source = 'county_rollup'``. They were
    never mentioned, and an analysis has to be able to count literal
    mentions and containment separately.
  * ``article_enrichment.geoids`` is NOT touched. That column is
    documented as carrying only the mentioned FIPS and the BigQuery
    export reads it; widening its meaning underneath a consumer is a
    different decision from filling a gap.
  * A county already present for the article is left alone, whatever its
    source. What was said outranks what was derived from it.
  * The ancestor rule the live path obeys is obeyed here: a county is
    skipped where a tract or block already carries its digits.

Multi-county places take their primary county. See
``src.enrichment.fips.county_of_place`` for that rule and why.

Usage:
  python scripts/backfill_place_counties.py --dry-run
  python scripts/backfill_place_counties.py --since 2026-03-01 --until 2026-04-01
  python scripts/backfill_place_counties.py --dataset <uuid>
"""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import text

from src.enrichment.fips import county_of_place
from src.models.database import DatabaseManager

# The place rows to consider, and every geoid already on those articles so
# the rollup can tell what is already claimed. Scoped by the article's
# publish date because that is how a corpus is talked about here.
SELECT_SQL = text("""
    SELECT ag.article_id, ag.geoid AS place_geoid
      FROM article_geoids ag
      JOIN articles a ON a.id = ag.article_id
     WHERE ag.geoid_level = 'place'
       AND a.publish_date >= :since
       AND a.publish_date <  :until
       AND (:dataset IS NULL OR a.dataset_id = :dataset)
""")

EXISTING_SQL = text("""
    SELECT ag.article_id, ag.geoid
      FROM article_geoids ag
      JOIN articles a ON a.id = ag.article_id
     WHERE a.publish_date >= :since
       AND a.publish_date <  :until
       AND (:dataset IS NULL OR a.dataset_id = :dataset)
""")

INSERT_SQL = text("""
    INSERT INTO article_geoids
      (article_id, geoid, geoid_level, is_primary, source)
    VALUES (:article_id, :geoid, 'county', false, 'county_rollup')
    ON CONFLICT DO NOTHING
""")


def plan(session, since: str, until: str, dataset: str | None):
    """What would be inserted, without inserting it."""
    args = {"since": since, "until": until, "dataset": dataset}

    have: dict[str, set[str]] = {}
    for article_id, geoid in session.execute(EXISTING_SQL, args):
        have.setdefault(article_id, set()).add(geoid)

    additions: list[tuple[str, str]] = []
    reasons: Counter[str] = Counter()
    spans: Counter[int] = Counter()
    for article_id, place in session.execute(SELECT_SQL, args):
        known = have.setdefault(article_id, set())
        hit = county_of_place(place)
        if hit is None:
            reasons["place not in the crosswalk"] += 1
            continue
        county, span = hit
        if county in known:
            reasons["county already on the article"] += 1
            continue
        # The same ancestor rule the live path obeys.
        if any(len(g) in (11, 15) and g.startswith(county) for g in known):
            reasons["a tract or block already carries it"] += 1
            continue
        additions.append((article_id, county))
        known.add(county)
        spans[span] += 1
        reasons["rolled up"] += 1
    return additions, reasons, spans


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--since", default="2026-03-01")
    parser.add_argument("--until", default="2026-04-01")
    parser.add_argument("--dataset", default=None, help="dataset id, or all")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be inserted and insert nothing",
    )
    args = parser.parse_args()

    db = DatabaseManager()
    with db.get_session() as session:
        additions, reasons, spans = plan(session, args.since, args.until, args.dataset)

        print(f"window {args.since} .. {args.until}")
        print(f"dataset {args.dataset or '(all)'}")
        for reason, n in reasons.most_common():
            print(f"  {n:7,}  {reason}")
        if spans:
            multi = sum(n for span, n in spans.items() if span > 1)
            print(
                f"  of those rolled up, {multi:,} are places spanning more "
                "than one county and took their primary"
            )
        articles = len({a for a, _ in additions})
        print(f"\n{len(additions):,} rows for {articles:,} articles")

        if args.dry_run:
            print("dry run: nothing written")
            return 0

        for article_id, county in additions:
            session.execute(INSERT_SQL, {"article_id": article_id, "geoid": county})
        session.commit()
        print("written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
