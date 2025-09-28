"""Background process monitoring commands for the modular CLI."""

from __future__ import annotations

import argparse
import logging
from typing import Iterable

from sqlalchemy import text

from src.models.database import DatabaseManager


logger = logging.getLogger(__name__)


def add_status_parser(subparsers) -> argparse.ArgumentParser:
    """Register the status command."""
    parser = subparsers.add_parser(
        "status",
        help="Show crawling status and background process information",
    )
    parser.add_argument(
        "--processes",
        action="store_true",
        help="List recent background processes",
    )
    parser.add_argument(
        "--process",
        type=str,
        help="Show details for a specific background process ID",
    )
    parser.set_defaults(func=handle_status_command)
    return parser


def add_queue_parser(subparsers) -> argparse.ArgumentParser:
    """Register the queue command."""
    parser = subparsers.add_parser(
        "queue",
        help="Show active background processes queue",
    )
    parser.set_defaults(func=handle_queue_command)
    return parser


def handle_status_command(args) -> int:
    """Handle the status command."""
    if getattr(args, "process", None):
        return show_process_status(args.process)

    if getattr(args, "processes", False):
        success = show_background_processes()
        return 0 if success else 1

    return _print_database_status()


def handle_queue_command(_args) -> int:
    """Handle the queue command."""
    success = show_active_queue()
    return 0 if success else 1


def show_process_status(process_id: str) -> int:
    """Show detailed information for a background process."""
    try:
        from src.models import BackgroundProcess

        with DatabaseManager() as db:
            session = db.session
            process = (
                session.query(BackgroundProcess)
                .filter_by(id=process_id)
                .first()
            )

            if not process:
                print(f"Process {process_id} not found")
                return 1

            _print_process_detail(process)
            return 0
    except Exception as exc:
        print(f"Error checking process status: {exc}")
        logger.exception("Process status lookup failed")
        return 1


def show_background_processes(limit: int = 20) -> bool:
    """Print a table of recent background processes."""
    try:
        from src.models import BackgroundProcess

        with DatabaseManager() as db:
            session = db.session
            processes = (
                session.query(BackgroundProcess)
                .order_by(BackgroundProcess.started_at.desc())
                .limit(limit)
                .all()
            )

            if not processes:
                print("No background processes found")
                return True

            _print_process_table(processes)
            return True
    except Exception as exc:
        print(f"Error listing background processes: {exc}")
        logger.exception("Background process listing failed")
        return False


def show_active_queue() -> bool:
    """Show active (pending or running) processes."""
    try:
        from src.models import BackgroundProcess

        with DatabaseManager() as db:
            session = db.session
            status_attr = getattr(BackgroundProcess, "status")
            active = (
                session.query(BackgroundProcess)
                .filter(status_attr.in_(["pending", "running"]))
                .order_by(BackgroundProcess.started_at.asc())
                .all()
            )

            if not active:
                print("No active background processes")
                return True

            print("Active Background Processes:")
            print("-" * 90)
            header = (
                f"{'ID':<8} {'Status':<10} {'Command':<25} "
                f"{'Progress':<15} {'Duration':<15} {'Publisher':<15}"
            )
            print(header)
            print("-" * 90)

            for process in active:
                progress = _format_progress(process)
                started_at = getattr(process, "started_at", None)
                duration = ""
                status_value = getattr(process, "status", None)
                if started_at is not None and status_value == "running":
                    duration = f"{process.duration_seconds:.0f}s"
                publisher = ""
                metadata = process.process_metadata or {}
                if "publisher_uuid" in metadata:
                    publisher = metadata["publisher_uuid"][:12]

                print(
                    f"{process.id:<8} {process.status:<10} "
                    f"{process.command[:24]:<25} {progress:<15} "
                    f"{duration:<15} {publisher:<15}"
                )

            return True
    except Exception as exc:
        print(f"Error listing queue: {exc}")
        logger.exception("Queue listing failed")
        return False


