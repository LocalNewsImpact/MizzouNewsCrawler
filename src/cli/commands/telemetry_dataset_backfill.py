"""Recover the dataset on telemetry rows written before the column existed.

Every telemetry table now records the dataset the run was for. The rows
already in them do not, and for most of them the answer is still
recoverable: the dataset lives on `candidate_links`, and each telemetry
table reaches a candidate link by some path.

The paths are not equally sound, and the difference decides what this
command will write.

Four tables reach a link by foreign key -- `url_verifications` and
`byline_cleaning_telemetry` hold `candidate_link_id` directly,
`article_enrichment` and `content_type_detection_telemetry` reach one
through `articles`. Those joins are exact.

`extraction_telemetry_v2` holds no id, only `url`, so it joins on the URL
text. That is exact only where a URL belongs to one dataset. Where the
same URL was discovered under two, the row is left null: a null says the
dataset is unknown, and a guess says something false about which corpus
the work belongs to. `verification_telemetry`, `verification_jobs` and
`jobs` are per-run rather than per-record and have no link to recover,
so they are not touched here.

Batched by primary key, because 378k updates in one statement is a lock
held long enough to matter on a live database.
"""

import argparse
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Each table, the statement that recovers its dataset, and the column the
# batches walk. `unambiguous` marks the URL join, which is the only one
# that can find more than one answer for a row.
BACKFILL_SOURCES: dict[str, dict[str, str]] = {
    "url_verifications": {
        "key": "id",
        "join": """
            FROM candidate_links cl
            WHERE cl.id = {t}.candidate_link_id
              AND cl.dataset_id = :dataset
        """,
    },
    "byline_cleaning_telemetry": {
        "key": "id",
        "join": """
            FROM candidate_links cl
            WHERE cl.id = {t}.candidate_link_id
              AND cl.dataset_id = :dataset
        """,
    },
    "article_enrichment": {
        "key": "article_id",
        "join": """
            FROM articles a
            JOIN candidate_links cl ON cl.id = a.candidate_link_id
            WHERE a.id = {t}.article_id
              AND cl.dataset_id = :dataset
        """,
    },
    "content_type_detection_telemetry": {
        "key": "id",
        "join": """
            FROM articles a
            JOIN candidate_links cl ON cl.id = a.candidate_link_id
            WHERE a.id = {t}.article_id
              AND cl.dataset_id = :dataset
        """,
    },
    "extraction_telemetry_v2": {
        "key": "id",
        # Three paths, in order of how directly each names the record.
        #
        # `candidate_link_id` is the candidate UUID and is exact, but it is
        # only present on rows written after it was added; every historical
        # row is null there, which is what the two paths below are for.
        #
        # `article_id` is populated on every row but resolves only where the
        # article still exists, and for most of these rows it never did:
        # the source was paused, or the URL was filtered as wire, weather or
        # obituary. Those are decisions that worked, not failures -- of the
        # Mizzou 2026 rows with no article, paused sources and correct
        # filtering account for the bulk and 404s for 2,712. The URL reaches
        # the candidate link either way, which is why it carries almost all
        # of the table (193,835 of 193,862; the article path adds 17).
        #
        # The "no other dataset claims this URL" test is a NOT EXISTS
        # rather than `count(DISTINCT ...) = 1`. Same answer; the count had
        # to read every candidate link sharing the URL before it could
        # compare, which on 193k rows exceeded the two-minute
        # statement_timeout and aborted the first production run. NOT
        # EXISTS stops at the first row that disagrees.
        #
        # The URL is a fallback rather than the primary because a URL may
        # legitimately be discovered under several datasets -- that is two
        # discoveries, not an ambiguity -- and then the URL alone cannot
        # say which dataset's job did the extraction. The article FK can,
        # so it wins wherever it resolves, and the URL is used only where
        # no article row exists and the URL belongs to one dataset.
        "join": """
            FROM candidate_links cl
            WHERE cl.dataset_id = :dataset
              AND (
                    cl.id = {t}.candidate_link_id
                 OR cl.id = (
                        SELECT a.candidate_link_id FROM articles a
                         WHERE a.id = {t}.article_id
                    )
                 OR (
                        {t}.candidate_link_id IS NULL
                        AND NOT EXISTS (
                            SELECT 1 FROM articles a2 WHERE a2.id = {t}.article_id
                        )
                        AND cl.url = {t}.url
                        AND NOT EXISTS (
                            SELECT 1 FROM candidate_links c2
                             WHERE c2.url = {t}.url
                               AND c2.dataset_id IS NOT NULL
                               AND c2.dataset_id <> cl.dataset_id
                        )
                    )
              )
        """,
    },
}

