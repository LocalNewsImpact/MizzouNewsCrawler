"""Check ingested URLs with the URL rules and storysniffer, and change nothing.

An ingested URL -- one handed over as part of a chosen set -- skips URL
verification so that no rule or model can remove it. That also meant nothing
looked at it: KHQ's `/video_` pages came in through the WSU tracker and were
fetched, stored and filed before anything read the URL.

This records what the checks say, one `url_verifications` row per link with
`verdict_kind: "ingested"`, and never writes `candidate_links.status`. A
flagged link is for a person to judge in the discovery review queue; it is
still fetched. The external wire check is not part of this.

storysniffer is local: no request, no proxy, cannot be blocked.
"""

import argparse
import logging

from src.services.url_verification import URLVerificationService


def add_check_ingested_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "check-ingested",
        help="Run URL rules and storysniffer over ingested URLs; record, do not filter",
    )
    parser.add_argument(
        "--dataset",
        help="Only ingested links in this dataset (name, slug or UUID)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be flagged without writing anything",
    )
    return parser


def handle_ingest_check_command(args) -> int:
    from src.models.database import DatabaseManager
    from src.utils.dataset_utils import resolve_dataset_id

    logging.basicConfig(level=logging.INFO)
    dataset_uuid = (
        resolve_dataset_id(DatabaseManager().engine, args.dataset)
        if args.dataset
        else None
    )
    service = URLVerificationService(run_http_precheck=False, dataset_id=dataset_uuid)
    counts = service.check_ingested(
        limit=args.limit, batch_size=args.batch_size, dry_run=args.dry_run
    )
    print(f"considered: {counts['considered']}")
    print(f"written:    {counts['written']}{' (dry run)' if args.dry_run else ''}")
    print(f"flagged:    {counts['flagged']}  for review; still fetched")
    print(f"errors:     {counts['errors']}")
    return 0
