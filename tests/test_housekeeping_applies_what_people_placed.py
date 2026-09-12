"""Geography a person put in has to reach BigQuery, and this is the only
thing that carries it.

`article_geoids` is what BigQuery reads: the scheduled query "Sync
Article Geoids from Cloud SQL" is `SELECT * FROM article_geoids`, daily
at 07:00 UTC, with no filter of its own. Nothing else writes a human row
there -- the merge inside `persist_outcome` is reachable only through
`select_by_ids`, which rejects anything whose status is not 'labeled',
and the review queue exists for articles enrichment has already finished
with.

So if this invocation is dropped from the housekeeping job, reviewers go
on placing stories, the maps go on drawing them, and BigQuery silently
never hears about any of it. Nothing would fail; the rows would just not
be there.
"""

import re
from pathlib import Path

import pytest

CRONJOB = Path(__file__).resolve().parent.parent / "k8s" / "housekeeping-cronjob.yaml"


@pytest.fixture(scope="module")
def manifest():
    return CRONJOB.read_text()


def test_the_daily_job_applies_reviewed_geography(manifest):
    assert "enrich apply-manual" in manifest, (
        "the housekeeping job no longer applies reviewed geography; "
        "contributions will reach the maps and never BigQuery"
    )


def test_it_runs_through_the_modular_cli(manifest):
    """`src.cli.main` is a deprecated forwarder. Invoked through it the
    command produced no output and exited 0 -- a silent no-op that looks
    exactly like a successful run with nothing to do."""
    line = next(ln for ln in manifest.splitlines() if "enrich apply-manual" in ln)
    assert "src.cli.cli_modular" in line, line.strip()


def test_it_runs_before_the_bigquery_sync(manifest):
    """07:00 UTC is when BigQuery reads the table. A job scheduled after
    that applies a contribution a full day late, which is dangerously
    close to looking like it works."""
    schedule = re.search(r'schedule:\s*"([^"]+)"', manifest)
    assert schedule, "the housekeeping job has no schedule"
    minute, hour = schedule.group(1).split()[:2]
    assert hour.isdigit() and minute.isdigit(), schedule.group(1)
    assert int(hour) < 7, (
        f"housekeeping runs at {hour}:{minute} UTC, at or after the 07:00 "
        "BigQuery sync, so a contribution waits a day"
    )


def test_a_failure_there_fails_the_job(manifest):
    """`set -e`. A sync that quietly stops carrying the rows is worse
    than one that stops loudly: the maps keep working, so nobody looks."""
    assert "set -e" in manifest


def test_the_command_it_runs_is_one_the_cli_declares():
    """A manifest can name a verb the CLI does not have, and nothing
    catches it until 02:00."""
    import argparse

    from src.cli.commands.enrichment import add_enrichment_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_enrichment_parser(subparsers)
    args = parser.parse_args(["enrich", "apply-manual", "--dry-run"])
    assert args.enrich_action == "apply-manual"
    assert args.dry_run is True
    # And the filters the manifest could grow later.
    args = parser.parse_args(
        ["enrich", "apply-manual", "--dataset", "mo", "--since", "2026-03-01"]
    )
    assert (args.dataset, args.since) == ("mo", "2026-03-01")
