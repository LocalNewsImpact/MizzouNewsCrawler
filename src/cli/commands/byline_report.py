"""The byline reports for a dataset, and the decisions behind them.

Three things one command does, because they are one question asked at three
stages of the same work:

    candidates  which byline strings a person should look at, worst first
    records     one row per person per article: the aligned author records
    bylines     every unique local byline, and the hosts it appears on
    hosts       every host, and how many unique bylines it carries

The reports resolve through `byline_normalizations`: a string a reviewer has
decided about is counted as the person it names, not as the string. Undecided
strings are counted as the splitter reads them, so a report can be run before
any review has happened -- it is then a report of what the parser produced,
which is the thing the review is about.

`apply` writes decided names onto `articles.author` for that dataset. The table
is the decision and the article is the record; the two are kept together so a
later extraction writing the raw form again can be corrected without a person
deciding twice.
"""

import argparse
import csv
import json
import logging
import sys

from src.services import byline_review as br

logger = logging.getLogger(__name__)


def add_byline_report_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "byline-report",
        help="Byline review candidates and the per-dataset byline reports",
    )
    parser.add_argument(
        "kind",
        choices=("candidates", "records", "bylines", "hosts", "apply"),
        help="What to produce; `apply` writes decided names onto the articles",
    )
    parser.add_argument("--dataset", required=True, help="Name, slug or UUID")
    parser.add_argument("--out", help="Write CSV here instead of stdout")
    parser.add_argument(
        "--limit", type=int, default=None, help="First N rows (candidates)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="apply: say what would be written, write nothing",
    )
    return parser


def _write(rows, fieldnames, out):
    handle = open(out, "w", newline="") if out else sys.stdout
    try:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if out:
            handle.close()
    return len(rows)


def handle_byline_report_command(args) -> int:
    from sqlalchemy import text

    from src.models.database import DatabaseManager
    from src.utils.dataset_utils import resolve_dataset_id

    logging.basicConfig(level=logging.INFO)
    db = DatabaseManager()
    dataset_id = resolve_dataset_id(db.engine, args.dataset)
    if not dataset_id:
        print(f"No such dataset: {args.dataset}")
        return 1

    with db.get_session() as session:
        rows = br.dataset_rows(session, dataset_id)
        per_article = (
            br.article_rows(session, dataset_id) if args.kind == "records" else []
        )

        if args.kind == "apply":
            pending = session.execute(
                text(
                    "SELECT id, raw_byline, canonical_names FROM byline_normalizations"
                    " WHERE dataset_id = :dataset_id AND applied_at IS NULL"
                ),
                {"dataset_id": dataset_id},
            ).fetchall()
            written = 0
            for row in pending:
                names = row[2]
                if isinstance(names, str):
                    names = json.loads(names)
                if args.dry_run:
                    print(f"would write {br.rendered(names)!r} over {row[1]!r}")
                    continue
                count = br.apply_decision(session, dataset_id, row[1], names)
                session.execute(
                    text(
                        "UPDATE byline_normalizations SET applied_at = CURRENT_TIMESTAMP,"
                        " articles_updated = :n WHERE id = :id"
                    ),
                    {"n": count, "id": row[0]},
                )
                written += count
            if not args.dry_run:
                session.commit()
            print(f"decisions: {len(pending)}  articles written: {written}")
            return 0

    if args.kind == "candidates":
        found = br.candidates(rows)
        if args.limit:
            found = found[: args.limit]
        out = [
            {
                "signal": row.top_signal or "",
                "what": br.SIGNAL_LABELS.get(row.top_signal or "", ""),
                "raw_byline": row.raw,
                "articles": row.articles,
                "proposed": br.rendered(row.proposed),
                "variants": " | ".join(row.variants),
                "hosts": len(row.hosts),
                "host_list": ", ".join(row.hosts),
                "owners": len(row.owners),
                "owner_list": ", ".join(row.owners),
            }
            for row in found
        ]
        fields = [
            "signal",
            "what",
            "raw_byline",
            "articles",
            "proposed",
            "variants",
            "hosts",
            "host_list",
            "owners",
            "owner_list",
        ]
    elif args.kind == "records":
        out = br.author_records(per_article)
        if args.limit:
            out = out[: args.limit]
        fields = [
            "article_id",
            "byline",
            "position",
            "of_authors",
            "host",
            "owner",
            "publish_date",
            "title",
            "raw_byline",
        ]
    elif args.kind == "bylines":
        out = br.bylines_with_hosts(rows)
        fields = [
            "byline",
            "articles",
            "hosts",
            "host_list",
            "owners",
            "owner_list",
            "raw_forms",
        ]
    else:
        out = br.hosts_with_bylines(rows)
        fields = ["host", "unique_bylines", "articles", "owner"]

    written = _write(out, fields, args.out)
    if args.out:
        print(f"{written} rows -> {args.out}")
    return 0
