"""Dataset version management commands for the modular CLI."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.models.versioning import (
    create_dataset_version,
    export_dataset_version,
    export_snapshot_for_version,
    list_dataset_versions,
)

logger = logging.getLogger(__name__)


def add_versioning_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register dataset version management commands."""
    create_parser = subparsers.add_parser(
        "create-version",
        help="Create a new dataset version",
    )
    create_parser.add_argument(
        "--dataset",
        required=True,
        help="Dataset name (e.g., candidate_links)",
    )
    create_parser.add_argument(
        "--tag",
        required=True,
        help="Version tag, e.g. v2025-09-18-1",
    )
    create_parser.add_argument(
        "--description",
        help="Optional description for the version",
    )
    create_parser.set_defaults(func=handle_create_version_command)

    list_parser = subparsers.add_parser(
        "list-versions",
        help="List dataset versions",
    )
    list_parser.add_argument(
        "--dataset",
        help="Optional dataset name filter",
    )
    list_parser.set_defaults(func=handle_list_versions_command)

    export_parser = subparsers.add_parser(
        "export-version",
        help="Export a dataset version snapshot",
    )
    export_parser.add_argument(
        "--version-id",
        required=True,
        help="Dataset version id",
    )
    export_parser.add_argument(
        "--output",
        required=True,
        help="Output path for exported snapshot",
    )
    export_parser.set_defaults(func=handle_export_version_command)

    snapshot_parser = subparsers.add_parser(
        "export-snapshot",
        help=(
            "Create a snapshot Parquet file for a dataset version by "
            "exporting a DB table"
        ),
    )
    snapshot_parser.add_argument(
        "--version-id",
        required=True,
        help="Dataset version id",
    )
    snapshot_parser.add_argument(
        "--table",
        required=True,
        help="Database table to export",
    )
    snapshot_parser.add_argument(
        "--output",
        required=True,
        help="Output path for snapshot",
    )
    snapshot_parser.add_argument(
        "--snapshot-chunksize",
        type=int,
        default=10_000,
        help="Rows per chunk when streaming export (default: 10000)",
    )
    snapshot_parser.add_argument(
        "--snapshot-compression",
        choices=["snappy", "gzip", "brotli", "zstd", "none"],
        default=None,
        help="Parquet compression codec to use",
    )
    snapshot_parser.set_defaults(func=handle_export_snapshot_command)


def handle_create_version_command(args: argparse.Namespace) -> int:
    """Create a new dataset version and print its identifier."""
    try:
        version = create_dataset_version(
            dataset_name=args.dataset,
            version_tag=args.tag,
            description=getattr(args, "description", None),
        )
    except Exception as exc:  # pragma: no cover - passthrough logging
        logger.exception("Failed to create dataset version")
        print(f"Failed to create dataset version: {exc}")
        return 1

    print(f"Created dataset version: {version.id} (tag={version.version_tag})")
    return 0


def handle_list_versions_command(args: argparse.Namespace) -> int:
    """List dataset versions, optionally filtered by dataset name."""
    dataset: str | None = getattr(args, "dataset", None)

    try:
        if dataset is None:
            versions = list_dataset_versions()
        else:
            versions = list_dataset_versions(dataset)
    except Exception as exc:  # pragma: no cover - passthrough logging
        logger.exception("Failed to list dataset versions")
        print(f"Failed to list dataset versions: {exc}")
        return 1

    if not versions:
        print("No dataset versions found")
        return 0

    for version in versions:
        print(
            f"{version.id}\t{version.dataset_name}\t"
            f"{version.version_tag}\t{version.created_at}\t"
            f"{version.snapshot_path}"
        )
    return 0


def handle_export_version_command(args: argparse.Namespace) -> int:
    """Export a dataset version snapshot to a local path."""
    try:
        output = export_dataset_version(args.version_id, args.output)
    except Exception as exc:  # pragma: no cover - passthrough logging
        logger.exception("Failed to export dataset version")
        print(f"Failed to export version: {exc}")
        return 1

    print(f"Exported version to: {output}")
    return 0


def handle_export_snapshot_command(args: argparse.Namespace) -> int:
    """Stream a Parquet snapshot for a dataset version."""
    compression = getattr(args, "snapshot_compression", None)
    resolved_compression: str | None = None
    if compression is not None and compression.lower() != "none":
        resolved_compression = compression

    try:
        output_path = str(Path(args.output))
        version = export_snapshot_for_version(
            args.version_id,
            args.table,
            output_path,
            chunksize=getattr(args, "snapshot_chunksize", 10_000),
            compression=resolved_compression,
        )
    except Exception as exc:  # pragma: no cover - passthrough logging
        logger.exception("Failed to export snapshot")
        print(f"Failed to export snapshot: {exc}")
        return 1

    version_id = getattr(version, "id", args.version_id)
    snapshot_path = getattr(version, "snapshot_path", str(version))
    print(f"Snapshot created and version finalized: {version_id} -> {snapshot_path}")
    return 0
