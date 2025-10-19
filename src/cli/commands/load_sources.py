"""Load publinks CSV sources into the normalized database tables."""

from __future__ import annotations

import argparse
import logging
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.cli.context import trigger_gazetteer_population_background
from src.models import Dataset, DatasetSource, Source
from src.models.database import DatabaseManager
from src.utils.telemetry import OperationTracker, OperationType

logger = logging.getLogger(__name__)


REQUIRED_COLUMNS = ["host_id", "name", "city", "county", "url_news"]


def add_load_sources_parser(subparsers) -> argparse.ArgumentParser:
    """Register the load-sources command."""
    parser = subparsers.add_parser(
        "load-sources",
        help="Load publinks.csv into normalized dataset tables",
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to the publinks.csv file",
    )
    parser.set_defaults(func=handle_load_sources_command)
    return parser


def _normalize_source_row(row: pd.Series) -> dict[str, Any]:
    """Build candidate link payload from CSV row."""
    address = (f"{row.get('address1', '')}, {row.get('address2', '')}").strip(", ")
    zip_code = row.get("zip")
    if pd.isna(zip_code):
        zip_code = None
    else:
        zip_code = str(zip_code)

    return {
        "source_host_id": str(row["host_id"]),
        "source_name": row["name"],
        "source_city": row["city"],
        "source_county": row["county"],
        "url": row["url_news"],
        "source_type": row.get("media_type", "unknown"),
        "frequency": row.get("frequency", "unknown"),
        "owner": row.get("owner", "unknown"),
        "address": address,
        "zip_code": zip_code,
        "cached_geographic_entities": row.get(
            "cached_geographic_entities",
            "",
        ),
        "cached_institutions": row.get(
            "cached_institutions",
            "",
        ),
        "cached_schools": row.get("cached_schools", ""),
        "cached_government": row.get(
            "cached_government",
            "",
        ),
        "cached_healthcare": row.get(
            "cached_healthcare",
            "",
        ),
        "cached_businesses": row.get(
            "cached_businesses",
            "",
        ),
        "cached_landmarks": row.get(
            "cached_landmarks",
            "",
        ),
        "status": "pending",
        "priority": 1,
    }


def _validate_columns(df: pd.DataFrame) -> list[str]:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    return missing


def _parse_host_components(url: str) -> tuple[str, str]:
    """Return the raw and normalized host for the provided URL.

    Raises:
        ValueError: If the URL does not contain a hostname.
    """

    parsed = urlparse(url)
    host = parsed.netloc.strip()
    if not host:
        raise ValueError(f"Missing host in URL: {url}")

    host_norm = host.lower().strip()
    return host, host_norm


def _detect_duplicate_urls(df: pd.DataFrame) -> list[str]:
    """Identify duplicate URL strings or hosts within the CSV."""

    messages: list[str] = []

    duplicate_urls = df[df["url_news"].duplicated(keep=False)]
    if not duplicate_urls.empty:
        details = duplicate_urls[["host_id", "name", "url_news"]].to_dict("records")
        formatted = "; ".join(
            "host_id={host_id} name={name} url={url}".format(
                host_id=row["host_id"],
                name=row["name"],
                url=row["url_news"],
            )
            for row in details
        )
        messages.append(
            "Duplicate url_news entries detected: "
            f"{formatted}. Remove duplicates before retrying."
        )

    duplicate_hosts = df[df["_parsed_host_norm"].duplicated(keep=False)]
    if not duplicate_hosts.empty:
        grouped = duplicate_hosts.groupby("_parsed_host_norm")
        host_messages = []
        for host_norm, rows in grouped:
            entries = ", ".join(
                "host_id={host_id} name={name} url={url}".format(
                    host_id=row["host_id"],
                    name=row["name"],
                    url=row["url_news"],
                )
                for row in rows.to_dict("records")
            )
            host_messages.append(f"{host_norm}: {entries}")

        messages.append(
            ("Duplicate host values detected (same domain appears multiple times): ")
            + "; ".join(host_messages)
        )

    return messages