def _print_database_status() -> int:
    """Print aggregated database statistics."""
    try:
        with DatabaseManager() as db:
            with db.engine.connect() as conn:
                _print_candidate_link_status(conn)
                _print_article_status(conn)
                _print_top_sources(conn)
                _print_geographic_distribution(conn)

        return 0
    except Exception as exc:
        logger.error("Failed to get status: %s", exc)
        print(f"Failed to get status: {exc}")
        return 1


def _print_candidate_link_status(conn) -> None:
    result = conn.execute(
        text(
            """
            SELECT status, COUNT(*) as count
            FROM candidate_links
            GROUP BY status
            ORDER BY count DESC
        """
        )
    )
    print("\n=== Candidate Links Status ===")
    for row in result:
        print(f"{row[0]}: {row[1]}")


def _print_article_status(conn) -> None:
    result = conn.execute(
        text(
            """
            SELECT status, COUNT(*) as count
            FROM articles
            GROUP BY status
            ORDER BY count DESC
        """
        )
    )
    print("\n=== Articles Status ===")
    for row in result:
        print(f"{row[0]}: {row[1]}")


def _print_top_sources(conn) -> None:
    result = conn.execute(
        text(
            """
            SELECT
                cl.source_name,
                cl.source_county,
                cl.source_city,
                COUNT(a.id) as article_count
            FROM candidate_links cl
            LEFT JOIN articles a ON cl.id = a.candidate_link_id
            GROUP BY cl.source_name, cl.source_county, cl.source_city
            ORDER BY article_count DESC
            LIMIT 10
        """
        )
    )
    print("\n=== Top Sources by Article Count ===")
    for row in result:
        print(f"{row[0]} ({row[2]}, {row[1]}): {row[3]} articles")


def _print_geographic_distribution(conn) -> None:
    result = conn.execute(
        text(
            """
            SELECT
                cl.source_county,
                COUNT(DISTINCT cl.id) as sources,
                COUNT(a.id) as articles
            FROM candidate_links cl
            LEFT JOIN articles a ON cl.id = a.candidate_link_id
            GROUP BY cl.source_county
            ORDER BY sources DESC
            LIMIT 10
        """
        )
    )
    print("\n=== Geographic Distribution (Top Counties) ===")
    for row in result:
        print(f"{row[0]}: {row[1]} sources, {row[2]} articles")


def _print_process_table(processes: Iterable) -> None:
    print("Background Processes (most recent 20):")
    print("-" * 80)
    print(
        f"{'ID':<8} {'Status':<10} {'Command':<20} "
        f"{'Progress':<15} {'Started':<20}"
    )
    print("-" * 80)

    for process in processes:
        progress = _format_progress(process)
        started = (
            process.started_at.strftime("%Y-%m-%d %H:%M")
            if process.started_at
            else ""
        )
        print(
            f"{process.id:<8} {process.status:<10} "
            f"{process.command[:20]:<20} {progress:<15} {started:<20}"
        )


def _print_process_detail(process) -> None:
    print(f"Process ID: {process.id}")
    print(f"Status: {process.status}")
    print(f"Command: {process.command}")

    progress = _format_progress(process, detailed=True)
    if progress:
        print(f"Progress: {progress}")

    if process.started_at:
        print(f"Started: {process.started_at}")
    if process.completed_at:
        print(f"Completed: {process.completed_at}")
    elif process.status == "running":
        print(f"Duration: {process.duration_seconds:.0f} seconds")

    if process.process_metadata:
        print("Metadata:")
        for key, value in process.process_metadata.items():
            print(f"  {key}: {value}")

    if process.error_message:
        print(f"Error: {process.error_message}")


def _format_progress(process, detailed: bool = False) -> str:
    total = process.progress_total
    current = process.progress_current or 0

    if total:
        percentage = process.progress_percentage or 0
        if detailed:
            return (
                f"{current}/{total} ({percentage:.1f}%)"
            )
        return f"{current}/{total}"

    return str(current)
