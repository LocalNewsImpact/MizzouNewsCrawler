"""The byline reports for a dataset, and the decisions behind them.

Three things one command does, because they are one question asked at three
stages of the same work:

    candidates  which byline strings a person should look at, worst first
    fix-literals  rewrite `["A", "B"]` rows to the current form -- no review
    records     one row per person per article: the aligned author records
    bylines     every unique local byline, and the hosts it appears on
    hosts       every host, and how many unique bylines it carries
    owners      every owner string, its spellings, and its ultimate owner
    refresh     recompute the queue into `byline_review_candidates`, which is
                what datadesk's review page reads

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
        choices=(
            "candidates",
            "records",
            "bylines",
            "hosts",
            "owners",
            "refresh",
            "apply",
            "fix-literals",
            "stale",
        ),
        help="What to produce; `apply` writes decided names onto the articles",
    )
    parser.add_argument(
        "--signal",
        default=None,
        help=(
            "stale: send every decided string carrying this signal back to "
            "the queue, keeping its answer. `cross_owner` is the one that "
            "goes stale on its own -- it is read through `owner_groups` and "
            "`sources.owner`, so an answer is only as good as the ownership "
            "recorded the day it was given."
        ),
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="stale: what changed under the old answer (required)",
    )
    parser.add_argument("--dataset", required=True, help="Name, slug or UUID")
    parser.add_argument("--out", help="Write CSV here instead of stdout")
    parser.add_argument(
        "--statuses",
        nargs="+",
        default=None,
        help=(
            "Article statuses to read. Default is the exported local set: "
            f"{', '.join(br.LOCAL_STATUSES)}. Mizzou has 81,786 more at "
            "`labeled` -- classified, never enriched, never exported."
        ),
    )
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

    from src.models.database import DatabaseManager
    from src.utils.dataset_utils import resolve_dataset_id

    logging.basicConfig(level=logging.INFO)
    db = DatabaseManager()
    dataset_id = resolve_dataset_id(db.engine, args.dataset)
    if not dataset_id:
        print(f"No such dataset: {args.dataset}")
        return 1

    # Unset means: the reports read what reached the export, and the repair
    # reads everything -- all 1,716 Mizzou literals are at `labeled`, outside
    # the export and still wrong.
    statuses = tuple(args.statuses) if args.statuses else None
    with db.get_session() as session:
        if args.kind == "stale":
            if not args.signal:
                print("stale needs --signal (try cross_owner)")
                return 1
            if not args.reason:
                print("stale needs --reason: what changed under the old answer")
                return 1
            names = br.bylines_with_signal(
                session, dataset_id, args.signal, statuses or br.LOCAL_STATUSES
            )
            marked = br.mark_stale(
                session, dataset_id, names, args.reason, dry_run=args.dry_run
            )
            if not args.dry_run:
                session.commit()
            print(f"carrying {args.signal}: {len(names)}")
            print(
                f"decided, sent back to the queue: {marked}"
                f"{' (dry run)' if args.dry_run else ''}"
            )
            # The rest are already in the queue, which is not a failure and
            # not a no-op worth hiding: it is how many the first pass missed.
            print(f"already open: {len(names) - marked}")
            return 0

        if args.kind == "refresh":
            result = br.refresh_candidates(
                session,
                dataset_id,
                statuses or br.LOCAL_STATUSES,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                session.commit()
            print(
                f"candidates: {result['candidates']}"
                f"{' (dry run)' if args.dry_run else ' written'}"
            )
            return 0

        if args.kind == "fix-literals":
            repaired = br.repair_list_literals(
                session, dataset_id, statuses=statuses, dry_run=args.dry_run
            )
            if not args.dry_run:
                session.commit()
            print(
                f"list-literal bylines: {repaired['strings']} strings, "
                f"{repaired['articles']} articles"
                f"{' (dry run)' if args.dry_run else ' rewritten'}"
            )
            for before, after, count in repaired["examples"]:
                print(f"  {before!r} -> {after!r}  ({count})")
            return 0

        rows = br.dataset_rows(session, dataset_id, statuses or br.LOCAL_STATUSES)
        # Who owns whom, so a reporter filing for two mastheads of one company
        # is not asked about. Spelling variants never get this far.
        groups = br.load_owner_groups(session)
        # What a reviewer has already answered. A decided string is counted as
        # the people it names and is not asked about again.
        decisions = br.load_decisions(session, dataset_id)
        per_article = (
            br.article_rows(session, dataset_id, statuses or br.LOCAL_STATUSES)
            if args.kind == "records"
            else []
        )

        if args.kind == "apply":
            # The same call housekeeping makes every night (`apply-byline-
            # decisions`). One implementation, so a decision applied by hand and
            # a decision applied by the schedule are the same write.
            result = br.apply_pending(session, dataset_id, dry_run=args.dry_run)
            if not args.dry_run:
                session.commit()
            print(
                f"decisions: {result['decisions']}  "
                f"articles written: {result['articles']}"
            )
            return 0

    if args.kind == "candidates":
        found = br.candidates(rows, groups, decisions)
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
                # What a reviewer cannot see: "Nick McNeal" beside
                # "Nick Mcneal", or a name beside itself in brackets.
                "differs_by": " | ".join(
                    br.difference_kind(row.raw, variant) for variant in row.variants
                ),
                "hosts": len(row.hosts),
                "host_list": " | ".join(row.hosts),
                "owners": len(row.owners),
                "owner_list": " | ".join(row.owners),
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
            "differs_by",
            "hosts",
            "host_list",
            "owners",
            "owner_list",
        ]
    elif args.kind == "owners":
        out = br.owner_grouping(rows, groups)
        fields = [
            "owner",
            "owner_forms",
            "spellings",
            "hosts",
            "host_list",
            "articles",
            "owner_key",
            "group_key",
            "grouped",
        ]
    elif args.kind == "records":
        out = br.author_records(per_article, decisions)
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
        out = br.bylines_with_hosts(rows, decisions)
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
        out = br.hosts_with_bylines(rows, decisions)
        fields = ["host", "unique_bylines", "articles", "owner"]

    written = _write(out, fields, args.out)
    if args.out:
        print(f"{written} rows -> {args.out}")
    return 0
