"""Plan and apply rework for one dataset: reparse what we have, refetch what we don't.

A thin wrapper. The decision lives in `src/services/rework_disposition.py` so the
Argo step, an API route and this command all ask one question and cannot drift --
`handle_extract_url_command` and `_process_batch` are what that drift looks like.

Dry run by default. `--apply` is required to write anything, because a rework plan
that queues a refetch spends publisher requests, and on a credentialed host a
login.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter

from sqlalchemy import text

from src.services.rework_disposition import (
    HOLD,
    LEAVE,
    REFETCH,
    REPARSE,
    decide,
)

logger = logging.getLogger(__name__)

#: The prose a whole body needs to count as a story. Same constant the extraction
#: gate uses, deliberately: if 150 characters is enough to be an article, it is
#: enough to prove one is present.
MIN_PROSE_CHARS = 150

#: Statuses worth reconsidering. A terminal judgement about the CONTENT, as
#: opposed to `error` (the fetch failed, already retried elsewhere) or `wire`
#: (a provenance finding, and wire is terminal by decision).
REWORKABLE = ("not_article", "paywall")

CANDIDATES_SQL = text("""
    SELECT a.id::text AS article_id,
           a.status,
           a.raw,
           a.title,
           cl.id::text AS link_id,
           cl.url,
           cl.status AS link_status,
           s.host_norm,
           coalesce(s.requires_login, false) AS requires_login,
           s.auth_secret_name IS NOT NULL AS has_credentials,
           a.metadata::json->>'authenticated_session' AS authenticated_session
    FROM articles a
    JOIN datasets d ON d.id = a.dataset_id
    JOIN candidate_links cl ON cl.id = a.candidate_link_id
    LEFT JOIN sources s ON s.id = cl.source_id
    WHERE d.slug = :dataset
      AND a.status = ANY(:statuses)
    """)

#: Reparse rewinds the ARTICLE, not the link. The capture stays; cleaning,
#: labelling and enrichment run again over it. `text` was emptied when the row was
#: condemned -- the furniture branch drops the body and keeps `raw` -- so cleaning
#: is what restores a readable body, and it reads `raw`.
REPARSE_SQL = text("""
    UPDATE articles
       SET status = 'extracted',
           metadata = (
               coalesce(metadata::jsonb, '{}'::jsonb)
               || jsonb_build_object('rework', CAST(:note AS jsonb))
           )::json
     WHERE id = CAST(:article_id AS uuid)
    """)


def add_rework_plan_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "rework-plan",
        help="Decide per row whether rework means reparse or refetch, and apply it",
    )
    parser.add_argument("--dataset", required=True, help="datasets.slug")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes; without it nothing is written",
    )
    parser.add_argument(
        "--only",
        choices=[REPARSE, REFETCH],
        help="apply just one disposition; refetch spends publisher requests",
    )
    parser.add_argument(
        "--by", default="rework-plan", help="who asked, recorded on the row"
    )
    parser.add_argument(
        "--reason",
        default="classifier corrected; row re-judged",
        help="why, recorded on the row",
    )
    parser.add_argument("--limit", type=int, help="stop after this many rows")


def plan(session, dataset: str) -> list[dict]:
    """Every reworkable row in the dataset, with its disposition."""
    rows = session.execute(
        CANDIDATES_SQL, {"dataset": dataset, "statuses": list(REWORKABLE)}
    ).mappings()
    out = []
    for row in rows:
        d = decide(
            status=row["status"],
            raw=row["raw"],
            host=row["host_norm"],
            requires_login=row["requires_login"],
            has_credentials=row["has_credentials"],
            authenticated_session=row["authenticated_session"],
            min_prose_chars=MIN_PROSE_CHARS,
        )
        out.append({**dict(row), "action": d.action, "reason": d.reason})
    return out


def _report(rows: list[dict]) -> None:
    by_action = Counter(r["action"] for r in rows)
    print(f"{len(rows)} reworkable rows")
    for action in (REPARSE, REFETCH, HOLD, LEAVE):
        n = by_action.get(action, 0)
        if not n:
            continue
        print(f"\n  {action.upper()}  {n}")
        for reason, count in Counter(
            r["reason"] for r in rows if r["action"] == action
        ).most_common():
            print(f"      {count:4d}  {reason}")
        hosts = Counter(
            r["host_norm"] or "(no source)" for r in rows if r["action"] == action
        )
        print(f"      hosts: {', '.join(f'{h} ({n})' for h, n in hosts.most_common())}")


def handle_rework_plan_command(args: argparse.Namespace) -> int:
    import json

    from src.models.database import DatabaseManager
    from src.pipeline import refetch as refetch_pipeline

    db = DatabaseManager()
    with db.get_session() as session:
        rows = plan(session, args.dataset)

    if args.limit:
        rows = rows[: args.limit]
    _report(rows)

    if not args.apply:
        print("\n(dry run — pass --apply to write)")
        return 0

    wanted = {args.only} if args.only else {REPARSE, REFETCH}
    note = json.dumps({"by": args.by, "reason": args.reason})

    reparsed = 0
    with db.get_session() as session:
        if REPARSE in wanted:
            for row in (r for r in rows if r["action"] == REPARSE):
                session.execute(
                    REPARSE_SQL, {"article_id": row["article_id"], "note": note}
                )
                reparsed += 1
            session.commit()

    marked = 0
    if REFETCH in wanted:
        # The existing rewind, not a second implementation of one: it records the
        # previous link status on the article so the note survives a `clear`.
        ids = [r["article_id"] for r in rows if r["action"] == REFETCH]
        if ids:
            with db.get_session() as session:
                result = refetch_pipeline.mark(
                    session, ids, by=args.by, reason=args.reason
                )
                # `mark` reports requested/marked/already/missing.
                marked = result.get("marked", 0)
                if result.get("already"):
                    print(f"  already rewound, left alone: {result['already']}")
                if result.get("missing"):
                    print(f"  missing: {result['missing']}")

    print(f"\napplied: {reparsed} reparsed, {marked} rewound for refetch")
    held = sum(1 for r in rows if r["action"] == HOLD)
    if held:
        print(f"held (not queued): {held} — see the reasons above")
    return 0
