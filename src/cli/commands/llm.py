"""CLI command for orchestrating LLM providers across workflow tasks."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from src.models.database import DatabaseManager

from ...services.llm import (
    ArticleLLMPipeline,
    ArticleLLMResult,
    LLMOrchestrator,
    ProviderRegistry,
    VectorStoreFactory,
    load_llm_settings,
)

logger = logging.getLogger(__name__)


def add_llm_parser(subparsers) -> None:
    """Register the ``llm`` subcommand group."""

    parser = subparsers.add_parser(
        "llm",
        help="Run large language model orchestration tasks",
    )

    sub = parser.add_subparsers(
        dest="llm_command",
        help="LLM command suite",
    )

    run_parser = sub.add_parser(
        "run",
        help="Generate summaries for recent articles",
    )
    run_parser.add_argument(
        "--statuses",
        nargs="+",
        help="Filter articles by status (default: cleaned local)",
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of articles to process (default: 20)",
    )
    run_parser.add_argument(
        "--prompt-template",
        help="Optional path to a custom prompt template",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview orchestration without persisting summaries",
    )
    run_parser.add_argument(
        "--show-failures",
        action="store_true",
        help="Print provider failure details even on success",
    )
    run_parser.set_defaults(func=_handle_llm_run)

    status_parser = sub.add_parser(
        "status",
        help="Show configured LLM providers and vector store state",
    )
    status_parser.set_defaults(func=_handle_llm_status)

    parser.set_defaults(func=handle_llm_command)


def handle_llm_command(args) -> int:
    """Dispatch ``llm`` subcommands."""

    if not getattr(args, "llm_command", None):
        print("Please provide an LLM subcommand (run, status)")
        return 1

    return args.func(args)  # type: ignore[misc]


def _handle_llm_status(args) -> int:
    del args  # Unused
    settings = load_llm_settings()

    print("\n=== LLM Provider Configuration ===")
    print("Provider order: " + ", ".join(settings.provider_names()))
    print("OpenAI API key configured? " + ("yes" if settings.openai_api_key else "no"))
    print(
        "Anthropic API key configured? "
        + ("yes" if settings.anthropic_api_key else "no")
    )
    print("Google API key configured? " + ("yes" if settings.google_api_key else "no"))
    if settings.vector_store and settings.vector_store.is_enabled():
        print("Vector store provider: " + settings.vector_store.provider)
    else:
        print("Vector store provider: none configured")

    available = ", ".join(ProviderRegistry.names())
    print("Available registry providers: " + available)
    return 0


def _handle_llm_run(args) -> int:
    settings = load_llm_settings()
    vector_store = VectorStoreFactory.create(settings)
    orchestrator = LLMOrchestrator.from_settings(
        settings,
        vector_store=vector_store,
    )

    statuses = _normalize_statuses(args.statuses)
    prompt_template = ArticleLLMPipeline.load_prompt_template(
        getattr(args, "prompt_template", None)
    )

    db = DatabaseManager()
    try:
        pipeline = ArticleLLMPipeline(
            db.session,
            orchestrator,
            prompt_template=prompt_template,
        )
        results = pipeline.run(
            statuses=statuses,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        _render_run_summary(results, args.dry_run, args.show_failures)
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("LLM run failed: %s", exc)
        return 1
    finally:
        db.close()


def _normalize_statuses(raw: Sequence[str] | None) -> list[str] | None:
    if not raw:
        return ["cleaned", "local"]

    statuses: list[str] = []
    for status in raw:
        if not status:
            continue
        status_norm = status.strip().lower()
        if not status_norm:
            continue
        if status_norm == "all":
            return None
        if status_norm not in statuses:
            statuses.append(status_norm)
    return statuses or None


def _render_run_summary(
    results: Sequence[ArticleLLMResult],
    dry_run: bool,
    show_failures: bool,
) -> None:
    successes = [result for result in results if result.success]
    failures = [result for result in results if not result.success]

    print("\n=== LLM Run Summary ===")
    print(f"Total articles evaluated: {len(results)}")
    print(f"Successful summaries: {len(successes)}")
    print(f"Failures: {len(failures)}")
    if dry_run:
        print("Dry-run enabled: no summaries were persisted.")

    if show_failures and failures:
        print("\n-- Failure Details --")
        for failure in failures:
            failure_messages = ", ".join(
                f"{entry.get('provider')}: {entry.get('reason')}"
                for entry in failure.failures
            )
            print(
                f"Article {failure.article_id} failed across providers: "
                f"{failure_messages}"
            )

    if successes:
        sample = successes[0]
        print("\nSample provider: " + (sample.provider or "unknown"))
        if sample.content:
            snippet = sample.content[:300]
            print(
                "Summary sample:\n" + snippet + ("..." if len(snippet) == 300 else "")
            )
