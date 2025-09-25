"""Commands for inspecting HTTP status telemetry."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Dict, List

from sqlalchemy import text

from src.models.database import DatabaseManager


logger = logging.getLogger(__name__)


def add_http_status_parser(subparsers) -> argparse.ArgumentParser:
    """Register the dump-http-status command."""
    parser = subparsers.add_parser(
        "dump-http-status",
        help="Dump recent http_status_tracking rows for a source",
    )
    parser.add_argument(
        "--source-id",
        help="Source UUID to filter telemetry by source_id",
    )
    parser.add_argument(
        "--host",
        help=(
            "Source host (e.g., www.example.com) to filter telemetry "
            "by source_url/host"
        ),
    )
    parser.add_argument(
        "--lookup-host",
        action="store_true",
        help=(
            "Lookup the given --host in the sources table and filter by its "
            "source_id(s)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of rows to return (default: 50)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )

    return parser


def handle_http_status_command(args) -> int:
    """Execute the dump-http-status command."""
    source_id = getattr(args, "source_id", None)
    host = getattr(args, "host", None)
    limit = getattr(args, "limit", 50) or 50
    out_format = getattr(args, "format", "table")
    lookup_host = getattr(args, "lookup_host", False)

    params: Dict[str, str | int] = {"limit": limit}
    where_clauses: List[str] = []

    try:
        with DatabaseManager() as db:
            if lookup_host and host:
                resolved_ids = _resolve_host_to_source_ids(db, host)
            else:
                resolved_ids = []

            if source_id:
                where_clauses.append("source_id = :source_id")
                params["source_id"] = source_id
            elif resolved_ids:
                placeholders = ",".join(
                    f":sid{i}" for i in range(len(resolved_ids))
                )
                where_clauses.append(f"source_id IN ({placeholders})")
                for idx, sid in enumerate(resolved_ids):
                    params[f"sid{idx}"] = sid

            if host and not lookup_host:
                where_clauses.append(
                    "(source_url LIKE :host_like OR "
                    "attempted_url LIKE :host_like)"
                )
                params["host_like"] = f"%{host}%"

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)
            else:
                print(
                    "Warning: no --source-id or --host provided; "
                    "showing latest entries across all sources"
                )

            sql = text(
                (
                    "SELECT id, source_id, source_url, attempted_url, "
                    "discovery_method, status_code, status_category, "
                    "response_time_ms, content_length, error_message, "
                    "timestamp "
                    "FROM http_status_tracking "
                    f"{where_sql} ORDER BY id DESC LIMIT :limit"
                )
            )

            with db.engine.connect() as conn:
                results = conn.execute(sql, params)
                rows = [dict(row) for row in results.fetchall()]

        if out_format == "json":
            print(json.dumps(rows, default=str, indent=2))
            return 0

        _print_http_status_table(rows)
        return 0
    except Exception as exc:
        logger.exception("Failed to query http_status_tracking")
        print(f"Failed to query http_status_tracking: {exc}")
        return 1


def _resolve_host_to_source_ids(db: DatabaseManager, host: str) -> List[str]:
    """Lookup source IDs matching a host pattern."""
    query = text(
        "SELECT id FROM sources WHERE host LIKE :h OR host_norm LIKE :h_norm"
    )

    try:
        with db.engine.connect() as conn:
            result = conn.execute(
                query,
                {"h": f"%{host}%", "h_norm": f"%{host.lower()}%"},
            )
            return [row[0] for row in result.fetchall()]
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"Host lookup failed: {exc}")
        return []


def _print_http_status_table(rows: List[Dict[str, object]]) -> None:
    if not rows:
        print("No http status records found for the given filters")
        return

    header = (
        f"{'id':<6} {'source_id':<36} {'attempted_url':<40} "
        f"{'status':<6} {'cat':<4} {'rt_ms':>8} {'ts':<20}"
    )
    print(header)
    print("-" * len(header))

    for row in rows:
        attempted = str(row.get("attempted_url") or "")[:38]
        source_uuid = str(row.get("source_id") or "")[:36]
        status_code = str(row.get("status_code") or "")
        category = row.get("status_category") or ""
        response_time = row.get("response_time_ms") or 0
        timestamp = str(row.get("timestamp") or "")[:19]
        row_id = row.get("id")
        print(
            f"{row_id:<6} {source_uuid:<36} {attempted:<40} "
            f"{status_code:<6} {category:<4} {response_time:>8} "
            f"{timestamp:<20}"
        )
