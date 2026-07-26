"""Re-verify already-classified candidate links against current rules.

The verification service only ever screens status='discovered' links, so
rows that reached 'article' long ago -- or were manually unpaused straight
back to 'article' -- keep whatever classification the rules of that era
gave them. Junk approved under old rules then flows to extraction, wasting
fetches and burning per-domain reputation (rate-limit backoffs on 502s,
etc.).

This command closes that gap two ways:

  reverify-candidates                     # re-screen the 'article' backlog
  reverify-candidates --release-paused    # paused -> discovered, so the
                                          # normal verification loop
                                          # re-screens them (the sanctioned
                                          # unpause path)

Verification here is pattern rules + StorySniffer only (no HTTP prechecks,
no proxy traffic), so re-screening tens of thousands of rows is cheap.
"""

import argparse
import logging

from src.services.url_verification import URLVerificationService

logger = logging.getLogger(__name__)


def add_reverify_candidates_parser(subparsers) -> argparse.ArgumentParser:
    """Add reverify-candidates command parser to subparsers."""
    parser = subparsers.add_parser(
        "reverify-candidates",
        help="Re-run current verification over already-classified backlog",
    )

    parser.add_argument(
        "--status",
        default="article",
        help="Candidate status to re-verify (default: article)",
    )
    parser.add_argument(
        "--release-paused",
        action="store_true",
        help=(
            "Instead of re-verifying in place, move paused links back to "
            "'discovered' so the normal verification loop re-screens them"
        ),
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        help="Only touch candidates created more than this many days ago",
    )
    parser.add_argument(
        "--host",
        help="Only touch candidates from this source host",
    )
    parser.add_argument(
        "--dataset-id",
        help="Only touch candidates belonging to this dataset id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of candidates to process",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Progress-log interval while re-verifying (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without updating any rows",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    parser.set_defaults(func=handle_reverify_candidates_command)
    return parser


def handle_reverify_candidates_command(args) -> int:
    """Handle the reverify-candidates command."""
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        service = URLVerificationService()

        if args.release_paused:
            count = service.release_paused(
                older_than_days=args.older_than_days,
                host=args.host,
                dataset_id=args.dataset_id,
                dry_run=args.dry_run,
            )
            verb = "Would release" if args.dry_run else "Released"
            print(f"✅ {verb} {count} paused candidates back to 'discovered'")
            return 0

        candidates = service.get_reverify_candidates(
            status=args.status,
            older_than_days=args.older_than_days,
            host=args.host,
            dataset_id=args.dataset_id,
            limit=args.limit,
        )
        if not candidates:
            print(f"No '{args.status}' candidates matched the filters")
            return 0

        mode = " (dry run)" if args.dry_run else ""
        print(
            f"🔎 Re-verifying {len(candidates)} '{args.status}' " f"candidates{mode}..."
        )
        metrics = service.reverify_candidates(
            candidates,
            dry_run=args.dry_run,
            progress_every=args.batch_size,
        )

        reclassified_total = sum(metrics["reclassified"].values())
        print(f"✅ Processed {metrics['total']} candidates:")
        print(f"   kept as '{args.status}': {metrics['kept']}")
        print(f"   reclassified: {reclassified_total}")
        for status, count in sorted(
            metrics["reclassified"].items(), key=lambda kv: -kv[1]
        ):
            print(f"     -> {status}: {count}")
        print(f"   errors (left untouched): {metrics['errors']}")
        return 0

    except Exception as e:
        logger.exception("reverify-candidates failed")
        print(f"❌ Error: {e}")
        return 1
