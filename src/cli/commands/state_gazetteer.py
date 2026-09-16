"""news-crawler load-state-gazetteer — install one state's POI extract.

The per-publisher gazetteer cannot verify induced geography: every
candidate sits within 22.2 miles of one publisher, so a match resolves
near that publisher whatever the story says. See
docs/STATEWIDE_GAZETTEER.md §1.

This installs a state from `gs://mizzou-osm-extracts/poi/`, built by
scripts/build_osm_poi_extract.py from a Geofabrik PBF. Loads are
idempotent, so running it twice costs a scan and writes nothing.

The name index (§3.1) is rebuilt separately because it counts
`place_geoid`, which `geocode-gazetteer` fills in afterwards.
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def add_state_gazetteer_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "load-state-gazetteer",
        help="Install a state's POI extract for statewide entity matching",
    )
    parser.add_argument(
        "--state", default=None, help="USPS code or full name, e.g. MO or Missouri"
    )
    parser.add_argument(
        "--compute-scopes",
        action="store_true",
        help="record which states each source may match against (§9)",
    )
    parser.add_argument(
        "--from-file", default=None, help="load this CSV instead of the bucket"
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="recount names per place afterwards (needs geocoding done first)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(func=handle_state_gazetteer_command)


def handle_state_gazetteer_command(args: argparse.Namespace) -> int:
    from src.models.database import DatabaseManager
    from src.pipeline import statewide_gazetteer as sg

    db = DatabaseManager()
    with db.get_session() as session:
        if args.compute_scopes:
            return _compute_scopes(session, sg, dry_run=args.dry_run)
        if not args.state:
            print("--state is required unless --compute-scopes is given")
            return 1
        uri = sg.extract_uri(args.state)
        if uri is None and not args.from_file:
            # The state is never guessed: 896 of 901 Vermont sources
            # arrive without one, and defaulting it built gazetteers in
            # the wrong state without failing loudly.
            print(f"unresolvable state {args.state!r} — nothing loaded")
            return 1
        print(f"source: {args.from_file or uri}")
        counts = sg.load_state(
            session, args.state, path=args.from_file, dry_run=args.dry_run
        )
        print(
            f"read:    {counts['read']}\nwritten: {counts['written']}"
            + ("\n(dry run — nothing written)" if args.dry_run else "")
        )
        if args.rebuild_index and not args.dry_run:
            index = sg.rebuild_name_index(session, args.state)
            print(
                f"names indexed: {index['names']}\n"
                f"  of those unambiguous (usable as evidence): {index['unambiguous']}"
            )
    return 0


def _compute_scopes(session, sg, *, dry_run: bool) -> int:
    """Record every source's reachable states.

    A source's own 20-mile OSM build already answered "what is within
    reach"; joining it to the state-keyed features says which states
    those were. The home state is always in scope; another state needs
    `BORDER_SHARE` of the build, because 17 sources touch a neighbour by
    a handful of POIs and opening a whole state's gazetteer on that is
    the error §9 exists to prevent.
    """
    from sqlalchemy import text

    # The source's own state wins; the DATASET's default_state fills a
    # gap; neither means no scope, never a guess. That is exactly
    # `resolve_source_state`'s contract, and it is why 901 Vermont
    # sources -- 896 of which carry no state -- depend on their dataset
    # declaring one.
    sources = session.execute(text("""
            SELECT s.id, s.host,
                   COALESCE(NULLIF(s.metadata->>'state', ''),
                            d.metadata->>'default_state')
              FROM sources s
              LEFT JOIN dataset_sources ds ON ds.source_id = s.id
              LEFT JOIN datasets d ON d.id = ds.dataset_id
             GROUP BY s.id, s.host, s.metadata->>'state',
                      d.metadata->>'default_state'
             ORDER BY s.host
        """)).all()
    multi = home_only = none = 0
    for source_id, host, declared in sources:
        scope = sg.reachable_states(session, source_id, home=declared)
        if not scope:
            none += 1
            continue
        multi += 1 if len(scope) > 1 else 0
        home_only += 1 if len(scope) == 1 else 0
        if not dry_run:
            sg.store_scope(session, source_id, scope)
        if len(scope) > 1:
            detail = " ".join(f"{e['state']}:{e['pois']}" for e in scope)
            logger.info("%s reaches %s", host, detail)
    if not dry_run:
        session.commit()
    print(
        f"sources:            {len(sources)}\n"
        f"  one state:        {home_only}\n"
        f"  two or more:      {multi}\n"
        f"  no scope at all:  {none}"
        + ("\n(dry run — nothing written)" if dry_run else "")
    )
    return 0
