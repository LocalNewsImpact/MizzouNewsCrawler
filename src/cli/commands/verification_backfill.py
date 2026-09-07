"""Write a verification row for decisions taken before anything recorded them.

245,473 URLs were verified and only the verdict was kept, in
`candidate_links.status`. The queue that reviews those verdicts
(docs/DISCOVERY_REVIEW_QUEUE.md) therefore has nothing to show for any of
them, and discovery has been idle since 2026-08-12 -- so waiting for
crawling to resume means waiting indefinitely.

storysniffer is a local model. This makes no request, needs no proxy and
cannot be blocked, which is why the whole backlog can be scored in one
offline pass.

A rescore is not the original decision. The pattern filter ran first and
both the rules and the model version have changed since, so where a
rescore disagrees with the recorded verdict the disagreement is the
finding, not a defect: it is the first estimate of the error rate before
any person opens a row.
"""

import argparse
import logging

from src.services.url_verification import URLVerificationService


def add_verification_backfill_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "backfill-verifications",
        help="Record the verification decisions that were never written",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Stop after this many links (default: every unrecorded one)",
    )
    parser.add_argument(
        "--dataset",
        help="Only links whose source belongs to this dataset slug",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per commit (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score and report agreement, write nothing",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    parser.set_defaults(func=handle_verification_backfill_command)
    return parser


def handle_verification_backfill_command(args) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level))
    # The HTTP pre-check is what would make this reach the network. Off
    # explicitly rather than by default, because a default is a thing
    # somebody changes for the live path without knowing this rides on it.
    service = URLVerificationService(run_http_precheck=False)
    counts = service.backfill_decisions(
        limit=args.limit,
        batch_size=args.batch_size,
        dataset=args.dataset,
        dry_run=args.dry_run,
    )

    considered = counts["considered"]
    print(f"considered: {considered}")
    print(f"written:    {counts['written']}{' (dry run)' if args.dry_run else ''}")
    print(f"errors:     {counts['errors']}")

    judged = counts["agree"] + counts["disagree"]
    if judged:
        # The number this run exists to produce. A rescore disagreeing
        # with the recorded verdict is where a reviewer should start.
        rate = counts["disagree"] / judged * 100
        print(
            f"agree:      {counts['agree']}\n"
            f"disagree:   {counts['disagree']} ({rate:.1f}% of {judged} judged)"
        )
    elif considered:
        print("nothing could be scored: storysniffer returned no answer")
    return 0
