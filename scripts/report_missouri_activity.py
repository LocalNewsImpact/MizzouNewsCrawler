#!/usr/bin/env python3
"""Report activity for a dataset (default: Missouri).

Usage: python3 scripts/report_missouri_activity.py --dataset Missouri

This script prints counts for the past 24 hours and past 1 hour for the
following events (when timestamp columns exist):
 - discovery (candidate_links.discovered_at)
 - verification (url_verifications.verified_at)
 - extraction (articles.extracted_at)
 - cleaning (APPROXIMATE: articles with status='cleaned' and recent extracted/created)
 - labeling (article_labels.applied_at)

Notes / assumptions:
 - The database schema doesn't include an explicit `cleaned_at` timestamp on
   `articles`. This script approximates cleaning activity by counting articles
   with status='cleaned' whose `extracted_at` or `created_at` falls in the
   window. If you have a stronger signal (a cleaned_at column or telemetry),
   modify the query accordingly.
 - The script uses the project's DatabaseManager which will use the Cloud SQL
   Python Connector if `USE_CLOUD_SQL_CONNECTOR` and `CLOUD_SQL_INSTANCE` are
   configured in the environment. Run this in Cloud Shell or on a host with
   proper credentials.
"""

from datetime import datetime, timedelta, timezone
import argparse
import os
import sys

from src.models.database import DatabaseManager
from sqlalchemy import text


def run_report(dataset_id: str):
    db = DatabaseManager()  # honors CLOUD_SQL_INSTANCE env / project config

    now = datetime.now(timezone.utc)
    windows = {
        "24h": now - timedelta(hours=24),
        "1h": now - timedelta(hours=1),
    }

    queries = {
        "discovered": (
            "SELECT COUNT(*) FROM candidate_links cl "
            "WHERE cl.dataset_id = :dataset AND cl.discovered_at >= :since"
        ),
        "verified": (
            "SELECT COUNT(*) FROM url_verifications uv "
            "JOIN candidate_links cl on uv.candidate_link_id = cl.id "
            "WHERE cl.dataset_id = :dataset AND uv.verified_at >= :since"
        ),
        "extracted": (
            "SELECT COUNT(*) FROM articles a "
            "JOIN candidate_links cl on a.candidate_link_id = cl.id "
            "WHERE cl.dataset_id = :dataset AND a.extracted_at >= :since"
        ),
        # cleaning is approximated since there's no explicit cleaned_at in schema
        "cleaned_approx": (
            "SELECT COUNT(*) FROM articles a "
            "JOIN candidate_links cl on a.candidate_link_id = cl.id "
            "WHERE cl.dataset_id = :dataset AND a.status = 'cleaned' "
            "AND (COALESCE(a.extracted_at, a.created_at) >= :since)"
        ),
        "labeled": (
            "SELECT COUNT(*) FROM article_labels al "
            "JOIN articles a on al.article_id = a.id "
            "JOIN candidate_links cl on a.candidate_link_id = cl.id "
            "WHERE cl.dataset_id = :dataset AND al.applied_at >= :since"
        ),
    }

    results = {w: {} for w in windows}

    try:
        with db.get_session() as session:
            for label, q in queries.items():
                for wname, since in windows.items():
                    r = session.execute(text(q), {"dataset": dataset_id, "since": since}).scalar()
                    results[wname][label] = int(r or 0)
    finally:
        db.close()

    # Print nicely
    print(f"Activity report for dataset='{dataset_id}' (UTC now={now.isoformat()})\n")
    for wname in ["24h", "1h"]:
        print(f"=== Past {wname} ===")
        print(f" Discovered: {results[wname].get('discovered', 0):,}")
        print(f" Verified:   {results[wname].get('verified', 0):,}")
        print(f" Extracted:  {results[wname].get('extracted', 0):,}")
        print(f" Cleaned*:   {results[wname].get('cleaned_approx', 0):,}  (approx)")
        print(f" Labeled:    {results[wname].get('labeled', 0):,}\n")

    print("* 'Cleaned' is approximated: if you have a dedicated cleaned_at timestamp, replace the query with that column to get exact results.")


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument(
        "--dataset",
        "-d",
        default="Missouri",
        help="dataset_id to filter by (default: Missouri)",
    )
    p.add_argument(
        "--cloud-sql-instance",
        dest="cloud_sql_instance",
        help=(
            "Cloud SQL instance in the form project:region:instance. "
            "If provided, the script will attempt to use the Cloud SQL Python Connector."
        ),
    )
    p.add_argument(
        "--use-cloud-sql-connector",
        dest="use_connector",
        action="store_true",
        help=("Force use of Cloud SQL Python Connector (requires ADC or gcloud credentials)."),
    )

    args = p.parse_args(argv)

    # If user passed Cloud SQL instance or requested connector, export
    # environment variables so DatabaseManager will use the connector.
    if args.cloud_sql_instance:
        os.environ.setdefault("CLOUD_SQL_INSTANCE", args.cloud_sql_instance)
    if args.use_connector:
        os.environ.setdefault("USE_CLOUD_SQL_CONNECTOR", "1")

    # If running locally and CLOUD_SQL_INSTANCE is present, default to using
    # the connector so authenticated CLI users don't need to pass credentials.
    if not os.getenv("KUBERNETES_SERVICE_HOST") and os.getenv("CLOUD_SQL_INSTANCE"):
        os.environ.setdefault("USE_CLOUD_SQL_CONNECTOR", os.environ.get("USE_CLOUD_SQL_CONNECTOR", "1"))

    run_report(args.dataset)


if __name__ == "__main__":
    main(sys.argv[1:])
