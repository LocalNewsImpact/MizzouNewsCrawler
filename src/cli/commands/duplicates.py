"""The same story, discovered twice, recorded once -- and SAID SO.

WHAT THIS IS FOR. A publisher serves the same article at more than one URL:
`http` and `https`, `www` and bare, a trailing slash, a tracking query. Each
variant is discovered as its own candidate link, and `articles.url` is
unique, so only the first one to be extracted gets an article row.

WHAT USED TO HAPPEN TO THE SECOND ONE

Two ways, and both left a record that says something untrue:

  scripts/cleanup_url_duplicates.py DELETED the newer duplicate article. The
  candidate link it belonged to stayed at `extracted`, pointing at nothing.
  1,458 March links were in that state, and the reporting called them
  "Link says extracted, no article" -- a hole nobody could explain, which
  took a day to trace back to a dedup script run by hand months earlier.

  Extraction's own insert is `ON CONFLICT DO NOTHING` on the URL, so when a
  variant was extracted second the insert quietly did nothing and the link
  was marked `extracted` anyway.

WHAT HAPPENS NOW. Nothing is deleted. The duplicate link is marked
`duplicate` and its `error_message` names the link whose article survived,
so the record says what it is: a second URL for a story the corpus already
has. Deleting is what made this invisible; a status is what makes it
answerable.

A survivor is the link whose article exists. Where several survive the
oldest wins, which is the rule the old script used and the one the corpus
was built on.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: What a link is set to when the corpus already holds its story under
#: another URL. Selected by no stage: extraction reads `article`,
#: classification and enrichment read article statuses.
DUPLICATE = "duplicate"

#: Strip what makes two URLs for one story look different: the scheme,
#: `www.`, a query string or fragment, and a trailing slash.
#:
#: Applied to BOTH sides of every comparison here. The old script stripped
#: only the scheme and `www.`, which is why 343 of the links it orphaned
#: could not be matched back to their survivor afterwards.
NORMALISE = (
    "lower(regexp_replace(regexp_replace(regexp_replace("
    "{col}, '^https?://(www\\.)?', ''), '[?#].*$', ''), '/+$', ''))"
)


def _norm(col: str) -> str:
    return NORMALISE.format(col=col)


def orphaned_links(session, source_id: str) -> list[tuple[str, str, str]]:
    """Links whose story the corpus holds under a different URL.

    ONE SOURCE AT A TIME. Normalising every URL in the corpus against every
    other is a full scan of 160,000 articles and it does not finish inside
    a statement timeout -- measured, twice. A publisher's duplicates are
    always its own URLs, so the comparison belongs inside one source, where
    it is a few hundred rows against a few thousand.

    Returns (link id, the link's URL, the surviving article's id).
    """
    rows = session.execute(
        text(f"""
            WITH mine AS (
                SELECT cl.id, cl.url, {_norm('cl.url')} AS norm
                FROM candidate_links cl
                WHERE cl.source_id = :source_id
                AND cl.status = 'extracted'
                AND NOT EXISTS (
                    SELECT 1 FROM articles a WHERE a.candidate_link_id = cl.id
                )
            ),
            survivors AS (
                SELECT a.id, {_norm('a.url')} AS norm, a.created_at
                FROM articles a
                JOIN candidate_links c2 ON c2.id = a.candidate_link_id
                WHERE c2.source_id = :source_id
            )
            SELECT DISTINCT ON (m.id) m.id, m.url, s.id
            FROM mine m JOIN survivors s ON s.norm = m.norm
            ORDER BY m.id, s.created_at
            """),
        {"source_id": source_id},
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def mark(session, resolved: list[tuple[str, str, str]]) -> int:
    """Record each link as a duplicate of the story that survived.

    An UPDATE, never a DELETE. The link is the evidence that the publisher
    served this URL, and the crawler found it; throwing it away is what
    produced a hole nobody could read.
    """
    if not resolved:
        return 0
    count = 0
    for link_id, _url, survivor in resolved:
        count += session.execute(
            text(
                "UPDATE candidate_links SET status = :status, "
                "error_message = :why WHERE id = :id AND status = 'extracted'"
            ),
            {
                "status": DUPLICATE,
                "why": f"Duplicate URL; the corpus holds this story as article {survivor}",
                "id": link_id,
            },
        ).rowcount
    session.commit()
    return count


def add_duplicates_parser(subparsers):
    parser = subparsers.add_parser(
        "duplicates",
        help="Mark candidate links whose story the corpus holds under another URL",
    )
    parser.add_argument(
        "--source",
        help="One source id. Without it, every active source, one at a time.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write the statuses. Without it nothing is written: this changes "
            "what the reporting counts, and a run that does that when "
            "somebody meant to look is a run nobody trusts again."
        ),
    )
    parser.add_argument(
        "--limit-sources",
        type=int,
        default=None,
        help="Stop after this many sources (for a bounded first pass).",
    )
    return parser


def handle_duplicates_command(args) -> int:
    from src.models.database import DatabaseManager

    db = DatabaseManager()
    with db.get_session() as session:
        if args.source:
            sources = [args.source]
        else:
            rows = session.execute(
                text("SELECT id FROM sources WHERE status = 'active' ORDER BY id")
            ).fetchall()
            sources = [r[0] for r in rows]
            if args.limit_sources:
                sources = sources[: args.limit_sources]

        total = 0
        marked = 0
        for source_id in sources:
            resolved = orphaned_links(session, source_id)
            if not resolved:
                continue
            total += len(resolved)
            logger.info(
                "%s: %d links whose story the corpus already holds",
                source_id,
                len(resolved),
            )
            if args.apply:
                marked += mark(session, resolved)

        print(f"duplicates found: {total}")
        if args.apply:
            print(f"marked `{DUPLICATE}`: {marked}")
        else:
            print("nothing written. Pass --apply to record them.")
    return 0
