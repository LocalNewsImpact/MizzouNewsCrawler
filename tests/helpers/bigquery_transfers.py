"""The sync queries BigQuery is actually running, read from the service.

The only way to catch a change made in the BigQuery console. Raises rather
than returning a partial answer: a check that silently sees three of eleven
configs would pass while the other eight drifted.
"""

from __future__ import annotations

import json
import subprocess

LOCATION = "us"
PROJECT = "mizzou-news-crawler"


def _run(args: list[str]) -> str:
    done = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {done.stderr.strip()[:300]}")
    return done.stdout


def deployed_sync_queries() -> dict[str, str]:
    """Destination table -> the SQL its scheduled query runs."""
    listed = json.loads(
        _run(
            [
                "bq",
                "ls",
                "--transfer_config",
                f"--transfer_location={LOCATION}",
                "--format=json",
                "--max_results=200",
            ]
        )
        or "[]"
    )
    queries: dict[str, str] = {}
    for config in listed:
        name = config.get("name", "")
        if not name:
            continue
        shown = json.loads(
            _run(["bq", "show", "--transfer_config", "--format=json", name])
        )
        params = shown.get("params", {})
        table = params.get("destination_table_name_template")
        query = params.get("query")
        if table and query:
            queries[table] = query
    if not queries:
        raise RuntimeError("no scheduled queries found; refusing to report agreement")
    return queries
