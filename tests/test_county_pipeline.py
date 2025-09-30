import logging
import runpy
import sys
from pathlib import Path

import pytest

from src.models import CandidateLink
from src.models.database import DatabaseManager


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


def test_orchestrate_pipeline_logs_skip_when_queue_empty(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    def fake_run_cli_step(*_args, **_kwargs):
        return None

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)
    monkeypatch.setattr(
        county_pipeline,
        "_get_candidate_queue_counts",
        lambda: {"discovered": 0, "article": 0},
    )

    county_pipeline.orchestrate_pipeline(
        counties=["Boone"],
        dataset=None,
        source_limit=None,
        max_articles=5,
        days_back=7,
        force_all=False,
        verification_batch_size=1,
        verification_batches=None,
        verification_sleep=0,
        skip_verification=False,
        extraction_limit=1,
        extraction_batches=1,
        skip_extraction=True,
        dry_run=True,
        cli_module="src.cli.cli_modular",
        skip_analysis=True,
        analysis_limit=None,
        analysis_batch_size=1,
        analysis_top_k=2,
        analysis_label_version=None,
        analysis_statuses=None,
        analysis_dry_run=False,
    )

    assert "No candidate links with status 'discovered'" in caplog.text


def test_orchestrate_pipeline_bubbles_verification_failure(monkeypatch):
    calls: list[str] = []

    def fake_run_cli_step(label, args, *, cli_base, dry_run, env=None):
        calls.append(label)
        if label == "Verification service":
            raise county_pipeline.PipelineError("verification failed")

    queue_counts = [
        {"discovered": 2, "article": 0},
    ]

    def fake_queue_counts():
        if queue_counts:
            return queue_counts.pop(0)
        return {"discovered": 0, "article": 0}

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)
    monkeypatch.setattr(
        county_pipeline,
        "_get_candidate_queue_counts",
        fake_queue_counts,
    )

    with pytest.raises(county_pipeline.PipelineError):
        county_pipeline.orchestrate_pipeline(
            counties=["Boone"],
            dataset=None,
            source_limit=None,
            max_articles=5,
            days_back=7,
            force_all=False,
            verification_batch_size=5,
            verification_batches=None,
            verification_sleep=0,
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

    assert calls == [
        "Discovery for county Boone",
        "Verification service",
    ]


def test_orchestrate_pipeline_bubbles_extraction_failure(monkeypatch):
    calls: list[str] = []

    def fake_run_cli_step(label, args, *, cli_base, dry_run, env=None):
        calls.append(label)
        if label == "Article extraction":
            raise county_pipeline.PipelineError("extraction failed")

    queue_counts = [
        {"discovered": 1, "article": 0},
        {"discovered": 0, "article": 2},
    ]

    def fake_queue_counts():
        if queue_counts:
            return queue_counts.pop(0)
        return {"discovered": 0, "article": 0}

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)
    monkeypatch.setattr(
        county_pipeline,
        "_get_candidate_queue_counts",
        fake_queue_counts,
    )

    with pytest.raises(county_pipeline.PipelineError):
        county_pipeline.orchestrate_pipeline(
            counties=["Boone"],
            dataset=None,
            source_limit=None,
            max_articles=5,
            days_back=7,
            force_all=False,
            verification_batch_size=1,
            verification_batches=None,
            verification_sleep=0,
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

    assert calls == [
        "Discovery for county Boone",
        "Verification service",
        "Article extraction",
    ]


def test_orchestrate_pipeline_bubbles_analysis_failure(monkeypatch):
    calls: list[str] = []

    def fake_run_cli_step(label, args, *, cli_base, dry_run, env=None):
        calls.append(label)
        if label == "ML analysis":
            raise county_pipeline.PipelineError("analysis failed")

    queue_counts = [
        {"discovered": 1, "article": 0},
        {"discovered": 0, "article": 2},
    ]

    def fake_queue_counts():
        if queue_counts:
            return queue_counts.pop(0)
        return {"discovered": 0, "article": 0}

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)
    monkeypatch.setattr(
        county_pipeline,
        "_get_candidate_queue_counts",
        fake_queue_counts,
    )

    with pytest.raises(county_pipeline.PipelineError):
        county_pipeline.orchestrate_pipeline(
            counties=["Boone"],
            dataset=None,
            source_limit=None,
            max_articles=5,
            days_back=7,
            force_all=False,
            verification_batch_size=1,
            verification_batches=None,
            verification_sleep=0,
            skip_verification=False,
            extraction_limit=1,
            extraction_batches=1,
            skip_extraction=False,
            dry_run=False,
            cli_module="src.cli.cli_modular",
            skip_analysis=False,
            analysis_limit=5,
            analysis_batch_size=2,
            analysis_top_k=2,
            analysis_label_version="v1",
            analysis_statuses=["article"],
            analysis_dry_run=False,
        )

    assert calls == [
        "Discovery for county Boone",
        "Verification service",
        "Article extraction",
        "ML analysis",
    ]


