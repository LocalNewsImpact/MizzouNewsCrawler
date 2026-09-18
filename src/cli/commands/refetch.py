"""news-crawler refetch-articles — rewind an article so its URL is fetched again.

Extraction refuses to re-fetch a URL whose article exists. That is right for
ordinary operation and wrong when the stored body is not the story: a paywall
teaser, a subscription appeal, a form's dropdown list. See
`src/pipeline/refetch.py` for why the rewind is in place rather than a delete.

    # what is waiting to be fetched again
    news-crawler refetch-articles --list --dataset WSU-Washington-State

    # rewind by explicit id list
    news-crawler refetch-articles --ids-file ids.txt \
        --by damon --reason "paywall teaser; subscription now wired"

    # rewind every article in a dataset at a status, shortest bodies first
    news-crawler refetch-articles --dataset WSU-Washington-State \
        --status paywall --by damon --reason "no body; BLOX auth wired"

    # give up on one: put the link back where it was
    news-crawler refetch-articles --clear --ids-file gave_up.txt
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def add_refetch_articles_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "refetch-articles",
        help="Rewind articles so extraction fetches their URLs again",
    )
    parser.add_argument("--dataset", default=None, help="dataset slug")
    parser.add_argument(
        "--status",
        nargs="+",
        default=None,
        help="rewind articles at these statuses (needs --dataset)",
    )
    parser.add_argument(
        "--max-text-length",
        type=int,
        default=None,
        help="only articles whose stored body is shorter than this",
    )
    parser.add_argument("--ids-file", default=None, help="file of article ids")
    parser.add_argument(
        "--by", default=None, help="who asked for the re-fetch (required to rewind)"
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="why the stored body is wrong (required to rewind)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--list", action="store_true", help="show what is already rewound"
    )
    parser.add_argument(
        "--clear", action="store_true", help="put the links back, rewinding nothing"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(func=handle_refetch_command)


def _ids_from_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as handle:
        return [
            line.strip() for line in handle if line.strip() and not line.startswith("#")
        ]


def _ids_from_query(session, args) -> list[str]:
    from sqlalchemy import text

    from src.models.database import safe_session_execute

    sql = """
        SELECT a.id
          FROM articles a
          JOIN datasets d ON d.id = a.dataset_id
         WHERE d.slug = :dataset
    """
    params: dict = {"dataset": args.dataset}
    if args.status:
        sql += " AND a.status = ANY(:statuses)"
        params["statuses"] = list(args.status)
    if args.max_text_length is not None:
        sql += " AND coalesce(a.text_length, 0) < :max_len"
        params["max_len"] = args.max_text_length
    # Shortest first: the least text is the strongest evidence that the stored
    # body is not the story.
    sql += " ORDER BY coalesce(a.text_length, 0)"
    if args.limit:
        sql += " LIMIT :limit"
        params["limit"] = args.limit
    result = safe_session_execute(session, text(sql), params)
    return [row[0] for row in (result.fetchall() if result is not None else [])]


def handle_refetch_command(args) -> int:
    from src.models.database import DatabaseManager
    from src.pipeline import refetch

    db = DatabaseManager()
    with db.get_session() as session:
        if args.list:
            rows = refetch.marked(session, args.dataset)
            if not rows:
                print("nothing is waiting to be fetched again")
                return 0
            print(f"{len(rows)} article(s) rewound and waiting:\n")
            for row in rows:
                print(
                    f"  {row['id']}  {(row['article_status'] or '-'):20}"
                    f"  {str(row['text_length'] or 0):>6} chars"
                )
                print(f"    {row['url']}")
                print(
                    f"    asked by {row['requested_by'] or '?'}"
                    f" at {row['requested_at'] or '?'}"
                    f" (link was {row['previous'] or '?'})"
                )
                print(f"    reason: {row['reason'] or '(none recorded)'}")
            return 0

        if args.ids_file:
            ids = _ids_from_file(args.ids_file)
        elif args.dataset:
            ids = _ids_from_query(session, args)
        else:
            print("refetch needs --ids-file or --dataset")
            return 1

        if args.clear:
            cleared = refetch.clear(session, ids, dry_run=args.dry_run)
            print(f"links restored: {cleared}")
            return 0

        try:
            counts = refetch.mark(
                session, ids, by=args.by, reason=args.reason, dry_run=args.dry_run
            )
        except refetch.Refused as exc:
            print(f"refused: {exc}")
            return 1

        print(
            f"requested: {counts['requested']}\n"
            f"rewound:   {counts['marked']}\n"
            f"already:   {counts['already']}\n"
            f"missing:   {counts['missing']}"
            + ("\n(dry run — nothing written)" if args.dry_run else "")
        )
        if counts.get("missing_ids"):
            for missing in counts["missing_ids"][:10]:
                print(f"  no such article: {missing}")
    return 0
