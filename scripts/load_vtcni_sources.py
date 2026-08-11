#!/usr/bin/env python3
"""Load the VT Community News (VTCNI) sources CSV into datasets/sources/dataset_sources.

Same shape and the same reasoning as ``load_washington_sources.py`` -- raw SQL
rather than the ORM, and no candidate-link enqueue, because the CSV carries
homepages and discovery is what finds the stories.

Two things are specific to this dataset:

``name`` is provisional for most rows. The list arrived as bare URLs with no
publication names, so ``name_source`` records where each name came from:
``og:site_name``/``application-name``/``twitter:site``/``title-segment``/
``logo-alt`` mean a real masthead was read off the page, while
``domain-fallback`` means nobody has confirmed it and the value is just the
domain title-cased ("Fordhamobserver"). Those are placeholders to be corrected
from what discovery captures, not names to publish. The column is carried into
source metadata so a later pass can find them without re-deriving.

Re-running is the supported way to fix them: rows match on ``sources.host_norm``,
so correcting names in the CSV and re-running updates this dataset in place.

**A source already owned by another dataset is linked, never rewritten.** Five
of these hosts are also Missouri sources with hand-curated names, cities,
counties and owners (``themaneater.com`` -> "The Maneater", Columbia, Boone).
This CSV carries no geography at all and a provisional name for most rows, so
letting it UPDATE those rows -- which is what the Washington loader this was
copied from does -- would replace "The Maneater" with "Themaneater" and blank
the rest. It has nothing to contribute to a curated row, so it does not try;
it only adds the dataset link. Even for rows this dataset does own, empty CSV
values are never written over existing ones, and a confirmed name is never
replaced by a provisional one.

Two entries were removed from the raw list before it became this CSV:
``medium.com`` and ``youtube.com``, which are platform roots rather than
publications -- loading them as sources would aim discovery at those entire
sites. The 26 remaining platform-hosted rows (``*.wordpress.com``,
``*.weebly.com``, ``*.wixsite.com``) are real student newsrooms and are kept.

The CSV itself is not in git -- ``.gitignore`` excludes ``*.csv`` with a short
allowlist, and the Washington sources CSV is untracked for the same reason. It
lives at ``sources/vtcni_sources.csv``, built from the VTCNI "productive sites"
URL list (bare URLs, no names) plus the name-detection described above.

Run inside a pod per the repo's DB access protocol::

    kubectl cp scripts/load_vtcni_sources.py production/<cli-pod>:/app/load_vtcni_sources.py
    kubectl cp sources/vtcni_sources.csv production/<cli-pod>:/app/vtcni_sources.csv
    kubectl exec -n production <cli-pod> -- python /app/load_vtcni_sources.py \
        --csv /app/vtcni_sources.csv [--commit]

Then discovery runs against it through the normal production path::

    python -m src.cli discover-urls --dataset "VT Community News" --force-all
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

# `--dataset` on discover-urls matches datasets.label, not the slug.
DATASET_SLUG = "VT-Community-News"
DATASET_LABEL = "VT Community News"
DATASET_NAME = "VT Community News Initiative Sources"
DATASET_DESCRIPTION = (
    "Student-produced and university-affiliated community news outlets tracked "
    "by the VT Community News Initiative: the 'productive' site list, i.e. "
    "outlets observed to be publishing."
)

# Anything else in this column means a masthead was read off the live page.
PLACEHOLDER_NAME_SOURCE = "domain-fallback"


def _source_fields(row: dict, host: str, host_norm: str) -> dict:
    """Map a CSV row onto the sources columns.

    ``name_source`` and ``name_is_provisional`` ride along in metadata so the
    follow-up pass can select exactly the rows whose names still need
    confirming, without re-deriving which ones those were.
    """
    name_source = row.get("name_source", "") or ""
    return {
        "host": host,
        "host_norm": host_norm,
        "canonical_name": row["name"],
        "city": row.get("city", ""),
        "county": row.get("county", ""),
        "owner": row.get("owner", ""),
        "type": row.get("media_type", "unknown"),
        "metadata": json.dumps(
            {
                "address1": row.get("address1", ""),
                "address2": row.get("address2", ""),
                "state": row.get("State", ""),
                "zip": str(row.get("zip", "") or ""),
                "frequency": row.get("frequency", ""),
                "media_type": row.get("media_type", ""),
                "cohort": row.get("cohort", ""),
                "source": row.get("source", ""),
                "name_source": name_source,
                "name_is_provisional": name_source == PLACEHOLDER_NAME_SOURCE,
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
    with open(args.csv, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("ERROR: CSV is empty", file=sys.stderr)
        return 1

    provisional = sum(
        1 for r in rows if r.get("name_source") == PLACEHOLDER_NAME_SOURCE
    )
    print(f"{len(rows)} rows; {provisional} carry a provisional (domain-derived) name")

    db = DatabaseManager()
    created_sources = 0
    linked_sources = 0
    existing_sources = 0
    skipped_updates = 0

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
                        "ingested_by": "load_vtcni_sources",
                        "metadata": json.dumps(
                            {
                                "source_file": args.csv,
                                "total_rows": len(rows),
                                "provisional_names": provisional,
                            }
                        ),
                        "is_public": False,
                        "cron_enabled": False,
                    },
                )

        for row in rows:
            host = row["url_news"].split("//", 1)[1].strip("/")
            host_norm = host.lower()

            fields = _source_fields(row, host, host_norm)

            existing = session.execute(
                text("""
                    SELECT s.id,
                           s.canonical_name,
                           EXISTS (
                               SELECT 1 FROM dataset_sources ds
                               WHERE ds.source_id = s.id
                                 AND ds.dataset_id <> :dataset_id
                           ) AS owned_elsewhere
                    FROM sources s
                    WHERE s.host_norm = :h
                    """),
                {"h": host_norm, "dataset_id": dataset_id},
            ).one_or_none()

            source_id = existing[0] if existing else None
            provisional_row = row.get("name_source") == PLACEHOLDER_NAME_SOURCE
            flag = "?" if provisional_row else " "

            if source_id:
                existing_sources += 1
                current_name, owned_elsewhere = existing[1], existing[2]

                if owned_elsewhere:
                    # Another dataset curated this row. Link it in; touch nothing.
                    skipped_updates += 1
                    print(
                        f"  LINK   {flag} {host_norm:<38} "
                        f"keeping {current_name!r} (owned by another dataset)"
                    )
                elif provisional_row and current_name:
                    skipped_updates += 1
                    print(
                        f"  LINK   {flag} {host_norm:<38} "
                        f"keeping {current_name!r} (ours is provisional)"
                    )
                else:
                    print(f"  UPDATE {flag} {host_norm:<38} {row['name']}")
                    if args.commit:
                        # COALESCE(NULLIF(...)) so a blank CSV cell leaves the
                        # stored value alone rather than erasing it.
                        session.execute(
                            text("""
                                UPDATE sources
                                SET canonical_name = :canonical_name,
                                    city = COALESCE(NULLIF(:city, ''), city),
                                    county = COALESCE(NULLIF(:county, ''), county),
                                    owner = COALESCE(NULLIF(:owner, ''), owner),
                                    type = COALESCE(NULLIF(:type, ''), type),
                                    metadata = CAST(:metadata AS JSON)
                                WHERE id = :id
                                """),
                            {**fields, "id": source_id},
                        )
            else:
                source_id = str(uuid.uuid4())
                created_sources += 1
                print(f"  CREATE {flag} {host_norm:<38} {row['name']}")
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
    # Report rows actually rewritten, not rows that merely already existed --
    # the two differ by every row this script deliberately left alone.
    print(
        f"\n{verb} sources created={created_sources} "
        f"updated={existing_sources - skipped_updates} "
        f"left-alone={skipped_updates} linked={linked_sources}"
    )
    print(
        f"'?' marks a provisional name ({provisional} rows) to fix after discovery; "
        f"{skipped_updates} existing sources were linked without being rewritten"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
