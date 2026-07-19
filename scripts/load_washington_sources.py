#!/usr/bin/env python3
"""Load the WSU Washington State sources CSV into datasets/sources/dataset_sources.

This does the same work as ``python -m src.cli load-sources`` but with raw SQL
instead of the ORM, for two reasons:

1. ``select(Dataset)`` currently fails against production: the ORM declares
   ``datasets.created_at`` but no migration ever added that column, so every ORM
   read of a Dataset errors with ``column datasets.created_at does not exist``.
   (``safe_session_execute`` masks this as a confusing bind-parameter error.)
2. ``load-sources`` also enqueues each ``url_news`` as a candidate link. Our CSV
   carries homepages, not stories, so those rows would be junk candidates —
   discovery finds the real articles.

Idempotent and re-runnable: rows are matched on ``sources.host_norm`` and on the
dataset slug. A host that already exists has its name/city/county/owner/type and
metadata (address, ZIP, frequency, cohort) refreshed from the CSV, so enriching
the CSV and re-running is the supported way to update the dataset in place.

Run inside a pod per the repo's DB access protocol::

    kubectl cp scripts/load_washington_sources.py production/<cli-pod>:/app/load_washington_sources.py
    kubectl cp sources/wsu_washington_sources.csv production/<cli-pod>:/app/wsu_washington_sources.csv
    kubectl exec -n production <cli-pod> -- python /app/load_washington_sources.py \
        --csv /app/wsu_washington_sources.csv [--commit]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from src.models.database import DatabaseManager  # noqa: E402

DATASET_SLUG = "WSU-Washington-State"
DATASET_LABEL = "WSU Washington State"
DATASET_NAME = "Washington State News Sources"
DATASET_DESCRIPTION = (
    "Washington news organizations for the WSU / Murrow Local News Fellowship "
    "study: treatment orgs (fellow host newsrooms), control orgs, and "
    "additional outlets observed in the Murrow fellow story tracker."
)


def _source_fields(row: dict, host: str, host_norm: str) -> dict:
    """Map a CSV row onto the sources columns.

    ``publisher_geo_filter`` reads address1/address2/zip/frequency/media_type out
    of the source metadata: ZIP is its geocoding fallback when a publisher's city
    and county coordinates cannot be resolved, and the resulting coordinates seed
    the OSM gazetteer lookup. Empty values are stored as empty strings, matching
    how the Missouri load-sources import shaped this blob.
    """
    return {
        "host": host,
        "host_norm": host_norm,
        "canonical_name": row["name"],
        "city": row["city"],
        "county": row["county"],
        "owner": row.get("owner", ""),
        "type": row.get("media_type", "unknown"),
        "metadata": json.dumps(
            {
                "address1": row.get("address1", ""),
                "address2": row.get("address2", ""),
                "state": row.get("State", "WA"),
                "zip": str(row.get("zip", "") or ""),
                "frequency": row.get("frequency", ""),
                "media_type": row.get("media_type", ""),
                "cohort": row.get("cohort", ""),
                "source": row.get("source", ""),
                "address_source": row.get("address_source", ""),
                "owner_source": row.get("owner_source", ""),
            }
        ),
    }


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Path to the sources CSV")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write. Without this the script reports what it would do.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    rows = list(csv.DictReader(open(args.csv, newline="")))
    if not rows:
        print("ERROR: CSV is empty", file=sys.stderr)
        return 1

    db = DatabaseManager()
    created_sources = 0
    linked_sources = 0
    existing_sources = 0

    with db.get_session() as session:
        dataset_id = session.execute(
            text("SELECT id FROM datasets WHERE slug = :slug"),
            {"slug": DATASET_SLUG},
        ).scalar_one_or_none()

        if dataset_id:
            print(f"Dataset {DATASET_SLUG} already exists ({dataset_id})")
        else:
            dataset_id = str(uuid.uuid4())
            print(f"CREATE dataset {DATASET_SLUG} ({dataset_id})")
            if args.commit:
                session.execute(
                    # ingested_at is NOT NULL in production and has no server
                    # default there, despite what the ORM model implies.
                    text("""
                        INSERT INTO datasets
                            (id, slug, label, name, description, ingested_at,
                             ingested_by, metadata, is_public, cron_enabled)
                        VALUES
                            (:id, :slug, :label, :name, :description, NOW(),
                             :ingested_by, CAST(:metadata AS JSON), :is_public,
                             :cron_enabled)
                        """),
                    {
                        "id": dataset_id,
                        "slug": DATASET_SLUG,
                        "label": DATASET_LABEL,
                        "name": DATASET_NAME,
                        "description": DATASET_DESCRIPTION,
                        "ingested_by": "load_washington_sources",
                        "metadata": json.dumps(
                            {"source_file": args.csv, "total_rows": len(rows)}
                        ),
                        "is_public": False,
                        "cron_enabled": False,
                    },
                )

        for row in rows:
            host = row["url_news"].split("//", 1)[1].strip("/")
            host_norm = host.lower()

            fields = _source_fields(row, host, host_norm)

            source_id = session.execute(
                text("SELECT id FROM sources WHERE host_norm = :h"),
                {"h": host_norm},
            ).scalar_one_or_none()

            if source_id:
                existing_sources += 1
                print(f"  UPDATE  {host_norm:<34} {row['name']}")
                if args.commit:
                    session.execute(
                        text("""
                            UPDATE sources
                            SET canonical_name = :canonical_name,
                                city = :city,
                                county = :county,
                                owner = :owner,
                                type = :type,
                                metadata = CAST(:metadata AS JSON)
                            WHERE id = :id
                            """),
                        {**fields, "id": source_id},
                    )
            else:
                source_id = str(uuid.uuid4())
                created_sources += 1
                print(f"  CREATE  {host_norm:<34} {row['name']}")
                if args.commit:
                    session.execute(
                        text("""
                            INSERT INTO sources
                                (id, host, host_norm, canonical_name, city, county,
                                 owner, type, metadata, status)
                            VALUES
                                (:id, :host, :host_norm, :canonical_name, :city,
                                 :county, :owner, :type, CAST(:metadata AS JSON),
                                 :status)
                            """),
                        {**fields, "id": source_id, "status": "active"},
                    )

            if not args.commit:
                continue

            mapped = session.execute(
                text("""
                    SELECT 1 FROM dataset_sources
                    WHERE dataset_id = :d AND source_id = :s
                    """),
                {"d": dataset_id, "s": source_id},
            ).scalar_one_or_none()
            if not mapped:
                linked_sources += 1
                session.execute(
                    text("""
                        INSERT INTO dataset_sources
                            (id, dataset_id, source_id, legacy_host_id, legacy_meta)
                        VALUES
                            (:id, :d, :s, :hid, CAST(:meta AS JSON))
                        """),
                    {
                        "id": str(uuid.uuid4()),
                        "d": dataset_id,
                        "s": source_id,
                        "hid": str(row["host_id"]),
                        "meta": json.dumps({"original_csv_row": row}),
                    },
                )

        if args.commit:
            session.commit()

    verb = "Wrote" if args.commit else "DRY RUN (pass --commit to write):"
    print(
        f"\n{verb} sources created={created_sources} "
        f"updated={existing_sources} dataset_sources linked={linked_sources}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
