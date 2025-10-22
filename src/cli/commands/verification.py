"""URL verification command for CLI."""

import argparse
import inspect
import logging
from typing import Any

from src.services.url_verification import URLVerificationService


def add_verification_parser(subparsers) -> argparse.ArgumentParser:
    """Add verification command parser to subparsers."""
    verify_parser = subparsers.add_parser(
        "verify-urls", help="Run URL verification with StorySniffer"
    )

    verify_parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of URLs to process per batch (default: 100)",
    )

    verify_parser.add_argument(
        "--sleep-interval",
        type=int,
        default=30,
        help="Seconds to sleep when no work available (default: 30)",
    )

    verify_parser.add_argument(
        "--max-batches",
        type=int,
        help="Maximum number of batches to process (default: unlimited)",
    )

    verify_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    verify_parser.add_argument(
        "--status",
        action="store_true",
        help="Show current verification status and exit",
    )

    verify_parser.add_argument(
        "--continuous",
        action="store_true",
        help=(
            "Keep polling even when no URLs are waiting; without this flag "
            "the service exits once the queue is empty"
        ),
    )

    verify_parser.set_defaults(func=handle_verification_command)
    return verify_parser


def handle_verification_command(args) -> int:
    """Handle the verification command."""
    # Set up logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        service = URLVerificationService(
            batch_size=args.batch_size, sleep_interval=args.sleep_interval
        )

        if args.status:
            return show_verification_status(service)
        else:
            return run_verification_service(
                service,
                max_batches=args.max_batches,
                continuous=args.continuous,
            )

    except Exception as e:
        logging.error(f"Verification command failed: {e}")
        return 1


def show_verification_status(service: URLVerificationService) -> int:
    """Show current verification status."""
    try:
        status = service.get_status_summary()

        print("\nURL Verification Status:")
        print("=" * 40)
        print(f"Total URLs: {status['total_urls']}")
        print(f"Pending verification: {status['verification_pending']}")
        print(f"Verified articles: {status['articles_verified']}")
        print(f"Verified non-articles: {status['non_articles_verified']}")
        print(f"Verification failures: {status['verification_failures']}")

        print("\nStatus breakdown:")
        for status_name, count in status["status_breakdown"].items():
            print(f"  {status_name}: {count}")

        return 0

    except Exception as e:
        logging.error(f"Failed to get verification status: {e}")
        return 1


def run_verification_service(
    service: URLVerificationService,
    *,
    max_batches: int | None = None,
    continuous: bool = False,
) -> int:
    """Run the verification service."""
    try:
        if max_batches:
            print(f"🚀 Starting verification service (max {max_batches} batches)...")
            logging.info(f"Starting verification service (max {max_batches} batches)")
        elif continuous:
            print("🚀 Starting continuous verification service...")
            logging.info("Starting continuous verification service")
        else:
            print("🚀 Starting verification service (exit when idle)...")
            logging.info("Starting verification service (exit when idle)")

        loop_callable = service.run_verification_loop

        try:
            signature = inspect.signature(loop_callable)
        except (TypeError, ValueError):
            signature = None

        has_var_kw = False
        params: Any
        if signature is not None:
            params = signature.parameters
            has_var_kw = any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
            )
        else:
            params = {}

        loop_kwargs: dict[str, Any] = {}

        max_batches_supported = (
            signature is None or "max_batches" in params or has_var_kw
        )
        exit_on_idle_supported = (
            signature is None or "exit_on_idle" in params or has_var_kw
        )

        if max_batches_supported:
            loop_kwargs["max_batches"] = max_batches
        # Only exit on idle if continuous is False AND max_batches is NOT set
        # When max_batches is set, keep polling until we hit the batch limit
        if exit_on_idle_supported and not continuous and max_batches is None:
            loop_kwargs["exit_on_idle"] = True

        if loop_kwargs:
            loop_callable(**loop_kwargs)
        else:
            loop_callable()

        print("✅ Verification completed successfully!")
        return 0

    except KeyboardInterrupt:
        logging.info("Verification service stopped by user")
        return 0
    except Exception as e:
        logging.error(f"Verification service failed: {e}")
        return 1
