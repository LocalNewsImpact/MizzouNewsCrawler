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
        "--state", required=True, help="USPS code or full name, e.g. MO or Missouri"
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
