"""news-crawler geocode-gazetteer — resolve each POI to its Census place.

Fills `gazetteer.place_geoid` / `place_name` / `county_geoid` so the
grounding gate can verify a place the model induced from an institution
the story named, rather than deleting it. See
`src.enrichment.gazetteer_places` for why `tags->>'addr:city'` is not
enough.

Defaults to the entries an article has actually matched -- 11,440 of
558,540 -- because those are the only ones the gate ever reads.
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def add_gazetteer_geocode_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "geocode-gazetteer",
        help="Resolve gazetteer points to Census places, for the grounding gate",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="every point, not only those an article has matched",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--table",
        default="gazetteer",
        choices=["gazetteer", "gazetteer_features"],
        help="which table to resolve; gazetteer_features is the statewide one",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report how many owe a lookup"
    )
    parser.set_defaults(func=handle_gazetteer_geocode_command)


def handle_gazetteer_geocode_command(args: argparse.Namespace) -> int:
    from src.enrichment import gazetteer_places
    from src.models.database import DatabaseManager

    db = DatabaseManager()
    with db.get_session() as session:
        counts = gazetteer_places.geocode(
            session,
            only_matched=not args.all,
            limit=args.limit,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
            table=args.table,
            on_batch=lambda n, c: logger.info(
                "geocoded %s points, %s placed", n, c["placed"]
            ),
        )
    print(
        f"owed a lookup: {counts['pending']}\n"
        f"placed:        {counts['placed']}\n"
        f"no place:      {counts['no_place']}\n"
        f"failed:        {counts['failed']}"
        + ("\n(dry run — nothing written)" if args.dry_run else "")
    )
    return 0
