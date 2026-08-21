"""news-crawler enrich — the backfield enrichment stage CLI.

Subcommands per docs/BACKFIELD_IMPLEMENTATION.md Phase 5:

  enrich run        --dataset SLUG [--limit N] [--dry-run] [--concurrency N]
  enrich backfill   --ids-file PATH [--dry-run]
  enrich status     [--dataset SLUG]
  enrich reprocess  --dataset SLUG --profile-version N [--dry-run]

--dry-run resolves candidates, prints the plan and projected cost, and makes no
model call and no write. The spend ceiling (ENRICHMENT_SPEND_CEILING_USD) is
checked between articles, never mid-article, so an article is never half-billed.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

logger = logging.getLogger(__name__)

# Measured in Phase 0/3; used only for --dry-run projection.
PROJECTED_COST_PER_ARTICLE = Decimal("0.0075")

DEFAULT_MODEL = "openrouter/deepseek/deepseek-v3.2"


def add_enrichment_parser(subparsers):
    parser = subparsers.add_parser(
        "enrich",
        help="Backfield enrichment: the final stage before BigQuery export",
    )
    actions = parser.add_subparsers(dest="enrich_action", required=True)

    run = actions.add_parser("run", help="Enrich candidates for one dataset")
    run.add_argument("--dataset", required=True)
    run.add_argument("--limit", type=int, default=200)
    run.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("ENRICHMENT_CONCURRENCY", "10")),
    )
    run.add_argument("--dry-run", action="store_true")

    backfill = actions.add_parser("backfill", help="Enrich an explicit id list")
    backfill.add_argument(
        "--ids-file", required=True, help="file of article ids, one per line"
    )
    backfill.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("ENRICHMENT_CONCURRENCY", "10")),
    )
    backfill.add_argument("--dry-run", action="store_true")

    status = actions.add_parser("status", help="Candidate and outcome counts")
    status.add_argument("--dataset", default=None)

    reprocess = actions.add_parser(
        "reprocess", help="Re-enrich under a newer profile version"
    )
    reprocess.add_argument("--dataset", required=True)
    reprocess.add_argument("--profile-version", type=int, required=True)
    reprocess.add_argument("--limit", type=int, default=200)
    reprocess.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("ENRICHMENT_CONCURRENCY", "10")),
    )
    reprocess.add_argument("--dry-run", action="store_true")

    parser.set_defaults(func=handle_enrichment_command)


def _max_attempts() -> int:
    return int(os.getenv("ENRICHMENT_MAX_ATTEMPTS", "3"))


def _ceiling() -> Decimal | None:
    raw = os.getenv("ENRICHMENT_SPEND_CEILING_USD")
    return Decimal(raw) if raw else None


def _backfield_commit() -> str:
    return os.getenv("BACKFIELD_COMMIT", "unknown")


def _process(session_factory, articles, profile, model, concurrency) -> dict:
    """Enrich a list of candidates: model calls in parallel threads, writes on
    the caller's thread, one commit per article, ceiling between articles."""
    from src.enrichment.orchestrator import enrich_article
    from src.enrichment.repository import persist_outcome

    ceiling = _ceiling()
    spent = Decimal("0")
    counts: dict[str, int] = {}
    halted = False

    def classify(article):
        return article, enrich_article(
            article, profile, model=model, max_attempts=_max_attempts()
        )

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        iterator = pool.map(classify, articles)
        with session_factory() as session:
            for article, outcome in iterator:
                persist_outcome(
                    session,
                    article,
                    outcome,
                    profile=profile,
                    model=model,
                    backfield_commit=_backfield_commit(),
                    prompt_versions={"content_gate": "content_gate-v1"},
                )
                counts[outcome.status] = counts.get(outcome.status, 0) + 1
                spent += outcome.total_cost_usd
                if ceiling is not None and spent >= ceiling:
                    logger.error(
                        "spend ceiling reached: $%s >= $%s — halting; "
                        "committed work is kept",
                        spent,
                        ceiling,
                    )
                    halted = True
                    break
    return {"counts": counts, "spent": str(spent), "halted": halted}


def handle_enrichment_command(args) -> int:
    from src.enrichment import repository
    from src.enrichment.profiles import ConfigurationError, configured_steps
    from src.models.database import DatabaseManager

    db = DatabaseManager()
    model = os.getenv("ENRICHMENT_MODEL", DEFAULT_MODEL)
    action = args.enrich_action

    try:
        with db.get_session() as session:
            if action == "status":
                where = "AND d.slug = :slug" if args.dataset else ""
                rows = session.execute(
                    __import__("sqlalchemy").text(f"""
                        SELECT a.status, count(*) FROM articles a
                        JOIN candidate_links cl ON cl.id = a.candidate_link_id
                        JOIN dataset_sources ds ON ds.source_id = cl.source_id
                        JOIN datasets d ON d.id = ds.dataset_id
                        WHERE a.status IN ('labeled','enriched','enrichment_skipped',
                                           'not_article','paywall') {where}
                        GROUP BY 1 ORDER BY 2 DESC"""),
                    {"slug": args.dataset} if args.dataset else {},
                ).fetchall()
                for status, count in rows:
                    print(f"  {status:22s} {count}")
                return 0

            if action == "run":
                profile = repository.dataset_profile(session, args.dataset)
                candidates = repository.select_candidates(
                    session, args.dataset, args.limit, _max_attempts()
                )
            elif action == "reprocess":
                profile = repository.dataset_profile(session, args.dataset)
                if profile.version < args.profile_version:
                    raise ConfigurationError(
                        f"dataset profile is v{profile.version}; "
                        f"--profile-version {args.profile_version} is newer — "
                        "update the dataset profile first"
                    )
                candidates = repository.select_reprocess_candidates(
                    session,
                    args.dataset,
                    args.profile_version,
                    args.limit,
                    _max_attempts(),
                )
            else:  # backfill
                ids = [
                    line.strip()
                    for line in open(args.ids_file)
                    if line.strip() and not line.startswith("#")
                ]
                report = repository.select_by_ids(session, ids, _max_attempts())
                print(
                    f"supplied: {len(ids)}  candidates: {len(report.candidates)}  "
                    f"rejected: {len(report.rejected)}"
                )
                for article_id, reason in sorted(report.rejected.items()):
                    print(f"  skip {article_id}: {reason}")
                candidates = report.candidates
                if candidates:
                    profile = repository.dataset_profile(
                        session, candidates[0].dataset_slug
                    )
                else:
                    print("nothing to do")
                    return 0

        if args.dry_run:
            steps = configured_steps(profile)
            projected = PROJECTED_COST_PER_ARTICLE * len(candidates)
            print(f"dry run: {len(candidates)} candidate(s)")
            print(
                f"  profile v{profile.version}, steps: {', '.join(steps) or '(none)'}"
            )
            print(
                f"  projected cost: ~${projected} at ${PROJECTED_COST_PER_ARTICLE}/article"
            )
            print("  no model call made, nothing written")
            return 0

        result = _process(db.get_session, candidates, profile, model, args.concurrency)
        print(
            f"processed: {sum(result['counts'].values())}  "
            f"spent: ${result['spent']}  halted: {result['halted']}"
        )
        for status, count in sorted(result["counts"].items()):
            print(f"  {status:22s} {count}")
        return 1 if result["halted"] else 0

    except ConfigurationError as exc:
        # §5.3: configuration errors fail the run at startup; no article is
        # touched and no attempt is burned.
        logger.error("configuration error: %s", exc)
        print(f"configuration error: {exc}")
        return 2