def test_run_cli_step_dry_run_skips_execution(monkeypatch):
    def fake_run(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError(
            "subprocess.run should not be called during dry run"
        )

    monkeypatch.setattr(county_pipeline.subprocess, "run", fake_run)

    county_pipeline._run_cli_step(
        "Dry run discovery",
        ["discover-urls", "--county", "Boone"],
        cli_base=[sys.executable, "-m", "src.cli.cli_modular"],
        dry_run=True,
    )


def test_run_cli_step_invokes_subprocess(monkeypatch, tmp_path):
    commands = []

    def fake_run(cmd, cwd=None, env=None, check=None):
        commands.append((cmd, cwd, env, check))

        class Result:
            def __init__(self) -> None:
                self.returncode = 0

        return Result()

    monkeypatch.setattr(county_pipeline.subprocess, "run", fake_run)

    county_pipeline._run_cli_step(
        "Verification service",
        ["verify-urls", "--batch-size", "1"],
        cli_base=[sys.executable, "-m", "src.cli.cli_modular"],
        dry_run=False,
        env={"PYTHONPATH": str(tmp_path)},
    )

    assert commands
    cmd, cwd, env, check = commands[0]
    assert cmd == [
        sys.executable,
        "-m",
        "src.cli.cli_modular",
        "verify-urls",
        "--batch-size",
        "1",
    ]
    assert cwd == county_pipeline.PROJECT_ROOT
    assert env == {"PYTHONPATH": str(tmp_path)}
    assert check is False


def test_run_cli_step_raises_on_failure(monkeypatch):
    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(cmd, cwd=None, env=None, check=None):  # pragma: no cover
        return Result(returncode=5)

    monkeypatch.setattr(county_pipeline.subprocess, "run", fake_run)

    with pytest.raises(county_pipeline.PipelineError) as excinfo:
        county_pipeline._run_cli_step(
            "Analysis",
            ["analyze"],
            cli_base=[sys.executable, "-m", "src.cli.cli_modular"],
            dry_run=False,
        )

    assert "exit code 5" in str(excinfo.value)


def test_get_candidate_queue_counts_returns_counts(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'queue-counts.db'}"
    setup_manager = DatabaseManager(database_url=db_url)
    setup_session = setup_manager.session
    setup_session.add_all(
        [
            CandidateLink(
                id="cand-discovered",
                url="https://example.com/discovered",
                source="Example Source",
                status="discovered",
            ),
            CandidateLink(
                id="cand-article",
                url="https://example.com/article",
                source="Example Source",
                status="article",
            ),
        ]
    )
    setup_session.commit()
    setup_session.close()
    setup_manager.close()

    def manager_factory(*_args, **_kwargs):
        return DatabaseManager(database_url=db_url)

    monkeypatch.setattr(county_pipeline, "DatabaseManager", manager_factory)

    counts = county_pipeline._get_candidate_queue_counts()

    assert counts["discovered"] == 1
    assert counts["article"] == 1


def test_orchestrate_pipeline_success_runs_all_steps(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'orchestration-success.db'}"
    setup_manager = DatabaseManager(database_url=db_url)
    setup_session = setup_manager.session
    setup_session.add_all(
        [
            CandidateLink(
                id="cand-1",
                url="https://example.com/story-1",
                source="Example Source",
                status="discovered",
            ),
            CandidateLink(
                id="cand-2",
                url="https://example.com/story-2",
                source="Example Source",
                status="discovered",
            ),
            CandidateLink(
                id="cand-3",
                url="https://example.com/story-3",
                source="Example Source",
                status="discovered",
            ),
            CandidateLink(
                id="cand-article",
                url="https://example.com/story-4",
                source="Example Source",
                status="article",
            ),
        ]
    )
    setup_session.commit()
    setup_session.close()
    setup_manager.close()

    def manager_factory(*_args, **_kwargs):
        return DatabaseManager(database_url=db_url)

    monkeypatch.setattr(county_pipeline, "DatabaseManager", manager_factory)

    executed_commands = []

    def fake_run(cmd, cwd=None, env=None, check=None):
        executed_commands.append(cmd)

        class Result:
            def __init__(self) -> None:
                self.returncode = 0

        return Result()

    monkeypatch.setattr(county_pipeline.subprocess, "run", fake_run)

    county_pipeline.orchestrate_pipeline(
        counties=["Boone"],
        dataset="smoke-test",
        source_limit=5,
        max_articles=10,
        days_back=3,
        force_all=True,
        verification_batch_size=3,
        verification_batches=None,
        verification_sleep=0,
        skip_verification=False,
        extraction_limit=2,
        extraction_batches=2,
        skip_extraction=False,
        dry_run=False,
        cli_module="src.cli.cli_modular",
        skip_analysis=False,
        analysis_limit=7,
        analysis_batch_size=4,
        analysis_top_k=3,
        analysis_label_version="beta",
        analysis_statuses=["article_ready", "verified"],
        analysis_dry_run=True,
    )

    assert [cmd[3] for cmd in executed_commands] == [
        "discover-urls",
        "verify-urls",
        "extract",
        "analyze",
    ]

    discovery_cmd = executed_commands[0]
    assert "--force-all" in discovery_cmd
    assert "--source-limit" in discovery_cmd
    assert "--dataset" in discovery_cmd

    verification_cmd = executed_commands[1]
    batch_index = verification_cmd.index("--batch-size")
    assert verification_cmd[batch_index + 1] == "1"
    max_batches_index = verification_cmd.index("--max-batches")
    assert verification_cmd[max_batches_index + 1] == "3"

    extraction_cmd = executed_commands[2]
    assert extraction_cmd.count("--limit") == 1
    assert extraction_cmd[extraction_cmd.index("--batches") + 1] == "2"

    analysis_cmd = executed_commands[3]
    assert analysis_cmd[analysis_cmd.index("--limit") + 1] == "7"
    assert "--dry-run" in analysis_cmd
    statuses_index = analysis_cmd.index("--statuses")
    assert analysis_cmd[statuses_index + 1:statuses_index + 3] == [
        "article_ready",
        "verified",
    ]


def test_parse_args_handles_all_flags():
    args = county_pipeline._parse_args(
        [
            "--counties",
            "Boone",
            "Cole",
            "--dataset",
            "smoke",
            "--source-limit",
            "5",
            "--max-articles",
            "10",
            "--days-back",
            "3",
            "--force-all",
            "--verification-batch-size",
            "4",
            "--verification-batches",
            "6",
            "--verification-sleep",
            "2",
            "--skip-verification",
            "--extraction-limit",
            "7",
            "--extraction-batches",
            "8",
            "--skip-extraction",
            "--skip-analysis",
            "--analysis-limit",
            "9",
            "--analysis-batch-size",
            "11",
            "--analysis-top-k",
            "4",
            "--analysis-label-version",
            "beta",
            "--analysis-statuses",
            "verified",
            "article_ready",
            "--analysis-dry-run",
            "--dry-run",
            "--cli-module",
            "custom.module",
            "--legacy-cli",
            "--log-level",
            "DEBUG",
        ]
    )

    assert args.counties == ["Boone", "Cole"]
    assert args.dataset == "smoke"
    assert args.source_limit == 5
    assert args.max_articles == 10
    assert args.days_back == 3
    assert args.force_all is True
    assert args.verification_batch_size == 4
    assert args.verification_batches == 6
    assert args.verification_sleep == 2
    assert args.skip_verification is True
    assert args.extraction_limit == 7
    assert args.extraction_batches == 8
    assert args.skip_extraction is True
    assert args.skip_analysis is True
    assert args.analysis_limit == 9
    assert args.analysis_batch_size == 11
    assert args.analysis_top_k == 4
    assert args.analysis_label_version == "beta"
    assert args.analysis_statuses == ["verified", "article_ready"]
    assert args.analysis_dry_run is True
    assert args.dry_run is True
    assert args.cli_module == "custom.module"
    assert args.legacy_cli is True
    assert args.log_level == "DEBUG"


def test_main_returns_zero_with_legacy_cli(monkeypatch):
    captured_kwargs = {}

    def fake_orchestrate_pipeline(**kwargs):
        captured_kwargs.update(kwargs)

    monkeypatch.setattr(
        county_pipeline,
        "orchestrate_pipeline",
        fake_orchestrate_pipeline,
    )

    exit_code = county_pipeline.main(
        [
            "--counties",
            "Boone",
            "--legacy-cli",
            "--dry-run",
            "--log-level",
            "ERROR",
        ]
    )

    assert exit_code == 0
    assert captured_kwargs["dry_run"] is True
    assert captured_kwargs["cli_module"] == county_pipeline.LEGACY_CLI_MODULE


def test_main_returns_one_on_pipeline_error(monkeypatch):
    def fake_orchestrate_pipeline(**_kwargs):
        raise county_pipeline.PipelineError("boom")

    monkeypatch.setattr(
        county_pipeline,
        "orchestrate_pipeline",
        fake_orchestrate_pipeline,
    )

    exit_code = county_pipeline.main(["--counties", "Boone", "--dry-run"])

    assert exit_code == 1


def test_main_returns_one_on_keyboard_interrupt(monkeypatch):
    def fake_orchestrate_pipeline(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        county_pipeline,
        "orchestrate_pipeline",
        fake_orchestrate_pipeline,
    )

    exit_code = county_pipeline.main(["--counties", "Boone", "--dry-run"])

    assert exit_code == 1


def test_module_entrypoint_executes_main(monkeypatch):
    class FakeSession:
        def execute(self, *_args, **_kwargs):
            return []

        def close(self) -> None:
            return None

    class FakeManager:
        def __init__(self, *args, **kwargs) -> None:
            self.session = FakeSession()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "src.models.database.DatabaseManager",
        FakeManager,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "county_pipeline.py",
            "--counties",
            "Boone",
            "--dry-run",
            "--skip-verification",
            "--skip-extraction",
            "--skip-analysis",
        ],
    )

    monkeypatch.delitem(
        sys.modules,
        "orchestration.county_pipeline",
        raising=False,
    )

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("orchestration.county_pipeline", run_name="__main__")

    assert excinfo.value.code == 0
