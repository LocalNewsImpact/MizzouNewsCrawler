#!/usr/bin/env python3
"""Utility for seeding candidate_links with a manual URL list.

This is useful when you already have a curated batch of article URLs and
want to push them directly into the pipeline without running the discovery
stage. The script accepts newline-delimited text files or CSV/TSV files with
at least a ``url`` column, normalises each URL, derives a source host value,
and bulk inserts the records into ``candidate_links`` using the existing
``DatabaseManager`` helper.

Typical usage::

    python scripts/manual_enqueue_urls.py --input urls.txt \
        --status discovered --discovered-by manual-import --priority 5

After insertion you can run the verification service and extraction command
as usual:

    python -m src.services.url_verification_service --max-batches 1
    python -m src.cli.main extract --limit 50 --batches 5

"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple
from urllib.parse import urlparse

import pandas as pd

# Ensure ``src`` package is importable when running from repository root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from src.models import Dataset  # noqa: E402
from src.models.database import DatabaseManager  # noqa: E402
from src.utils.url_utils import normalize_url  # noqa: E402

ALLOWED_STATUSES = {"discovered", "article", "not_article"}


def _read_urls(path: Path, column: str | None) -> List[str]:
    """Load URLs from a text/CSV file.

    Args:
        path: Path to the file containing URLs.
        column: Optional column name to read when parsing CSV/TSV.

    Returns:
        List of URL strings (duplicates removed, order preserved).
    """

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv", ".txt"} and column:
        # Allow explicit column selection for delimited files
        sep = "\t" if suffix == ".tsv" else ","
        df = pd.read_csv(path, sep=sep)
        if column not in df.columns:
            available = ", ".join(df.columns.astype(str))
            message = (
                f"Column '{column}' not present in {path}. "
                f"Available: {available}"
            )
            raise ValueError(message)
        urls = df[column].dropna().astype(str).tolist()
    elif suffix in {".csv", ".tsv"}:
        df = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",")
        lower_cols = {c.lower(): c for c in df.columns}
        url_col = lower_cols.get("url")
        if not url_col:
            raise ValueError(
                "CSV/TSV input must include a 'url' column or specify --column"
            )
        urls = df[url_col].dropna().astype(str).tolist()
    else:
        urls = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip()
        ]

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def _build_dataframe(
    urls: Sequence[str],
    status: str,
    discovered_by: str,
    priority: int,
    metadata_flag: bool,
    dataset_id: str | None,
) -> pd.DataFrame:
    """Convert URL sequence into a candidate_links DataFrame."""

    rows = []
    for raw in urls:
        parsed = urlparse(raw)
        host = parsed.netloc or "manual-import"
        normalized = normalize_url(raw)
        row = {
            "url": normalized,
            "source": host,
            "source_name": host,
            "status": status,
            "discovered_by": discovered_by,
            "priority": priority,
        }
        if metadata_flag:
            row["meta"] = json.dumps({"manual_import": True})
        if dataset_id:
            row["dataset_id"] = dataset_id
        rows.append(row)

    df = pd.DataFrame(rows)
    return df


def _slugify(value: str) -> str:
    """Generate a slug suitable for Dataset.slug."""

    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or f"manual-{uuid.uuid4().hex[:8]}"


def _ensure_dataset(
    db: DatabaseManager,
    dataset_id: str | None,
    dataset_label: str | None,
    input_path: Path,
    discovered_by: str,
) -> Tuple[str, bool, str]:
    """Look up or create a Dataset for this manual enqueue batch.

    Returns a tuple of (dataset_id, created_flag, dataset_slug).
    """

    session = db.session

    if dataset_id:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise ValueError(
                "Provided dataset_id does not exist in datasets table: "
                f"{dataset_id}"
            )
        return str(dataset.id), False, dataset.slug

    label = dataset_label or (
        f"Manual enqueue {datetime.utcnow():%Y-%m-%d %H:%M:%S UTC}"
    )
    base_slug = _slugify(label)
    slug = base_slug
    counter = 1
    while True:
        existing = session.execute(
            select(Dataset).where(Dataset.slug == slug)
        ).scalar_one_or_none()
        if not existing:
            break
        counter += 1
        slug = f"{base_slug}-{counter}"

    dataset = Dataset(
        slug=slug,
        label=label,
        name=label,
        description=(
            f"Manual enqueue created from {input_path.name} on "
            f"{datetime.utcnow():%Y-%m-%d}"
        ),
        ingested_by="manual_enqueue_urls",
        meta={
            "source_file": str(input_path),
            "created_via": "manual_enqueue_urls",
            "discovered_by": discovered_by,
        },
    )
    session.add(dataset)
    session.commit()

    return str(dataset.id), True, slug


def enqueue_urls(
    input_path: Path,
    status: str,
    discovered_by: str,
    priority: int,
    dataset_id: str | None,
    dataset_label: str | None,
    column: str | None,
    metadata_flag: bool,
    dry_run: bool,
) -> int:
    """Insert the provided URLs into candidate_links.

    Returns number of rows written.
    """

    urls = _read_urls(input_path, column)
    if not urls:
        print("No URLs found in input file. Nothing to do.")
        return 0

    if dry_run:
        df = _build_dataframe(
            urls,
            status,
            discovered_by,
            priority,
            metadata_flag,
            dataset_id=None,
        )
        print("Dry run -- would enqueue the following preview:")
        try:
            preview = df.head().to_markdown(index=False)
        except Exception:
            preview = df.head().to_string(index=False)
        print(preview)
        print(f"Total URLs prepared: {len(df)}")
        return 0

    with DatabaseManager() as db:
        resolved_dataset_id, created_dataset, dataset_slug = _ensure_dataset(
            db,
            dataset_id,
            dataset_label,
            input_path,
            discovered_by,
        )

        df = _build_dataframe(
            urls,
            status,
            discovered_by,
            priority,
            metadata_flag,
            dataset_id=resolved_dataset_id,
        )

        inserted = db.upsert_candidate_links(
            df, if_exists="append", dataset_id=resolved_dataset_id
        )

    summary = (
        "Inserted {inserted} new candidate links (out of {total} prepared)."
    ).format(inserted=inserted, total=len(df))
    print(summary)
    print(
        "Dataset {dataset_id} ({slug}) {action}.".format(
            dataset_id=resolved_dataset_id,
            slug=dataset_slug,
            action="created" if created_dataset else "re-used",
        )
    )
    if inserted < len(df):
        print("Existing URLs were skipped to avoid duplicates.")
    return inserted


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually enqueue URLs for extraction"
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help=(
            "Path to newline-delimited text, CSV, or TSV file containing URLs"
        ),
    )
    parser.add_argument(
        "--column",
        help="Column to use when reading CSV/TSV input (defaults to 'url')",
    )
    parser.add_argument(
        "--status",
        choices=sorted(ALLOWED_STATUSES),
        default="discovered",
        help="Candidate status to assign (default: discovered)",
    )
    parser.add_argument(
        "--discovered-by",
        default="manual-import",
        help=(
            "Value for candidate_links.discovered_by (default: manual-import)"
        ),
    )
    parser.add_argument(
        "--priority",
        type=int,
        default=5,
        help="Priority to assign for extraction scheduling (default: 5)",
    )
    parser.add_argument(
        "--dataset-id",
        help="Optional dataset UUID to associate with these links",
    )
    parser.add_argument(
        "--dataset-label",
        help=(
            "Optional dataset label. If omitted, a new dataset label will be "
            "generated automatically when --dataset-id is not supplied."
        ),
    )
    parser.add_argument(
        "--mark-manual",
        action="store_true",
        help="Tag meta.manual_import = true for downstream auditing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rows that would be inserted without touching the DB",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    inserted = enqueue_urls(
        input_path=args.input,
        status=args.status,
        discovered_by=args.discovered_by,
        priority=args.priority,
        dataset_id=args.dataset_id,
        dataset_label=args.dataset_label,
        column=args.column,
        metadata_flag=args.mark_manual,
        dry_run=args.dry_run,
    )

    return 0 if inserted or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
