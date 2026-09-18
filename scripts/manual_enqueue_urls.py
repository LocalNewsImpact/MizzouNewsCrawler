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
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
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


def _read_urls(path: Path, column: str | None) -> list[str]:
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
            message = f"Column '{column}' not present in {path}. Available: {available}"
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
        urls = [line.strip() for line in path.read_text().splitlines() if line.strip()]

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def _lookup_host(host: str) -> str:
    """The host as `sources` keys it: lowercase, no port, no `www.`."""
    host = (host or "").lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _load_sources(db: DatabaseManager) -> dict:
    """Every source, keyed by the host a URL will present.

    Keyed on the stripped form so `www.spokesman.com` in a URL finds the
    `www.spokesman.com` source row and `ptleader.com` finds `ptleader.com`,
    whichever spelling each happens to store.
    """
    from sqlalchemy import text

    with db.get_session() as session:
        rows = session.execute(
            text("SELECT id, host, canonical_name, city, county, type FROM sources")
        ).mappings()
        out = {}
        for row in rows:
            out[_lookup_host(row["host"])] = dict(row)
    return out


def _build_dataframe(
    urls: Sequence[str],
    status: str,
    discovered_by: str,
    priority: int,
    metadata_flag: bool,
    dataset_id: str | None,
    sources: dict | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Convert URL sequence into a candidate_links DataFrame.

    Returns the frame and a count of URLs per host that no source row claims.

    A LINK WITHOUT source_id IS INVISIBLE TO ENRICHMENT.
    -----------------------------------------------------
    This used to set `source` and `source_name` to the bare host and leave
    `source_id` NULL. Extraction is unaffected -- it LEFT JOINs sources -- and
    so is classification, so such an article looks finished. Enrichment's
    candidate query does not:

        JOIN dataset_sources ds ON ds.source_id = cl.source_id

    An inner join on NULL matches nothing, so the article is never a candidate,
    never gets a place, and nothing reports it as skipped. The publisher's city
    and state, which the geography prompt is grounded on, also hang off that id.

    So the id is resolved here from the host, and the denormalised columns that
    every discovery-written row carries are filled from the same source record
    rather than from the URL string.
    """

    rows = []
    unknown: dict[str, int] = {}
    sources = sources or {}
    for raw in urls:
        parsed = urlparse(raw)
        host = parsed.netloc or "manual-import"
        normalized = normalize_url(raw)
        source = sources.get(_lookup_host(host))
        if source is None:
            unknown[_lookup_host(host)] = unknown.get(_lookup_host(host), 0) + 1
        row = {
            "url": normalized,
            # `source` carries the publisher NAME on every row discovery
            # writes, not the host; 259,025 rows disagree with the host.
            "source": (source or {}).get("canonical_name") or host,
            "source_name": (source or {}).get("canonical_name") or host,
            "status": status,
            "discovered_by": discovered_by,
            "priority": priority,
        }
        if source:
            row["source_id"] = source["id"]
            row["source_city"] = source.get("city")
            row["source_county"] = source.get("county")
            row["source_type"] = source.get("type")
        if metadata_flag:
            row["meta"] = json.dumps({"manual_import": True})
        if dataset_id:
            row["dataset_id"] = dataset_id
        rows.append(row)

    df = pd.DataFrame(rows)
    return df, unknown


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
) -> tuple[str, bool, str]:
    """Look up or create a Dataset for this manual enqueue batch.

    Returns a tuple of (dataset_id, created_flag, dataset_slug).
    """

    session = db.session

    if dataset_id:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise ValueError(
                f"Provided dataset_id does not exist in datasets table: {dataset_id}"
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


def _report_unknown(unknown: dict[str, int], allowed: bool) -> None:
    """Name the hosts no source claims, and what that costs.

    Printed rather than logged, and printed whether or not the run proceeds: a
    link with no source_id is invisible to enrichment and nothing downstream
    will ever say so.
    """
    if not unknown:
        return
    total = sum(unknown.values())
    verb = "enqueued anyway" if allowed else "refused"
    print(
        f"\n{total} URL(s) across {len(unknown)} host(s) have no source row "
        f"({verb}). Their articles would extract and classify but could never "
        f"be enriched -- enrichment joins dataset_sources on "
        f"candidate_links.source_id:"
    )
    for host, count in sorted(unknown.items(), key=lambda kv: -kv[1]):
        print(f"  {count:5}  {host}")


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
    allow_unknown_hosts: bool = False,
) -> int:
    """Insert the provided URLs into candidate_links.

    Returns number of rows written.
    """

    urls = _read_urls(input_path, column)
    if not urls:
        print("No URLs found in input file. Nothing to do.")
        return 0

    # The sources are read even for a dry run: which hosts have no source row
    # is the thing worth knowing BEFORE writing, since a link without a
    # source_id extracts and classifies normally and is then invisible to
    # enrichment for good.
    with DatabaseManager() as db:
        sources = _load_sources(db)

        if dry_run:
            df, unknown = _build_dataframe(
                urls,
                status,
                discovered_by,
                priority,
                metadata_flag,
                dataset_id=None,
                sources=sources,
            )
            print("Dry run -- would enqueue the following preview:")
            try:
                preview = df.head().to_markdown(index=False)
            except Exception:
                preview = df.head().to_string(index=False)
            print(preview)
            print(f"Total URLs prepared: {len(df)}")
            _report_unknown(unknown, allow_unknown_hosts)
            return 0

        resolved_dataset_id, created_dataset, dataset_slug = _ensure_dataset(
            db,
            dataset_id,
            dataset_label,
            input_path,
            discovered_by,
        )

        df, unknown = _build_dataframe(
            urls,
            status,
            discovered_by,
            priority,
            metadata_flag,
            dataset_id=resolved_dataset_id,
            sources=sources,
        )

        if unknown and not allow_unknown_hosts:
            _report_unknown(unknown, allow_unknown_hosts)
            print(
                "Nothing written. Add these hosts as sources, or pass "
                "--allow-unknown-hosts to enqueue them knowing their articles "
                "cannot be enriched."
            )
            return 0
        _report_unknown(unknown, allow_unknown_hosts)

        inserted = db.upsert_candidate_links(
            df, if_exists="append", dataset_id=resolved_dataset_id
        )

    summary = f"Inserted {inserted} new candidate links (out of {len(df)} prepared)."
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
    parser = argparse.ArgumentParser(description="Manually enqueue URLs for extraction")
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help=("Path to newline-delimited text, CSV, or TSV file containing URLs"),
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
        help=("Value for candidate_links.discovered_by (default: manual-import)"),
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
    parser.add_argument(
        "--allow-unknown-hosts",
        action="store_true",
        help=(
            "Enqueue URLs whose host has no source row. Their articles can "
            "never be enriched -- enrichment joins dataset_sources on "
            "candidate_links.source_id and an inner join on NULL matches "
            "nothing -- so this is refused by default."
        ),
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
        allow_unknown_hosts=args.allow_unknown_hosts,
    )

    return 0 if inserted or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
