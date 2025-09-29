import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from orchestration import county_pipeline  # noqa: E402


def test_orchestrate_pipeline_forces_verification_batch_size(monkeypatch):
    captured_calls = []

    def fake_run_cli_step(label, args, *, cli_base, dry_run, env=None):
        captured_calls.append((label, list(args)))

    queue_counts = [
        {"discovered": 1, "article": 0},
        {"discovered": 0, "article": 0},
    ]

    def fake_queue_counts():
        return queue_counts.pop(0)

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)
    monkeypatch.setattr(
        county_pipeline,
        "_get_candidate_queue_counts",
        fake_queue_counts,
    )

    county_pipeline.orchestrate_pipeline(
        counties=["Boone"],
        dataset=None,
        source_limit=None,
        max_articles=10,
        days_back=7,
        force_all=False,
        verification_batch_size=99,
        verification_batches=None,
        verification_sleep=5,
        skip_verification=False,
        extraction_limit=5,
        extraction_batches=1,
        skip_extraction=True,
        dry_run=False,
        cli_module="src.cli.cli_modular",
        skip_analysis=True,
        analysis_limit=None,
        analysis_batch_size=16,
        analysis_top_k=2,
        analysis_label_version=None,
        analysis_statuses=None,
        analysis_dry_run=False,
    )

    verification_calls = [
        call for call in captured_calls if call[0] == "Verification service"
    ]
    assert verification_calls, "Verification step should have been triggered"

    _, verify_args = verification_calls[0]
    batch_flag_index = verify_args.index("--batch-size")
    forced_value = verify_args[batch_flag_index + 1]

    assert forced_value == str(county_pipeline.FORCED_VERIFICATION_BATCH_SIZE)

    max_batches_index = verify_args.index("--max-batches")
    max_batches_value = verify_args[max_batches_index + 1]

    assert max_batches_value == "1"


def test_orchestrate_pipeline_raises_on_multi_county_failure(monkeypatch):
    calls = []

    def fake_run_cli_step(label, args, *, cli_base, dry_run, env=None):
        calls.append(label)
        if label == "Discovery for county Osage":
            raise county_pipeline.PipelineError("boom")

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)

    with pytest.raises(county_pipeline.PipelineError):
        county_pipeline.orchestrate_pipeline(
            counties=["Boone", "Osage"],
            dataset=None,
            source_limit=None,
            max_articles=5,
            days_back=7,
            force_all=False,
            verification_batch_size=1,
            verification_batches=None,
            verification_sleep=1,
            skip_verification=True,
            extraction_limit=1,
            extraction_batches=1,
            skip_extraction=True,
            dry_run=False,
            cli_module="src.cli.cli_modular",
            skip_analysis=True,
            analysis_limit=None,
            analysis_batch_size=1,
            analysis_top_k=2,
            analysis_label_version=None,
            analysis_statuses=None,
            analysis_dry_run=False,
        )

    assert calls == [
        "Discovery for county Boone",
        "Discovery for county Osage",
    ]


def test_orchestrate_pipeline_skips_extraction_when_verification_exhausted(
    monkeypatch,
):
    calls = []

    def fake_run_cli_step(label, args, *, cli_base, dry_run, env=None):
        calls.append(label)

    queue_counts = [
        {"discovered": 2, "article": 0},
        {"discovered": 1, "article": 0},
    ]

    def fake_queue_counts():
        return queue_counts.pop(0)

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)
    monkeypatch.setattr(
        county_pipeline,
        "_get_candidate_queue_counts",
        fake_queue_counts,
    )

    county_pipeline.orchestrate_pipeline(
        counties=["Boone"],
        dataset=None,
        source_limit=None,
        max_articles=5,
        days_back=7,
        force_all=False,
        verification_batch_size=1,
        verification_batches=3,
        verification_sleep=1,
        skip_verification=False,
        extraction_limit=1,
        extraction_batches=1,
        skip_extraction=False,
        dry_run=False,
        cli_module="src.cli.cli_modular",
        skip_analysis=True,
        analysis_limit=None,
        analysis_batch_size=1,
        analysis_top_k=2,
        analysis_label_version=None,
        analysis_statuses=None,
        analysis_dry_run=False,
    )

    assert "Verification service" in calls
    assert "Article extraction" not in calls
