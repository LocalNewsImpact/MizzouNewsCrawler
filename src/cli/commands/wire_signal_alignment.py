"""Record one syndicator one way.

`articles.wire` holds the same fact in two shapes. 14,681 values are a
service name -- "The Associated Press", "CNN" -- and 6,373 are a bare
domain, because `canonical_cross_domain` records the host it found the
canonical pointing at and every other method records a name.

So the Columbia Missourian is `Columbia Missourian` on the rows a byline
identified and `columbiamissourian.com` on the 600 a canonical did. The
service filter in the review console groups by value, which means it
offers the same syndicator twice and each option finds part of its work.
Any count of "how much did this newsroom syndicate" is wrong by whichever
half it missed.

Nothing here changes a verdict. The detection was right -- 228 KOMU
articles really are the Missourian's, found by the canonical tag and
found accurately. Only the name is rewritten, from the host to what the
source record already calls that publisher.

WHY NOT A PATTERN INSTEAD
-------------------------
The first attempt at this added regexes to `wire_services` for the three
Mizzou newsrooms, so their names would be matched in article text the way
the Associated Press is. That was the wrong instrument: these articles
are already being identified, accurately, and a content pattern on
"KOMU 8" or "Columbia Missourian" would fire on any story that mentions
either in passing -- a new way to be wrong about work already being got
right. The signal exists; it just is not written down the same way twice.

THE DOMAIN IS THE SYNDICATOR OF RECORD
--------------------------------------
Where no name exists in the database, the domain stands as the name.
That is the rule, not a shortfall: 287 hosts appear here that nothing
else records -- tvinsider.com, liveinformed.com, fooddrinklife.com,
theconversation.com, talker.news -- and they are real syndicators. A
controlled vocabulary for them would mean somebody writing 287 display
names, keeping them current as the list grows, and deciding case by case
whether legacy.com and buzzsprout.com are syndicators or infrastructure.

`tvinsider.com` is a worse name than "TV Insider" and a much better one
than a blank, an invented spelling, or a row quietly dropped for want of
a label. It is also exact: it is what the canonical tag said, so a
reviewer can check it. Where the corpus does hold a name -- because the
publisher is a source we crawl -- that name wins, because it is the
name the rest of the console already uses for them.
"""

import argparse
import json
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: A value shaped like a host: it has a dot and no spaces. Every service
#: name in the corpus has a space or no dot; every domain has both.
DOMAIN_SHAPED = "elem LIKE '%.%' AND elem NOT LIKE '% %'"

#: What each domain should be called, from the source record that already
#: names it. `www.` is tried both ways because the corpus holds hosts in
#: both forms and the canonical tag can carry either.
RESOLVE_SQL = text(f"""
    SELECT DISTINCT elem AS host,
           (SELECT so.canonical_name
              FROM sources so
             WHERE so.canonical_name IS NOT NULL
               AND (so.host = elem
                    OR so.host = 'www.' || elem
                    OR replace(so.host, 'www.', '') = elem)
             LIMIT 1) AS display_name
      FROM articles a, LATERAL json_array_elements_text(a.wire) elem
     WHERE a.status = 'wire'
       AND json_typeof(a.wire) = 'array'
       AND {DOMAIN_SHAPED}
    """)

FIND_SQL = text("""
    SELECT a.id, a.wire::text
      FROM articles a
     WHERE a.status = 'wire'
       AND json_typeof(a.wire) = 'array'
       AND a.wire::text LIKE :needle
     LIMIT :batch
    """)

WRITE_SQL = text("UPDATE articles SET wire = CAST(:wire AS json) WHERE id = :id")


def add_wire_signal_alignment_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "align-wire-signal",
        help="Record a syndicator by name where a domain was stored",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change and write nothing",
    )
    parser.add_argument(
        "--batch-size", type=int, default=2000, help="Rows per pass (default: 2000)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    parser.set_defaults(func=handle_wire_signal_alignment_command)
    return parser


def _renamed(raw, names):
    """The wire array with known hosts replaced by their display name.

    Returns None where nothing changes, so an article already recorded
    correctly is not rewritten. Order is preserved and duplicates are
    dropped: a row naming both `komu.com` and `KOMU` becomes one KOMU.
    """
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(value, list):
        return None

    # A host with no name in the database keeps its host. That is the
    # syndicator of record, not a gap waiting to be filled.
    out, seen = [], set()
    for item in value:
        if not isinstance(item, str):
            continue
        name = names.get(item.strip().lower(), item)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out if out != value else None


def handle_wire_signal_alignment_command(args) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level))
    from src.models.database import DatabaseManager

    db = DatabaseManager()
    with db.get_session() as session:
        session.execute(text("SET statement_timeout = '900s'"))

        names, unknown = {}, []
        for host, display in session.execute(RESOLVE_SQL).fetchall():
            if display:
                names[host.strip().lower()] = display
            else:
                unknown.append(host)
        logger.info("%d hosts resolve to a source; %d do not", len(names), len(unknown))
        for host in sorted(unknown)[:10]:
            logger.debug("no source record: %s", host)

        changed = 0
        for host, display in sorted(names.items()):
            rows = session.execute(
                FIND_SQL, {"needle": f'%"{host}"%', "batch": args.batch_size}
            ).fetchall()
            for article_id, raw in rows:
                renamed = _renamed(raw, names)
                if renamed is None:
                    continue
                if not args.dry_run:
                    session.execute(
                        WRITE_SQL, {"wire": json.dumps(renamed), "id": article_id}
                    )
                changed += 1
            if rows and not args.dry_run:
                session.commit()
            logger.info("  %-34s -> %-34s %d rows", host, display, len(rows))

    print(f"hosts resolved:   {len(names)}")
    print(f"hosts unresolved: {len(unknown)}  (left as they are)")
    print(f"articles renamed: {changed}{' (dry run)' if args.dry_run else ''}")
    return 0
