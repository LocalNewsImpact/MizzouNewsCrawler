"""Backfill script to create `datasets` and `sources` and populate candidate_links.source_id/dataset_id.

Usage:
    python scripts/backfill_sources.py --db data/mizzou.db --slug publinks-2025-09 --name "publinks.csv import"

The script makes a backup copy of the DB before mutating it.
"""

import argparse
import shutil
import sqlite3
import uuid
from datetime import datetime
from urllib.parse import urlparse

DB_COPY_SUFFIX = ".backfill.copy"


def ensure_tables(conn):
    cur = conn.cursor()
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS datasets (
        id VARCHAR PRIMARY KEY,
        slug VARCHAR UNIQUE,
        label VARCHAR UNIQUE,
        name VARCHAR,
        description TEXT,
        ingested_at DATETIME,
        ingested_by VARCHAR,
        metadata JSON,
        is_public BOOLEAN
    );
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS sources (
        id VARCHAR PRIMARY KEY,
        host VARCHAR,
        canonical_name VARCHAR,
        city VARCHAR,
        county VARCHAR,
        owner VARCHAR,
        type VARCHAR,
        metadata JSON
    );
    """
    )

    # Add dataset_id and source_id to candidate_links if missing
    cur.execute("PRAGMA table_info(candidate_links);")
    cols = [r[1] for r in cur.fetchall()]
    if "dataset_id" not in cols:
        cur.execute("ALTER TABLE candidate_links ADD COLUMN dataset_id VARCHAR;")
        print("Added dataset_id column to candidate_links")
    if "source_id" not in cols:
        cur.execute("ALTER TABLE candidate_links ADD COLUMN source_id VARCHAR;")
        print("Added source_id column to candidate_links")
    conn.commit()


def make_dataset(conn, slug, name, ingested_by=None):
    cur = conn.cursor()
    dataset_id = str(uuid.uuid4())
    # If a dataset with the same slug or name exists, return its id to avoid
    # creating duplicates.
    cur.execute(
        "SELECT id FROM datasets WHERE slug = ? OR label = ? LIMIT 1",
        (slug, name),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # Insert with label if possible (label column present is handled by schema)
    try:
        cur.execute(
            (
                "INSERT INTO datasets (id, slug, label, name, ingested_at, "
                "ingested_by) VALUES (?, ?, ?, ?, ?, ?)"
            ),
            (
                dataset_id,
                slug,
                name,
                name,
                datetime.utcnow().isoformat(),
                ingested_by,
            ),
        )
    except sqlite3.OperationalError:
        # Fallback if label column missing.
        cur.execute(
            (
                "INSERT INTO datasets (id, slug, name, ingested_at, "
                "ingested_by) VALUES (?, ?, ?, ?, ?)"
            ),
            (
                dataset_id,
                slug,
                name,
                datetime.utcnow().isoformat(),
                ingested_by,
            ),
        )
    conn.commit()
    return dataset_id


def extract_host(value):
    if not value:
        return None
    # try treating value as a host first
    if "/" not in value and "." in value:
        return value.lower()
    try:
        parsed = urlparse(value)
        return (parsed.netloc or parsed.path).lower()
    except Exception:
        return value.lower()


def build_sources(conn):
    cur = conn.cursor()
    # get distinct candidate links hosts from source_host_id and url
    cur.execute(
        "SELECT DISTINCT source_host_id FROM candidate_links "
        "WHERE source_host_id IS NOT NULL AND source_host_id != '';"
    )
    rows = cur.fetchall()
    hosts = set(r[0] for r in rows if r[0])

    # also try to extract hosts from `url` where source_host_id missing
    cur.execute(
        "SELECT DISTINCT url FROM candidate_links "
        "WHERE (source_host_id IS NULL OR source_host_id = '') "
        "AND url IS NOT NULL;"
    )
    for (u,) in cur.fetchall():
        h = extract_host(u)
        if h:
            hosts.add(h)

    print(f"Found {len(hosts)} distinct hosts to create sources for")

    # Insert sources and return mapping host->id
    host_to_id = {}
    for host in sorted(hosts):
        source_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO sources (id, host, canonical_name) VALUES (?, ?, ?)",
            (source_id, host, host),
        )
        host_to_id[host] = source_id
    conn.commit()
    return host_to_id


def apply_source_ids(conn, host_to_id, dry_run=False):
    cur = conn.cursor()
    total = 0
    for host, sid in host_to_id.items():
        # Update candidate_links where exact match on source_host_id.
        cur.execute(
            "UPDATE candidate_links SET source_id = ? " "WHERE source_host_id = ?",
            (sid, host),
        )
        total += cur.rowcount
        # Also update where `url` contains the host when `source_host_id` was
        # missing or empty.
        cur.execute(
            "UPDATE candidate_links SET source_id = ? "
            "WHERE (source_host_id IS NULL OR source_host_id = '') "
            "AND url LIKE ?",
            (sid, "%" + host + "%"),
        )
        total += cur.rowcount
    if not dry_run:
        conn.commit()
    return total


def apply_dataset_id(conn, dataset_id, where_clause=None):
    cur = conn.cursor()
    if where_clause:
        q = f"UPDATE candidate_links SET dataset_id = ? WHERE {where_clause}"
        cur.execute(q, (dataset_id,))
    else:
        cur.execute("UPDATE candidate_links SET dataset_id = ?", (dataset_id,))
    conn.commit()
    return cur.rowcount


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/mizzou.db")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--ingested-by")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--where",
        help=(
            "Optional SQL WHERE clause to restrict dataset assignment "
            "(no leading WHERE)"
        ),
    )
    args = parser.parse_args()

    src_db = args.db
    backup_db = src_db + DB_COPY_SUFFIX

    print(f"Backing up DB {src_db} -> {backup_db}")
    shutil.copy2(src_db, backup_db)

    conn = sqlite3.connect(backup_db)
    try:
        ensure_tables(conn)

        dataset_id = make_dataset(
            conn, args.slug, args.name, ingested_by=args.ingested_by
        )
        print(f"Created dataset id {dataset_id}")

        host_to_id = build_sources(conn)
        print(f"Creating {len(host_to_id)} source rows")

        updated = apply_source_ids(conn, host_to_id, dry_run=args.dry_run)
        print(f"Updated {updated} candidate_links with source_id")

        changed = apply_dataset_id(conn, dataset_id, where_clause=args.where)
        print(f"Updated {changed} candidate_links with dataset_id")

        print(
            "Backfill complete on DB copy. Original DB left untouched at:",
            src_db,
        )
        print("If results look good, replace the original DB with the copy")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
