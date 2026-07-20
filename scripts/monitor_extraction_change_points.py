#!/usr/bin/env python3
"""Report the observable change points for the Selenium / entity-extraction work.

Run it BEFORE deploying and again after, over comparable windows, so the next
round of fixes is aimed by measurement rather than inference. Every number here
corresponds to something a change in this branch should move — or must NOT move.

    python scripts/monitor_extraction_change_points.py --since '2026-07-20 12:00'
    python scripts/monitor_extraction_change_points.py --since '2026-07-21 09:00' --hosts

What each section is watching:

  selenium duration   Should fall sharply. page_source used to block until the
                      page load settled (~208s measured); the stop now runs
                      first. This is the headline claim and the one that was
                      never proven inside the pipeline.

  methods attempted   Should NOT change much. The fixes make Selenium cheaper,
                      not rarer. A big shift means something unintended.

  field completeness  MUST NOT regress. The safety metric — cheaper extraction
                      that loses fields is not a win. Compare per field.

  challenge leakage   THE RISK. Treating a reCAPTCHA as non-blocking when the
                      page still carries prose could, if the content probe is
                      wrong, let a real challenge page through as an article.
                      Watch for short articles carrying challenge language.

  entity backlog      Should drain to ~0 and stay there. If it climbs, the
                      partial index is not being used or the stamp is not being
                      written.

  archive coverage    Share of new articles with raw_gcs_path. Feeds the
                      same-input extractor A/B; a drop means archiving broke.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict

from sqlalchemy import text

from src.models.database import DatabaseManager

CHALLENGE_MARKERS = (
    "enable javascript",
    "checking your browser",
    "verify you are human",
    "just a moment",
    "attention required",
    "access denied",
)


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.1%})" if d else f"{n}/0"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--since", required=True, help="window start, e.g. '2026-07-21 09:00'"
    )
    ap.add_argument("--until", default=None, help="window end (default: now)")
    ap.add_argument(
        "--hosts", action="store_true", help="break Selenium timing out by host"
    )
    args = ap.parse_args()

    params = {"since": args.since, "until": args.until or "2999-01-01"}
    eng = DatabaseManager().engine

    with eng.connect() as conn:
        conn.execute(text("SET statement_timeout='300s'"))

        rows = conn.execute(
            text("""
                SELECT host, method_timings, methods_attempted, extracted_fields
                FROM extraction_telemetry_v2
                WHERE created_at >= :since AND created_at < :until
                  AND method_timings IS NOT NULL
            """),
            params,
        ).all()

        per_method: dict[str, list[float]] = defaultdict(list)
        per_host: dict[str, list[float]] = defaultdict(list)
        n_methods: Counter = Counter()
        have: Counter = Counter()
        total = 0

        for host, mt, ma, ef in rows:
            t = json.loads(mt) if isinstance(mt, str) else (mt or {})
            m = json.loads(ma) if isinstance(ma, str) else (ma or [])
            d = json.loads(ef) if isinstance(ef, str) else (ef or {})
            total += 1
            n_methods[len(m)] += 1
            for k, v in t.items():
                if isinstance(v, (int, float)):
                    per_method[k].append(v)
                    if k == "selenium" and host:
                        per_host[host].append(v)
            if isinstance(d, dict):
                for f in ("title", "author", "content", "publish_date"):
                    v = d.get(f)
                    if v not in (None, "", [], {}) and v is not False:
                        have[f] += 1

        print(f"window: {args.since} .. {args.until or 'now'}   extractions: {total}")

        print("\n-- per-method duration (median / p90) --")
        for k in sorted(per_method):
            v = sorted(per_method[k])
            p90 = v[max(int(len(v) * 0.9) - 1, 0)]
            print(
                f"  {k:16s} n={len(v):5d}  median={statistics.median(v) / 1000:8.1f}s"
                f"  p90={p90 / 1000:8.1f}s"
            )

        print("\n-- methods attempted per extraction (should stay stable) --")
        print("  ", dict(sorted(n_methods.items())))

        print("\n-- field completeness (MUST NOT regress) --")
        for f in ("title", "author", "content", "publish_date"):
            print(f"  {f:14s} {_pct(have[f], total)}")

        if args.hosts and per_host:
            print("\n-- selenium median by host --")
            for h in sorted(per_host, key=lambda x: -statistics.median(per_host[x]))[
                :12
            ]:
                v = per_host[h]
                print(
                    f"  {str(h)[:34]:34s} n={len(v):3d}  {statistics.median(v) / 1000:7.1f}s"
                )

        print("\n-- challenge leakage (THE RISK: real walls read as widgets) --")
        marker_sql = " OR ".join(
            f"lower(a.text) LIKE '%%{m}%%'" for m in CHALLENGE_MARKERS
        )
        leaked = conn.execute(
            text(f"""
                SELECT COUNT(*) FROM articles a
                WHERE a.created_at >= :since AND a.created_at < :until
                  AND length(a.text) < 1200 AND ({marker_sql})
            """),
            params,
        ).scalar()
        new_articles = conn.execute(
            text(
                "SELECT COUNT(*) FROM articles WHERE created_at >= :since "
                "AND created_at < :until"
            ),
            params,
        ).scalar()
        print(
            f"  short articles carrying challenge language: {_pct(leaked or 0, new_articles or 0)}"
        )
        print(
            "  (baseline should be ~0; any rise means the content probe is too permissive)"
        )

        print("\n-- entity backlog (should drain and stay near zero) --")
        pending = conn.execute(text("""
                SELECT COUNT(*) FROM articles a
                WHERE a.content IS NOT NULL AND a.text IS NOT NULL
                  AND a.status NOT IN ('error','paywall','wire')
                  AND NOT EXISTS (
                      SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id
                  )
            """)).scalar()
        print(f"  pending entity extraction: {pending:,}")

        print("\n-- archive coverage (feeds same-input extractor A/B) --")
        archived = conn.execute(
            text(
                "SELECT COUNT(*) FROM articles WHERE created_at >= :since "
                "AND created_at < :until AND raw_gcs_path IS NOT NULL"
            ),
            params,
        ).scalar()
        print(
            f"  new articles with raw_gcs_path: {_pct(archived or 0, new_articles or 0)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
