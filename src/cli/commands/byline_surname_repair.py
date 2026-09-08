"""Give back the surnames a wire-service list took, and the articles with them.

`BylineCleaner.WIRE_SERVICES` holds bare brand tokens -- "fox", "ap",
"nbc", "abc", "cbs", "hearst" -- and every one of them is also a surname.
The word filter that removed them ran over names the cleaner had already
identified as people: `protected_spans` was built and never read.

So a reporter called Fox lost her surname and her article was excluded as
syndicated by "fox". 460 articles, across The Examiner (Jeffrey Fox, 371),
KCUR (Madeline Fox), the Columbia Missourian and Boone County Journal
(Molly Fox), and KQTV, where "NBC Olympics" is a real network credit and
is left alone.

Two things were damaged and only one of them heals by itself. The status
can be rewound. The byline cannot: what was stored is "Jeffrey", the raw
capture is not kept, and the archived HTML is thirty days old at most.
What is kept is both halves -- `metadata.byline.authors` and
`metadata.byline.wire_services` -- so the name is rebuilt from them, and
only where there is exactly one of each, which is the shape every one of
these rows has. Anything ambiguous is reported and left alone.
"""

import argparse
import json
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: Tokens that are brands to a wire-service list and surnames to a
#: newsroom. `nbc` is deliberately absent: "NBC Olympics" is a credit,
#: not a person, and those rows are correctly excluded.
SURNAME_TOKENS = ("fox", "hearst", "abc", "cbs", "ap")

#: What the status is rewound to. `cleaned` is where an article sits
#: before enrichment reads it, which is where these belong.
REWIND_TO = "cleaned"

FIND_SQL = text("""
    SELECT a.id, a.author, a.status, a.wire::text,
           (a.metadata::jsonb)->'byline' AS byline_meta
      FROM articles a
     WHERE a.status = 'wire'
       AND a.wire::text = ANY(:shapes)
    """)


#: Hoisted to a module constant so something can execute it.
#:
#: This lived inside the function, which is why nothing ever asked a
#: database to parse it: the tests read the SQL as text and the command
#: shipped carrying `:note::jsonb`, which pg8000 will not accept. A
#: statement no test can reach is a statement no test is checking.
REPAIR_SQL = text("""
    UPDATE articles
       SET author = :name,
           status = :rewind,
           wire = NULL,
           metadata = CAST(jsonb_set(
               CAST(metadata AS jsonb),
               '{byline_surname_repair}',
               -- CAST, not `:note::jsonb`. pg8000 rewrites named
               -- parameters to positional ones and the `::` immediately
               -- after one does not survive it: 42601, syntax error at
               -- ":". The same driver quirk behind the 42P18 failures
               -- in services/work_queue.py.
               CAST(:note AS jsonb),
               true
           ) AS json)
     WHERE id = :id
    """)


def add_byline_surname_repair_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "repair-byline-surnames",
        help="Restore surnames a wire-service token removed, and the articles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change and write nothing",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Stop after this many articles",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    parser.set_defaults(func=handle_byline_surname_repair_command)
    return parser


def _rebuilt_name(author: str | None, byline_meta) -> str | None:
    """ "Jeffrey" plus a removed "fox" is "Jeffrey Fox", or nothing.

    Nothing, rather than a guess, wherever the row does not have exactly
    one author and exactly one removed token: two of either and the word
    order is no longer known, and a byline invented here would be
    indistinguishable from one somebody reported.
    """
    if not (author or "").strip():
        return None
    if isinstance(byline_meta, str):
        try:
            byline_meta = json.loads(byline_meta)
        except ValueError:
            return None
    if not isinstance(byline_meta, dict):
        return None

    authors = byline_meta.get("authors") or []
    services = byline_meta.get("wire_services") or []
    if len(authors) != 1 or len(services) != 1:
        return None
    if authors[0].strip() != author.strip():
        return None
    token = str(services[0]).strip()
    if token.lower() not in SURNAME_TOKENS:
        return None
    return f"{author.strip()} {token.capitalize()}"


def handle_byline_surname_repair_command(args) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level))
    from src.models.database import DatabaseManager

    shapes = [json.dumps([t]) for t in SURNAME_TOKENS]
    repaired = skipped = 0
    db = DatabaseManager()
    with db.get_session() as session:
        rows = session.execute(FIND_SQL, {"shapes": shapes}).fetchall()
        logger.info("Found %d articles excluded on a surname", len(rows))

        for article_id, author, _status, _wire, byline_meta in rows:
            if args.limit and repaired >= args.limit:
                break
            name = _rebuilt_name(author, byline_meta)
            if not name:
                skipped += 1
                logger.debug("Ambiguous, left alone: %s (%r)", article_id, author)
                continue
            if not args.dry_run:
                session.execute(
                    REPAIR_SQL,
                    {
                        "name": name,
                        "rewind": REWIND_TO,
                        "id": article_id,
                        # Said on the row, because a byline this command
                        # rebuilt is not one a reporter filed.
                        "note": json.dumps(
                            {
                                "was": author,
                                "rebuilt": name,
                                "reason": "surname matched a wire-service token",
                            }
                        ),
                    },
                )
            repaired += 1

        if not args.dry_run:
            session.commit()

    print(f"found:    {repaired + skipped}")
    print(f"repaired: {repaired}{' (dry run)' if args.dry_run else ''}")
    print(f"skipped:  {skipped}  (ambiguous, left alone)")
    return 0
