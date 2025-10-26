#!/usr/bin/env python3
"""Run an end-to-end pipeline for a handful of Missouri counties.

This helper script wraps the news crawler CLI so we can exercise discovery,
verification, and extraction in one shot without touching individual services
manually. It is intended for smoke tests or staging runs rather than
production-scale orchestrations.

Example usage (from the project root)::

    python orchestration/county_pipeline.py --dry-run

Once you're confident, drop ``--dry-run`` to execute the full pipeline.
"""

from __future__ import annotations

import argparse
import logging
import math
import shlex
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from sqlalchemy import text

from src.models.database import DatabaseManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COUNTIES = ("Boone", "Osage", "Audrain")
DEFAULT_CLI_MODULE = "src.cli.cli_modular"
LEGACY_CLI_MODULE = "src.cli.main"
FORCED_VERIFICATION_BATCH_SIZE = 1


class PipelineError(RuntimeError):
    """Raised when a pipeline step fails."""


def _get_candidate_queue_counts() -> dict[str, int]:
    """Return counts of verification/extraction queues.

    This inspects the ``candidate_links`` table and returns the number of
    records currently marked as ``discovered`` (awaiting verification) and
    ``article`` (ready for extraction). We use this to avoid launching a
    verification loop that will busy-wait when there is nothing to process.
    """

    counts = {"discovered": 0, "article": 0}

    with DatabaseManager() as db:
        result = db.session.execute(
            text(
                "SELECT status, COUNT(*) AS total "
                "FROM candidate_links "
                "WHERE status IN ('discovered', 'article') "
                "GROUP BY status"
            )
        )
        for row in result:
            status = row._mapping["status"]
            total = row._mapping["total"]
            counts[status] = total

    return counts


def _run_cli_step(
    label: str,
    cli_args: Sequence[str],
    *,
    cli_base: Sequence[str],
    dry_run: bool,
    env: dict[str, str] | None = None,
) -> None:
    """Execute a CLI command, raising :class:`PipelineError` on failure."""

    cmd = [*cli_base, *cli_args]
    command_str = " ".join(shlex.quote(part) for part in cmd)
    logging.info("➡️  %s", label)
    logging.debug("Command: %s", command_str)

    if dry_run:
        logging.info("(dry-run) Skipping execution: %s", command_str)
        return

    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    )

    if result.returncode != 0:
        raise PipelineError(
            f"Step '{label}' failed with exit code {result.returncode}."
        )


def _add_optional(
    arg_list: list[str],
    flag: str,
    value: str | int | None,
) -> None:
    if value is None:
        return
    arg_list.extend([flag, str(value)])