# The column each table dates its rows by, for --since/--until.
DATE_COLUMN = {
    "url_verifications": "created_at",
    "byline_cleaning_telemetry": "created_at",
    "article_enrichment": "enriched_at",
    "content_type_detection_telemetry": "created_at",
    "extraction_telemetry_v2": "created_at",
}


def add_telemetry_dataset_backfill_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "backfill-telemetry-dataset",
        help="Recover dataset_id on telemetry rows written before the column",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Dataset name, slug or UUID. Resolved to the UUID before use.",
    )
    parser.add_argument(
        "--since",
        help="Only rows dated on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        help="Only rows dated before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--table",
        action="append",
        choices=sorted(BACKFILL_SOURCES),
        help="Restrict to one table; repeatable. Default: every table.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows per statement (default: 5000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what each table would fill and write nothing",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.set_defaults(func=handle_telemetry_dataset_backfill_command)
    return parser


def _date_clause(table: str, since: str | None, until: str | None) -> tuple[str, dict]:
    """The date filter, mentioning each parameter only when it has a value.

    A bare parameter compared to NULL cannot be typed by pg8000 and fails
    42P18 before the statement runs -- the fault that kept /work/request
    answering 500. Appending the clause avoids the construct entirely.
    """
    column = DATE_COLUMN[table]
    clause = ""
    params: dict[str, str] = {}
    if since:
        clause += " AND {t}." + column + " >= CAST(:since AS date)"
        params["since"] = since
    if until:
        clause += " AND {t}." + column + " < CAST(:until AS date)"
        params["until"] = until
    return clause, params


def _count_pending(session, table: str, dataset: str, date_clause, date_params) -> int:
    source = BACKFILL_SOURCES[table]
    sql = f"""
        SELECT count(*) FROM {table} t
         WHERE t.dataset_id IS NULL
           AND EXISTS (SELECT 1 {source["join"].format(t="t")}){date_clause.format(t="t")}
    """
    return session.execute(text(sql), {"dataset": dataset, **date_params}).scalar() or 0


def _fill(session, table: str, dataset: str, date_clause, date_params, batch_size):
    """Fill one table in batches, returning how many rows were written."""
    source = BACKFILL_SOURCES[table]
    key = source["key"]
    written = 0

    sql = text(f"""
        UPDATE {table} t
           SET dataset_id = :dataset
         WHERE t.{key} IN (
               SELECT t2.{key} FROM {table} t2
                WHERE t2.dataset_id IS NULL
                  AND EXISTS (
                      SELECT 1 {source["join"].format(t="t2")}
                  )
                  {date_clause.format(t="t2")}
                LIMIT :batch
         )
        """)

    # A batch is a bigger statement than the two-minute default allows on
    # a table this size. Raised for this session only.
    session.execute(text("SET statement_timeout='900s'"))

    while True:
        result = session.execute(
            sql, {"dataset": dataset, "batch": batch_size, **date_params}
        )
        session.commit()
        if not result.rowcount:
            break
        written += result.rowcount
        logger.info("  %s: %s rows filled so far", table, f"{written:,}")

    return written


def handle_telemetry_dataset_backfill_command(args) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level))

    from src.models.database import DatabaseManager
    from src.utils.dataset_utils import resolve_dataset_id

    db = DatabaseManager()
    with db.get_session() as session:
        dataset = resolve_dataset_id(session, args.dataset)

    if not dataset:
        print(f"❌ Could not resolve dataset: {args.dataset}")
        return 1

    tables = args.table or sorted(BACKFILL_SOURCES)
    print(f"Dataset {args.dataset} -> {dataset}")
    if args.since or args.until:
        print(f"  window: {args.since or 'start'} .. {args.until or 'now'}")

    totals = {}
    with db.get_session() as session:
        for table in tables:
            date_clause, date_params = _date_clause(table, args.since, args.until)

            # Counted only for a dry run. The count is the same scan as the
            # work, so running it first doubled a real backfill -- and on
            # extraction_telemetry_v2 the count alone exceeded the
            # two-minute statement_timeout and killed the run before a
            # single row was written. What a real run reports is what it
            # wrote, which is the more truthful number anyway.
            if args.dry_run:
                pending = _count_pending(
                    session, table, dataset, date_clause, date_params
                )
                print(f"  {table:36s} would fill {pending:>9,}")
                totals[table] = pending
                continue

            print(f"  {table:36s} filling ...")
            totals[table] = _fill(
                session, table, dataset, date_clause, date_params, args.batch_size
            )
            print(f"  {table:36s} filled  {totals[table]:>9,}")

    print(f"\ntotal: {sum(totals.values()):,}")
    return 0