def handle_load_sources_command(args) -> int:
    """Execute the load-sources command."""
    csv_path = args.csv
    logger.info("Loading sources from %s", csv_path)
    
    # Initialize OperationTracker for telemetry
    tracker = OperationTracker()

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:  # pragma: no cover - passthrough logging
        logger.error("Failed to read CSV: %s", exc)
        return 1

    missing = _validate_columns(df)
    if missing:
        logger.error("Missing required columns: %s", missing)
        return 1

    # Pre-compute host components and validate duplicates prior to DB access.
    parsed_hosts: list[str] = []
    parsed_host_norms: list[str] = []

    for idx, url in enumerate(df["url_news"], start=1):
        try:
            raw_host, host_norm = _parse_host_components(url)
        except ValueError as exc:
            logger.error(
                "Row %s contains an invalid url_news value: %s",
                idx,
                exc,
            )
            return 1

        parsed_hosts.append(raw_host)
        parsed_host_norms.append(host_norm)

    df["_parsed_host"] = parsed_hosts
    df["_parsed_host_norm"] = parsed_host_norms

    duplicate_messages = _detect_duplicate_urls(df)
    if duplicate_messages:
        for message in duplicate_messages:
            logger.error(message)
        return 1

    db = DatabaseManager()
    Session = sessionmaker(bind=db.engine)
    session = Session()
    
    # Start tracking the load-sources operation
    with tracker.track_operation(
        OperationType.LOAD_SOURCES,
        source_file=csv_path,
        total_rows=len(df)
    ) as operation:
        try:
            dataset_slug = csv_path.split("/")[-1].replace(".", "_")
            dataset_slug = f"publinks-{dataset_slug}"

            dataset = session.execute(
                select(Dataset).where(Dataset.slug == dataset_slug)
            ).scalar_one_or_none()

            if dataset:
                logger.info("Using existing dataset: %s", dataset_slug)
            else:
                dataset = Dataset(
                    slug=dataset_slug,
                    label=f"Publisher Links from {csv_path.split('/')[-1]}",
                    name=f"Dataset from {csv_path}",
                    description=f"Publisher data imported from {csv_path}",
                    ingested_by="load_sources_command",
                    meta={"source_file": csv_path, "total_rows": len(df)},
                )
                session.add(dataset)
                session.flush()
                logger.info("Created new dataset: %s (ID: %s)", dataset_slug, dataset.id)

            sources_created = 0
            dataset_sources_created = 0
            candidate_links: list[dict[str, Any]] = []
            
            total_rows = len(df)
            operation.update_progress(0, total_rows, "Initializing load")

            for idx, (_, row) in enumerate(df.iterrows(), start=1):
                url = row["url_news"]
                host = row["_parsed_host"]
                host_norm = row["_parsed_host_norm"]

                existing_source = session.execute(
                    select(Source).where(Source.host_norm == host_norm)
                ).scalar_one_or_none()

                if existing_source:
                    source = existing_source
                else:
                    source = Source(
                        host=host,
                        host_norm=host_norm,
                        canonical_name=row["name"],
                        city=row["city"],
                        county=row["county"],
                        owner=row.get("owner", ""),
                        type=row.get("media_type", "unknown"),
                        meta={
                            "address1": row.get("address1", ""),
                            "address2": row.get("address2", ""),
                            "state": row.get("State", "MO"),
                            "zip": (
                                str(row.get("zip", ""))
                                if pd.notna(row.get("zip"))
                                else ""
                            ),
                            "frequency": row.get("frequency", ""),
                            "cached_geographic_entities": row.get(
                                "cached_geographic_entities",
                                "",
                            ),
                            "cached_institutions": row.get(
                                "cached_institutions",
                                "",
                            ),
                            "cached_schools": row.get("cached_schools", ""),
                            "cached_government": row.get(
                                "cached_government",
                                "",
                            ),
                            "cached_healthcare": row.get(
                                "cached_healthcare",
                                "",
                            ),
                            "cached_businesses": row.get(
                                "cached_businesses",
                                "",
                            ),
                            "cached_landmarks": row.get(
                                "cached_landmarks",
                                "",
                            ),
                        },
                    )
                    session.add(source)
                    session.flush()
                    sources_created += 1
                    logger.info(
                        "Created source: %s (ID: %s)",
                        source.canonical_name,
                        source.id,
                    )

                mapping = session.execute(
                    select(DatasetSource).where(
                        DatasetSource.dataset_id == dataset.id,
                        DatasetSource.source_id == source.id,
                    )
                ).scalar_one_or_none()

                if not mapping:
                    original_csv_row = row.drop(
                        labels=["_parsed_host", "_parsed_host_norm"],
                        errors="ignore",
                    ).to_dict()
                    dataset_source = DatasetSource(
                        dataset_id=dataset.id,
                        source_id=source.id,
                        legacy_host_id=str(row["host_id"]),
                        legacy_meta={"original_csv_row": original_csv_row},
                    )
                    session.add(dataset_source)
                    dataset_sources_created += 1

                link_data = _normalize_source_row(row)
                link_data.update(
                    {
                        "dataset_id": dataset.id,
                        "source_id": source.id,
                    }
                )
                candidate_links.append(link_data)
                
                # Update progress periodically
                if idx % 10 == 0 or idx == total_rows:
                    operation.update_progress(
                        idx,
                        total_rows,
                        f"Processed {idx} of {total_rows} rows",
                    )

            session.commit()
            logger.info(
                "Created %s sources and %s dataset mappings",
                sources_created,
                dataset_sources_created,
            )

            if candidate_links:
                result_df = pd.DataFrame(candidate_links)
                db.upsert_candidate_links(result_df)
                logger.info("Loaded %s candidate links", len(candidate_links))

            print("\n=== Load Summary ===")
            print(f"Dataset: {dataset.slug}")
            print(f"Total sources created: {sources_created}")
            print(f"Total candidate links: {len(candidate_links)}")
            print(f"Unique counties: {df['county'].nunique()}")
            print(f"Unique cities: {df['city'].nunique()}")
            if "media_type" in df.columns:
                print(f"Media types: {df['media_type'].value_counts().to_dict()}")

            logger.info("Auto-triggering gazetteer population for new dataset")
            try:
                trigger_gazetteer_population_background(str(dataset.slug), logger)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("Failed to trigger gazetteer population: %s", exc)

            return 0

        except Exception as exc:
            logger.error("Failed to load sources: %s", exc)
            session.rollback()
            return 1
        finally:
            session.close()
