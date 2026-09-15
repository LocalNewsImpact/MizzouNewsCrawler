"""news-crawler enrich — the backfield enrichment stage CLI.

Subcommands per docs/BACKFIELD_IMPLEMENTATION.md Phase 5:

  enrich run        --dataset SLUG [--since YYYY-MM-DD] [--limit N]
                    [--dry-run] [--concurrency N]
  enrich backfill   --ids-file PATH [--dry-run]
  enrich reground   [--dataset SLUG] [--since D] [--until D] [--dry-run]
  enrich status     [--dataset SLUG]
  enrich reprocess  --dataset SLUG --profile-version N [--dry-run]

--dry-run resolves candidates, prints the plan and projected cost, and makes no
model call and no write. The spend ceiling (ENRICHMENT_SPEND_CEILING_USD) is
checked between articles, never mid-article, so an article is never half-billed.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
    run.add_argument(
        "--since",
        help=(
            "Only articles created on or after this date (YYYY-MM-DD). "
            "The selection is oldest-first, so --limit alone takes the "
            "oldest N of the backlog, not the newest."
        ),
    )
    run.add_argument("--limit", type=int, default=200)
    run.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("ENRICHMENT_CONCURRENCY", "10")),
    )
    run.add_argument("--dry-run", action="store_true")

    backfill = actions.add_parser("backfill", help="Enrich an explicit id list")
    backfill.add_argument(
        "--ids-file", default=None, help="file of article ids, one per line"
    )
    backfill.add_argument(
        "--rework",
        action="store_true",
        default=False,
        help=(
            "Enrich only the articles pipeline_rework says owe it -- the "
            "records a review decision rewound -- and close those rows "
            "when done. Housekeeping uses this and never `enrich run`."
        ),
    )
    backfill.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("ENRICHMENT_CONCURRENCY", "10")),
    )
    backfill.add_argument("--dry-run", action="store_true")

    status = actions.add_parser("status", help="Candidate and outcome counts")
    status.add_argument("--dataset", default=None)

    # Geography a person contributed, into the table BigQuery reads.
    # Separate from every other verb here because it calls no model and
    # spends nothing: it moves rows that already exist.
    manual = actions.add_parser(
        "apply-manual",
        help="Put reviewed geography into article_geoids (and so BigQuery)",
    )
    manual.add_argument("--dataset", default=None)
    manual.add_argument(
        "--since", help="Only articles published on or after this date (YYYY-MM-DD)"
    )
    manual.add_argument("--dry-run", action="store_true")

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

    reground = actions.add_parser(
        "reground",
        help="Remove stored geography the article's own text does not support",
    )
    reground.add_argument("--dataset", help="dataset slug; omit for every dataset")
    reground.add_argument("--since", help="publish_date >= this (YYYY-MM-DD)")
    reground.add_argument("--until", help="publish_date < this (YYYY-MM-DD)")
    reground.add_argument("--limit", type=int, default=None)
    reground.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be removed and write nothing",
    )

    parser.set_defaults(func=handle_enrichment_command)


def _max_attempts() -> int:
    return int(os.getenv("ENRICHMENT_MAX_ATTEMPTS", "3"))


def _ceiling() -> Decimal | None:
    raw = os.getenv("ENRICHMENT_SPEND_CEILING_USD")
    return Decimal(raw) if raw else None


def _backfield_commit() -> str:
    return os.getenv("BACKFIELD_COMMIT", "unknown")


def _process(
    session_factory, articles, profile, model, concurrency, dataset_id=None
) -> dict:
    """Enrich a list of candidates: model calls in parallel threads, writes on
    the caller's thread, one commit per article AS IT FINISHES, ceiling
    between articles.

    AS IT FINISHES IS THE WHOLE POINT, and it used to be `pool.map`.

    `ThreadPoolExecutor.map` yields results in INPUT order. The model calls
    still ran in parallel, but article #2 could not be persisted until #1
    returned, #3 until #2, and so on, so finished work sat unwritten behind
    the slowest article ahead of it. Everything landed in a burst at the
    end, or -- if the run was cut short -- not at all.

    That is not hypothetical. Four housekeeping runs on 2026-09-13 made
    model calls for up to 47 minutes and wrote ZERO enrichment rows between
    them: every one was stopped before the ordered yield reached the head of
    its queue, and every dollar of that spend was discarded. A fifth run on
    2026-09-14 was 13 minutes in, 25 model calls done, still zero rows.

    Waiting on FIRST_COMPLETED instead means an article is durable the
    moment it finishes. A run that is interrupted keeps what it paid for.
    """
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
        submitted = {}
        pending = set()
        for position, article in enumerate(articles):
            future = pool.submit(classify, article)
            submitted[future] = position
            pending.add(future)
        try:
            with session_factory() as session:
                while pending and not halted:
                    finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                    # `wait` hands back a SET, and several articles often
                    # finish inside the same tick. Persist them in the order
                    # they were submitted: an arbitrary order would still be
                    # durable, but it would make the ceiling stop at an
                    # arbitrary subset, so two runs over the same articles
                    # could halt on different ones. Waiting is what we gave
                    # up; determinism is not.
                    for future in sorted(finished, key=submitted.__getitem__):
                        article, outcome = future.result()
                        persist_outcome(
                            session,
                            article,
                            outcome,
                            profile=profile,
                            model=model,
                            backfield_commit=_backfield_commit(),
                            prompt_versions={"content_gate": "content_gate-v1"},
                            dataset_id=dataset_id,
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
        finally:
            # Anything not yet started stops here. A future already running
            # cannot be cancelled and its result is dropped, which is the
            # same bargain the ordered version made -- the difference is
            # that everything finished before this point is already written.
            for future in pending:
                future.cancel()
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
            if action == "reground":
                result = repository.reground_stored(
                    session,
                    dataset=args.dataset,
                    since=args.since,
                    until=args.until,
                    limit=args.limit,
                    dry_run=args.dry_run,
                    on_batch=lambda n, c: logger.info(
                        "regrounded %s articles, %s places dropped so far",
                        n,
                        c["places_dropped"],
                    ),
                )
                print(
                    f"articles read:     {result['articles']}\n"
                    f"articles changed:  {result['articles_changed']}\n"
                    f"places dropped:    {result['places_dropped']}\n"
                    f"counties dropped:  {result['counties_dropped']}\n"
                    f"points cleared:    {result['points_cleared']}\n"
                    f"unverifiable kept: {result['unverifiable']}"
                    + ("\n(dry run — nothing written)" if args.dry_run else "")
                )
                return 0

            if action == "apply-manual":
                from src.enrichment.repository import apply_manual_geography

                result = apply_manual_geography(
                    session,
                    dataset=args.dataset,
                    since=getattr(args, "since", None),
                    dry_run=args.dry_run,
                )
                print(
                    f"contributions: {result['contributions']}  "
                    f"articles: {result['articles']}  "
                    f"written: {result['written']}"
                    + ("  (dry run)" if args.dry_run else "")
                )
                return 0

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
                    session,
                    args.dataset,
                    args.limit,
                    _max_attempts(),
                    since=getattr(args, "since", None),
                )
            elif action == "reprocess":
                # Keyed on status. `--profile-version` no longer selects
                # anything -- raising a profile is not a reason to
                # re-answer questions that were answered -- and it is
                # still checked against the dataset's, because running a
                # reprocess against a profile the dataset does not have
                # would record a version that never enriched anything.
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
                    args.limit,
                    _max_attempts(),
                )
            else:  # backfill
                # THE IDS, FROM THE DATABASE WHEN ASKED.
                #
                # `--rework` reads `pipeline_rework` -- the articles a
                # review decision rewound that still owe enrichment -- so
                # housekeeping never runs `enrich run`, which selects every
                # article at `labeled` and would spend the ceiling on
                # 85,000 records nobody asked about. An empty table means
                # nothing to do, never "everything".
                if getattr(args, "rework", False) is True:
                    ids = repository.articles_owed_enrichment(session)
                    if not ids:
                        print("rework: nothing owes enrichment")
                        return 0
                elif args.ids_file:
                    ids = [
                        line.strip()
                        for line in open(args.ids_file)
                        if line.strip() and not line.startswith("#")
                    ]
                else:
                    raise ConfigurationError(
                        "backfill needs --ids-file or --rework: with neither "
                        "there is nothing to say which articles, and no "
                        "default that is not a sweep"
                    )
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

        # The CLI takes a slug; telemetry keys on the UUID. Resolve once here
        # so every enrichment row this run writes carries the same dataset.
        from src.utils.dataset_utils import resolve_dataset_id

        with db.get_session() as resolving_session:
            dataset_uuid = resolve_dataset_id(
                resolving_session, getattr(args, "dataset", None)
            )
        result = _process(
            db.get_session,
            candidates,
            profile,
            model,
            args.concurrency,
            dataset_id=dataset_uuid,
        )
        # Close the rework rows for articles that reached a terminal
        # status. Judged on the status, not on having been attempted: one
        # whose enrichment failed is still `labeled`, still owes the work,
        # and tomorrow's run should find it.
        if action == "backfill" and getattr(args, "rework", False) is True:
            with db.get_session() as session:
                settled = repository.settle_enrichment_rework(
                    session, [c.id for c in candidates]
                )
            print(f"rework: {settled} rows settled")
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
