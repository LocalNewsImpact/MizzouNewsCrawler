"""Remove enrichment from articles the content gate would now refuse.

The rule and the cleanup are the same code. Every enriched article is
re-judged by the gate's free checks -- `boilerplate_score`, `paywalled_stub`,
`no_story`, in the orchestrator's own order -- and any it would refuse today
has its enrichment removed and its status set to what the gate would have
written. No second list of phrases, no SQL that can drift from the rule.

    scripts/remove_enrichment_the_gate_would_refuse.py            # report only
    scripts/remove_enrichment_the_gate_would_refuse.py --apply    # do it

Scope is `status = 'enriched'` only. Articles already at `enrichment_skipped`
or `not_article` carry a gate verdict and are left alone, so this cannot
re-judge a decision a person made.

CIN labels are NOT touched. A paywall stub keeps its label by rule -- classify
from the text that is there, withhold only the enrichment -- and a body with
no story keeps whatever label it has for the same reason the earlier cleanups
did: the labels on non-local-news are harmless and were left in place
deliberately on 2026-09-13.

Model calls: none. Everything here is the free layer.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import datetime

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.enrichment.gate import (  # noqa: E402
    BOILERPLATE_SKIP_REASON,
    HEURISTIC_REJECT,
    NO_STORY_SKIP_REASON,
    boilerplate_score,
    no_story,
    paywalled_stub,
)
from src.enrichment.orchestrator import PAYWALL_RULE_SKIP_REASON  # noqa: E402

DERIVED = (
    "article_geoids",
    "article_places",
    "article_people",
    "article_organizations",
    "article_enrichment",
)


def verdict(content: str) -> tuple[str, str] | None:
    """(status, skip_reason) the gate would write, or None to keep it.

    Same three checks, same order, as `orchestrator.enrich_article`.
    """
    body = content or ""
    if boilerplate_score(body) >= HEURISTIC_REJECT:
        return ("not_article", BOILERPLATE_SKIP_REASON)
    if paywalled_stub(body) is not None:
        return ("enrichment_skipped", PAYWALL_RULE_SKIP_REASON)
    if no_story(body):
        return ("not_article", NO_STORY_SKIP_REASON)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default=None, help="CSV of what changed / would")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL") or (
        f"host={os.environ.get('PGHOST', '127.0.0.1')} "
        f"port={os.environ.get('PGPORT', '5436')} "
        f"dbname={os.environ.get('PGDATABASE', 'mizzou')} "
        f"user={os.environ.get('PGUSER', 'mizzou_user')} "
        f"password={os.environ['PGPASSWORD']}"
    )
    report_path = args.report or (
        f"enrichment_gate_cleanup_{datetime.now():%Y%m%d_%H%M%S}.csv"
    )

    with psycopg.connect(dsn) as conn:
        conn.execute("SET statement_timeout = '600s'")
        rows = conn.execute(
            "SELECT id, url, content FROM articles WHERE status = 'enriched'"
        ).fetchall()
        print(f"enriched articles judged: {len(rows)}")

        decided = []
        for article_id, url, content in rows:
            found = verdict(content)
            if found:
                decided.append((article_id, url, *found))

        tally = Counter((s, r) for _, _, s, r in decided)
        for (status, reason), n in tally.most_common():
            print(f"  {n:>5}  -> {status}/{reason}")
        print(f"  {len(decided):>5}  total the gate would refuse")

        with open(report_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["article_id", "url", "new_status", "skip_reason"])
            w.writerows(decided)
        print(f"report: {report_path}")

        if not args.apply:
            print("dry run; pass --apply to change anything")
            return 0

        ids = [d[0] for d in decided]
        with conn.transaction():
            for table in DERIVED:
                conn.execute(
                    f"DELETE FROM {table} WHERE article_id = ANY(%s)", (ids,)
                )
            for status, reason in tally:
                batch = [d[0] for d in decided if (d[2], d[3]) == (status, reason)]
                conn.execute(
                    "UPDATE articles SET status = %s, enrichment_attempts = 0 "
                    "WHERE id = ANY(%s)",
                    (status, batch),
                )
        print(f"applied: {len(ids)} articles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