def orchestrate_pipeline(
    counties: Iterable[str],
    *,
    dataset: str | None,
    source_limit: int | None,
    max_articles: int,
    days_back: int,
    force_all: bool,
    verification_batch_size: int,
    verification_batches: int | None,
    verification_sleep: int,
    skip_verification: bool,
    extraction_limit: int,
    extraction_batches: int,
    skip_extraction: bool,
    dry_run: bool,
    cli_module: str,
    skip_analysis: bool,
    analysis_limit: int | None,
    analysis_batch_size: int,
    analysis_top_k: int,
    analysis_label_version: str | None,
    analysis_statuses: list[str] | None,
    analysis_dry_run: bool,
) -> None:
    """Run discovery, verification, and extraction for the counties."""

    logging.info("Project root: %s", PROJECT_ROOT)
    cli_base = [sys.executable, "-m", cli_module]

    for county in counties:
        discover_args: list[str] = [
            "discover-urls",
            "--county",
            county,
            "--max-articles",
            str(max_articles),
            "--days-back",
            str(days_back),
        ]
        if force_all:
            discover_args.append("--force-all")
        _add_optional(discover_args, "--source-limit", source_limit)
        if dataset:
            discover_args.extend(["--dataset", dataset])

        label = f"Discovery for county {county}"
        _run_cli_step(
            label,
            discover_args,
            cli_base=cli_base,
            dry_run=dry_run,
        )

    queue_counts = _get_candidate_queue_counts()
    discovered_pending = queue_counts["discovered"]
    extraction_ready = queue_counts["article"]

    run_verification = not skip_verification and discovered_pending > 0

    forced_batch_size = FORCED_VERIFICATION_BATCH_SIZE
    if verification_batch_size != forced_batch_size:
        logging.warning(
            (
                "Overriding verification batch size from %s to %s to ensure "
                "sequential processing."
            ),
            verification_batch_size,
            forced_batch_size,
        )
    verification_batch_size = forced_batch_size

    if run_verification:
        batches_needed = math.ceil(discovered_pending / verification_batch_size)

        if verification_batches is None:
            verification_batches = batches_needed
            logging.info(
                "Configuring verification to process up to %s batch(es) "
                "based on %s discovered link(s).",
                verification_batches,
                discovered_pending,
            )
        else:
            logging.info(
                "Using user-supplied verification batch limit: %s",
                verification_batches,
            )

        verify_args: list[str] = [
            "verify-urls",
            "--batch-size",
            str(verification_batch_size),
            "--sleep-interval",
            str(verification_sleep),
        ]
        if verification_batches is not None:
            verify_args.extend(["--max-batches", str(verification_batches)])

        _run_cli_step(
            "Verification service",
            verify_args,
            cli_base=cli_base,
            dry_run=dry_run,
        )
        if not dry_run:
            # Refresh counts now that verification has had a chance to run.
            queue_counts = _get_candidate_queue_counts()
            extraction_ready = queue_counts["article"]
    elif not skip_verification:
        logging.info(
            "No candidate links with status 'discovered'; skipping verification"
        )
    else:
        logging.info("Skipping verification step per user request")

    if not skip_extraction:
        extract_args = [
            "extract",
            "--limit",
            str(extraction_limit),
            "--batches",
            str(extraction_batches),
        ]

        if extraction_ready == 0:
            logging.info(
                "No candidate links with status 'article'; skipping extraction"
            )
        else:
            _run_cli_step(
                "Article extraction",
                extract_args,
                cli_base=cli_base,
                dry_run=dry_run,
            )
    else:
        logging.info("Skipping extraction step per user request")

    if not skip_analysis:
        analyze_args: list[str] = [
            "analyze",
        ]
        _add_optional(analyze_args, "--limit", analysis_limit)
        _add_optional(
            analyze_args,
            "--batch-size",
            analysis_batch_size,
        )
        _add_optional(analyze_args, "--top-k", analysis_top_k)
        if analysis_label_version:
            analyze_args.extend(["--label-version", analysis_label_version])
        if analysis_statuses:
            analyze_args.append("--statuses")
            analyze_args.extend(analysis_statuses)
        if analysis_dry_run:
            analyze_args.append("--dry-run")

        _run_cli_step(
            "ML analysis",
            analyze_args,
            cli_base=cli_base,
            dry_run=dry_run,
        )
    else:
        logging.info("Skipping analysis step per user request")

    logging.info("✅ Pipeline finished%s.", " (dry run)" if dry_run else "")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Orchestrate the discovery → verification → extraction pipeline"),
    )
    parser.add_argument(
        "--counties",
        nargs="+",
        default=list(DEFAULT_COUNTIES),
        help="Counties to target (default: Boone, Osage, Audrain)",
    )
    parser.add_argument(
        "--dataset",
        help="Optional dataset label to tag discovery telemetry",
    )
    parser.add_argument(
        "--source-limit",
        type=int,
        help="Limit the number of sources discovered per county",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=40,
        help="Maximum discovered articles per source (default: 40)",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="How many days back discovery should look (default: 7)",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Ignore scheduling and force discovery for matching sources",
    )
    parser.add_argument(
        "--verification-batch-size",
        type=int,
        default=FORCED_VERIFICATION_BATCH_SIZE,
        help=(
            "Deprecated: verification runs sequentially with batch size 1; "
            "this flag is ignored"
        ),
    )
    parser.add_argument(
        "--verification-batches",
        type=int,
        help=("Cap the number of verification batches (default: run until idle)"),
    )
    parser.add_argument(
        "--verification-sleep",
        type=int,
        default=5,
        help="Seconds to sleep when verification finds no work (default: 5)",
    )
    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip the verification step",
    )
    parser.add_argument(
        "--extraction-limit",
        type=int,
        default=10,
        help="Articles to extract per batch (default: 10)",
    )
    parser.add_argument(
        "--extraction-batches",
        type=int,
        default=3,
        help="Number of extraction batches to run (default: 3)",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip the extraction step",
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Skip the machine-learning analysis step",
    )
    parser.add_argument(
        "--analysis-limit",
        type=int,
        help="Maximum number of articles to classify",
    )
    parser.add_argument(
        "--analysis-batch-size",
        type=int,
        default=16,
        help="Articles per classification batch (default: 16)",
    )
    parser.add_argument(
        "--analysis-top-k",
        type=int,
        default=2,
        help="Predictions to keep per article (default: 2)",
    )
    parser.add_argument(
        "--analysis-label-version",
        default="default",
        help="Label version slug for stored predictions",
    )
    parser.add_argument(
        "--analysis-statuses",
        nargs="+",
        help="Override eligible article statuses for analysis",
    )
    parser.add_argument(
        "--analysis-dry-run",
        action="store_true",
        help="Run analysis without writing classifications",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands without executing them",
    )
    parser.add_argument(
        "--cli-module",
        default=DEFAULT_CLI_MODULE,
        help=(
            f"Python module to execute for CLI commands (default: {DEFAULT_CLI_MODULE})"
        ),
    )
    parser.add_argument(
        "--legacy-cli",
        action="store_true",
        help="Use the legacy src.cli.main entry point",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    cli_module = LEGACY_CLI_MODULE if args.legacy_cli else args.cli_module

    try:
        orchestrate_pipeline(
            counties=args.counties,
            dataset=args.dataset,
            source_limit=args.source_limit,
            max_articles=args.max_articles,
            days_back=args.days_back,
            force_all=args.force_all,
            verification_batch_size=args.verification_batch_size,
            verification_batches=args.verification_batches,
            verification_sleep=args.verification_sleep,
            skip_verification=args.skip_verification,
            extraction_limit=args.extraction_limit,
            extraction_batches=args.extraction_batches,
            skip_extraction=args.skip_extraction,
            dry_run=args.dry_run,
            cli_module=cli_module,
            skip_analysis=args.skip_analysis,
            analysis_limit=args.analysis_limit,
            analysis_batch_size=args.analysis_batch_size,
            analysis_top_k=args.analysis_top_k,
            analysis_label_version=args.analysis_label_version,
            analysis_statuses=args.analysis_statuses,
            analysis_dry_run=args.analysis_dry_run,
        )
    except PipelineError as exc:
        logging.error("Pipeline aborted: %s", exc)
        return 1
    except KeyboardInterrupt:
        logging.warning("Pipeline interrupted by user")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
