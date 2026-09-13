"""The sync queries BigQuery is actually running, read from the service.

The only way to catch a change made in the BigQuery console.

Two failures that must not be confused, because conflating them either
makes CI permanently red or hides real drift:

  COULD NOT READ    no `bq`, no credentials, no network. Says nothing about
                    the warehouse. Raises `TransfersUnavailable` so a caller
                    can SKIP -- visibly, never silently passing.
  READ AND EMPTY    reached the service and it reported no configs. That is
                    not agreement, and it raises.

The pre-push hook found this the hard way: it runs on a scratch worktree
with no credentials, the read failed, and the audit test FAILED rather than
skipping -- which would have left every push and every CI run red.
"""

from __future__ import annotations

import json
import subprocess

LOCATION = "us"
PROJECT = "mizzou-news-crawler"


class TransfersUnavailable(RuntimeError):
    """BigQuery could not be read. Not a statement about the warehouse."""


def _run(args: list[str]) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=180)
    except FileNotFoundError as missing:  # bq not installed
        raise TransfersUnavailable(f"{args[0]} is not installed") from missing
    except subprocess.TimeoutExpired as slow:
        raise TransfersUnavailable(f"{args[0]} timed out") from slow
    if done.returncode != 0:
        # Every non-zero exit is treated as "could not read". Guessing which
        # stderr strings mean "unauthenticated" would be a list to maintain,
        # and being wrong in that direction turns an environment problem into
        # a permanently red build.
        raise TransfersUnavailable(
            f"{' '.join(args)} failed: {done.stderr.strip()[:300] or '(no stderr)'}"
        )
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
        # Reached the service and it reported nothing. That is a real finding,
        # not an unavailable environment, so it does NOT skip.
        raise RuntimeError("no scheduled queries found; refusing to report agreement")
    return queries
