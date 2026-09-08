"""Make a link agree with the article that came from it.

33,289 candidate links say `paused` while their own article is settled:
20,209 whose article is enriched, labelled or skipped -- finished work,
in the export -- and 13,080 whose article carries a content verdict of
its own.

Nothing is stopped by this. Both extraction selectors require
`status = 'article'` AND no article row, so a link with an article is
never re-extracted whatever it says. What the wrong status does is lie
to everybody reading it: the Blocked page counted 26,918 links as never
fetched when 8,407 were, and any per-stage tally drawn from
`candidate_links.status` is wrong by the same amount.

HOW THEY GOT THIS WAY
---------------------
A 403 wall pauses a host, not a link: `PAUSE_CANDIDATE_LINKS_SQL` sets
every link on the host to `paused`, including the ones already extracted
weeks earlier. 13,540 carry "Re-paused: already extracted (has article
text)", which says exactly this, and 7,360 more carry no message at all.
Pausing a host is right; leaving the finished links pretending to be
held is the part that was never cleaned up.

THE MAPPING IS READ FROM THE CORPUS, NOT CHOSEN
-----------------------------------------------
Where a link and its article agree, this is what they agree on:

    article enriched            -> link extracted   84%
    article labeled             -> link extracted   74%
    article enrichment_skipped  -> link extracted   76%
    article wire                -> link wire        71%
    article obituary            -> link obituary    63%
    article opinion             -> link opinion     85%
    article weather             -> link weather     85%

So a finished article puts its link at `extracted`, and a content
verdict puts its link at the same verdict. `paused` is the minority
reading in every one of those rows, which is what identifies it as the
error rather than a third convention.
"""

import argparse
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: An article that finished. The link says how far the work got, and the
#: work got all the way, so the link says `extracted` and the article
#: keeps the detail.
FINISHED = ("enriched", "labeled", "enrichment_skipped")
FINISHED_LINK_STATUS = "extracted"

#: An article the pipeline judged. The link repeats the verdict, which is
#: what the post-extraction content rule does when it writes both.
VERDICTS = ("wire", "obituary", "opinion", "weather", "not_article", "paywall")

COUNT_SQL = text("""
    SELECT a.status, count(*)
      FROM candidate_links cl
      JOIN articles a ON a.candidate_link_id = cl.id
     WHERE cl.status = 'paused'
       AND a.status = ANY(:statuses)
     GROUP BY 1 ORDER BY 2 DESC
    """)

#: Bounded and repeatable: the same statement run again finds only what
#: it has not already repaired, so a run that dies halfway costs nothing.
#: Batched because this is 33,289 rows on an instance where a two-minute
#: statement timeout is the default.
REPAIR_SQL = text("""
    UPDATE candidate_links
       SET status = :new_status,
           error_message = NULL
     WHERE id IN (
         SELECT cl.id
           FROM candidate_links cl
           JOIN articles a ON a.candidate_link_id = cl.id
          WHERE cl.status = 'paused'
            AND a.status = ANY(:statuses)
          LIMIT :batch
     )
    """)


def add_link_status_repair_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "repair-link-status",
        help="Set paused links to agree with the article extracted from them",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Rows per statement (default: 2000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change and write nothing",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    parser.set_defaults(func=handle_link_status_repair_command)
    return parser


def _repair(session, statuses, new_status, batch_size, dry_run):
    """Move one group, a batch at a time, and say how many moved."""
    before = {
        row[0]: row[1]
        for row in session.execute(COUNT_SQL, {"statuses": list(statuses)}).fetchall()
    }
    total = sum(before.values())
    for status, count in sorted(before.items(), key=lambda kv: -kv[1]):
        logger.info("  article %s -> link %s: %d", status, new_status, count)
    if dry_run or not total:
        return total, before

    moved = 0
    while moved < total:
        result = session.execute(
            REPAIR_SQL,
            {
                "statuses": list(statuses),
                "new_status": new_status,
                "batch": batch_size,
            },
        )
        if not result.rowcount:
            break
        moved += result.rowcount
        session.commit()
        logger.info("  ... %d of %d", moved, total)
    return moved, before


def handle_link_status_repair_command(args) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level))
    from src.models.database import DatabaseManager

    db = DatabaseManager()
    with db.get_session() as session:
        session.execute(text("SET statement_timeout = '900s'"))

        logger.info("Finished articles, link should read %r:", FINISHED_LINK_STATUS)
        finished, _ = _repair(
            session, FINISHED, FINISHED_LINK_STATUS, args.batch_size, args.dry_run
        )

        # Each verdict moves to its own value, so these run one at a time
        # rather than as a group.
        verdicts = 0
        logger.info("Judged articles, link repeats the verdict:")
        for verdict in VERDICTS:
            moved, _ = _repair(
                session, (verdict,), verdict, args.batch_size, args.dry_run
            )
            verdicts += moved

    suffix = " (dry run)" if args.dry_run else ""
    print(f"finished -> extracted: {finished}{suffix}")
    print(f"verdict  -> verdict:   {verdicts}{suffix}")
    print(f"total:                 {finished + verdicts}{suffix}")
    return 0
