"""news-crawler enrich: the parser, the per-article loop, and every subcommand.

Everything that would touch a model or a database is replaced at the seam
enrichment.py imports it through -- ``src.enrichment.repository``,
``src.enrichment.orchestrator`` and ``src.models.database`` -- so these run
on nothing but the process. What they pin: the exit codes (0 done, 1 halted
at the spend ceiling, 2 configuration error), that --dry-run makes no call
and no write, that the ceiling is checked between articles and keeps the
committed work, and that a backfill accounts for every id it was given.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from src.cli.commands import enrichment
from src.enrichment.profiles import ConfigurationError, Profile


@dataclass
class _Article:
    id: str
    dataset_slug: str = "mo"


@dataclass
class _Outcome:
    status: str
    total_cost_usd: Decimal = Decimal("0.01")


@dataclass
class _Report:
    candidates: list
    rejected: dict = field(default_factory=dict)


class _Session:
    """Enough of a SQLAlchemy session for the status query."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return self

    def fetchall(self):
        return self.rows


class _Database:
    def __init__(self, session):
        self.session = session

    def get_session(self):
        @contextmanager
        def _cm():
            yield self.session

        return _cm()


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    enrichment.add_enrichment_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(argv)


@pytest.fixture
def db(monkeypatch):
    """A fake DatabaseManager wired in; returns the session it hands out."""
    session = _Session()
    monkeypatch.setattr(
        "src.models.database.DatabaseManager", lambda: _Database(session)
    )
    return session


# --- the parser ---------------------------------------------------------------


def test_run_has_the_documented_defaults(monkeypatch):
    monkeypatch.delenv("ENRICHMENT_CONCURRENCY", raising=False)
    args = _parse(["enrich", "run", "--dataset", "mo"])
    assert args.enrich_action == "run"
    assert args.dataset == "mo"
    assert args.limit == 200
    assert args.concurrency == 10
    assert args.dry_run is False
    assert args.func is enrichment.handle_enrichment_command


def test_concurrency_default_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("ENRICHMENT_CONCURRENCY", "3")
    assert _parse(["enrich", "run", "--dataset", "mo"]).concurrency == 3
    assert _parse(["enrich", "backfill", "--ids-file", "x"]).concurrency == 3
    assert (
        _parse(
            ["enrich", "reprocess", "--dataset", "mo", "--profile-version", "2"]
        ).concurrency
        == 3
    )


def test_every_subcommand_parses():
    assert _parse(["enrich", "status"]).dataset is None
    assert _parse(["enrich", "status", "--dataset", "vt"]).dataset == "vt"
    backfill = _parse(["enrich", "backfill", "--ids-file", "ids.txt", "--dry-run"])
    assert backfill.ids_file == "ids.txt" and backfill.dry_run
    reprocess = _parse(
        ["enrich", "reprocess", "--dataset", "mo", "--profile-version", "4"]
    )
    assert reprocess.profile_version == 4 and reprocess.limit == 200


def test_run_requires_a_dataset_and_reprocess_a_profile_version():
    with pytest.raises(SystemExit):
        _parse(["enrich", "run"])
    with pytest.raises(SystemExit):
        _parse(["enrich", "reprocess", "--dataset", "mo"])


# --- the environment knobs ----------------------------------------------------


def test_environment_knobs(monkeypatch):
    for name in (
        "ENRICHMENT_MAX_ATTEMPTS",
        "ENRICHMENT_SPEND_CEILING_USD",
        "BACKFIELD_COMMIT",
    ):
        monkeypatch.delenv(name, raising=False)
    assert enrichment._max_attempts() == 3
    assert enrichment._ceiling() is None
    assert enrichment._backfield_commit() == "unknown"

    monkeypatch.setenv("ENRICHMENT_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("ENRICHMENT_SPEND_CEILING_USD", "12.50")
    monkeypatch.setenv("BACKFIELD_COMMIT", "abc123")
    assert enrichment._max_attempts() == 5
    assert enrichment._ceiling() == Decimal("12.50")
    assert enrichment._backfield_commit() == "abc123"


# --- _process -----------------------------------------------------------------


@pytest.fixture
def seams(monkeypatch):
    """enrich_article and persist_outcome replaced; records every write."""
    monkeypatch.delenv("ENRICHMENT_SPEND_CEILING_USD", raising=False)
    monkeypatch.setenv("BACKFIELD_COMMIT", "deadbeef")
    outcomes: dict[str, _Outcome] = {}
    persisted: list[tuple[str, str, dict]] = []

    def enrich_article(article, profile, *, model, max_attempts):
        return outcomes[article.id]

    def persist_outcome(session, article, outcome, **kwargs):
        persisted.append((article.id, outcome.status, kwargs))

    monkeypatch.setattr("src.enrichment.orchestrator.enrich_article", enrich_article)
    monkeypatch.setattr("src.enrichment.repository.persist_outcome", persist_outcome)
    return outcomes, persisted


def _factory(session):
    return _Database(session).get_session


def test_process_writes_every_outcome_and_totals_the_spend(seams):
    outcomes, persisted = seams
    outcomes["a"] = _Outcome("enriched", Decimal("0.010"))
    outcomes["b"] = _Outcome("enrichment_skipped", Decimal("0.002"))
    outcomes["c"] = _Outcome("enriched", Decimal("0.010"))
    profile = Profile(version=1)

    result = enrichment._process(
        _factory(_Session()),
        [_Article("a"), _Article("b"), _Article("c")],
        profile,
        "some/model",
        concurrency=2,
    )

    assert result == {
        "counts": {"enriched": 2, "enrichment_skipped": 1},
        "spent": "0.022",
        "halted": False,
    }
    assert [(i, s) for i, s, _ in persisted] == [
        ("a", "enriched"),
        ("b", "enrichment_skipped"),
        ("c", "enriched"),
    ]
    written = persisted[0][2]
    assert written["profile"] is profile
    assert written["model"] == "some/model"
    assert written["backfield_commit"] == "deadbeef"
    assert written["prompt_versions"] == {"content_gate": "content_gate-v1"}


def test_process_halts_at_the_ceiling_after_committing_the_article(seams, monkeypatch):
    """The ceiling is checked between articles: the article that crosses it is
    written, the next one is never touched."""
    outcomes, persisted = seams
    monkeypatch.setenv("ENRICHMENT_SPEND_CEILING_USD", "0.015")
    for article_id in ("a", "b", "c"):
        outcomes[article_id] = _Outcome("enriched", Decimal("0.010"))

    result = enrichment._process(
        _factory(_Session()),
        [_Article("a"), _Article("b"), _Article("c")],
        Profile(version=1),
        "m",
        concurrency=1,
    )

    assert result["halted"] is True
    assert result["spent"] == "0.020"
    assert [i for i, _, _ in persisted] == ["a", "b"]


# --- handle_enrichment_command -----------------------------------------------


def test_status_prints_one_line_per_status(db, capsys):
    db.rows = [("enriched", 40), ("labeled", 2)]

    code = enrichment.handle_enrichment_command(
        _parse(["enrich", "status", "--dataset", "mo"])
    )

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "  enriched               40",
        "  labeled                2",
    ]
    statement, params = db.statements[0]
    assert "AND d.slug = :slug" in statement
    assert params == {"slug": "mo"}


def test_status_without_a_dataset_counts_every_dataset(db):
    enrichment.handle_enrichment_command(_parse(["enrich", "status"]))
    statement, params = db.statements[0]
    assert "d.slug" not in statement
    assert params == {}


def test_dry_run_plans_and_writes_nothing(db, monkeypatch, capsys):
    profile = Profile(version=2, scope=True)
    candidates = [_Article("a"), _Article("b")]
    monkeypatch.setattr(
        "src.enrichment.repository.dataset_profile", lambda s, slug: profile
    )
    monkeypatch.setattr(
        "src.enrichment.repository.select_candidates",
        lambda s, slug, limit, attempts: candidates,
    )

    def never(
        *args, **kwargs
    ):  # pragma: no cover - the assertion is that it is not called
        raise AssertionError("dry run must not process")

    monkeypatch.setattr(enrichment, "_process", never)

    code = enrichment.handle_enrichment_command(
        _parse(["enrich", "run", "--dataset", "mo", "--dry-run"])
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "dry run: 2 candidate(s)" in out
    assert "profile v2, steps: content_gate, scope" in out
    assert "projected cost: ~$0.0150 at $0.0075/article" in out
    assert "nothing written" in out


def test_run_processes_and_reports(db, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(
        "src.enrichment.repository.dataset_profile",
        lambda s, slug: Profile(version=1),
    )
    monkeypatch.setattr(
        "src.enrichment.repository.select_candidates",
        lambda s, slug, limit, attempts: seen.setdefault(
            "select", (slug, limit, attempts)
        )
        and [_Article("a")],
    )
    monkeypatch.setenv("ENRICHMENT_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("ENRICHMENT_MODEL", "test/model")

    def process(session_factory, articles, profile, model, concurrency):
        seen["process"] = (len(articles), model, concurrency)
        return {"counts": {"enriched": 1}, "spent": "0.01", "halted": False}

    monkeypatch.setattr(enrichment, "_process", process)

    code = enrichment.handle_enrichment_command(
        _parse(
            ["enrich", "run", "--dataset", "mo", "--limit", "7", "--concurrency", "2"]
        )
    )

    assert code == 0
    assert seen["select"] == ("mo", 7, 4)
    assert seen["process"] == (1, "test/model", 2)
    out = capsys.readouterr().out
    assert "processed: 1  spent: $0.01  halted: False" in out
    assert "  enriched               1" in out


def test_a_halted_run_exits_one(db, monkeypatch):
    monkeypatch.setattr(
        "src.enrichment.repository.dataset_profile",
        lambda s, slug: Profile(version=1),
    )
    monkeypatch.setattr(
        "src.enrichment.repository.select_candidates",
        lambda s, slug, limit, attempts: [_Article("a")],
    )
    monkeypatch.setattr(
        enrichment,
        "_process",
        lambda *a: {"counts": {"enriched": 1}, "spent": "1", "halted": True},
    )
    assert (
        enrichment.handle_enrichment_command(
            _parse(["enrich", "run", "--dataset", "mo"])
        )
        == 1
    )


def test_reprocess_refuses_a_profile_version_the_dataset_lacks(db, monkeypatch, capsys):
    monkeypatch.setattr(
        "src.enrichment.repository.dataset_profile",
        lambda s, slug: Profile(version=1),
    )

    code = enrichment.handle_enrichment_command(
        _parse(["enrich", "reprocess", "--dataset", "mo", "--profile-version", "2"])
    )

    assert code == 2
    assert "configuration error: dataset profile is v1" in capsys.readouterr().out


def test_reprocess_selects_by_status_under_the_dataset_profile(db, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "src.enrichment.repository.dataset_profile",
        lambda s, slug: Profile(version=3),
    )
    monkeypatch.setattr(
        "src.enrichment.repository.select_reprocess_candidates",
        lambda s, slug, limit, attempts: seen.setdefault("select", (slug, limit))
        and [_Article("a")],
    )
    monkeypatch.setattr(
        enrichment,
        "_process",
        lambda *a: {"counts": {"enriched": 1}, "spent": "0", "halted": False},
    )

    code = enrichment.handle_enrichment_command(
        _parse(
            [
                "enrich",
                "reprocess",
                "--dataset",
                "mo",
                "--profile-version",
                "2",
                "--limit",
                "5",
            ]
        )
    )

    assert code == 0
    assert seen["select"] == ("mo", 5)


def test_unknown_dataset_is_a_configuration_error(db, monkeypatch):
    def unknown(session, slug):
        raise ConfigurationError(f"unknown dataset: {slug}")

    monkeypatch.setattr("src.enrichment.repository.dataset_profile", unknown)
    assert (
        enrichment.handle_enrichment_command(
            _parse(["enrich", "run", "--dataset", "nope"])
        )
        == 2
    )


def test_backfill_accounts_for_every_id(db, monkeypatch, tmp_path, capsys):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("# march repair\n\naaa\nbbb\n ccc \n")
    seen = {}
    monkeypatch.setattr(
        "src.enrichment.repository.select_by_ids",
        lambda s, ids, attempts: seen.setdefault("ids", ids)
        and _Report(
            candidates=[_Article("aaa", dataset_slug="vt")],
            rejected={"ccc": "already enriched", "bbb": "not labeled"},
        ),
    )
    monkeypatch.setattr(
        "src.enrichment.repository.dataset_profile",
        lambda s, slug: seen.setdefault("profile_for", slug) and Profile(version=1),
    )
    monkeypatch.setattr(
        enrichment,
        "_process",
        lambda *a: {"counts": {"enriched": 1}, "spent": "0.01", "halted": False},
    )

    code = enrichment.handle_enrichment_command(
        _parse(["enrich", "backfill", "--ids-file", str(ids_file)])
    )

    assert code == 0
    assert seen["ids"] == ["aaa", "bbb", "ccc"]
    assert seen["profile_for"] == "vt"
    out = capsys.readouterr().out
    assert "supplied: 3  candidates: 1  rejected: 2" in out
    assert "  skip bbb: not labeled\n  skip ccc: already enriched\n" in out


def test_backfill_with_nothing_eligible_does_nothing(db, monkeypatch, tmp_path, capsys):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("aaa\n")
    monkeypatch.setattr(
        "src.enrichment.repository.select_by_ids",
        lambda s, ids, attempts: _Report(candidates=[], rejected={"aaa": "gone"}),
    )

    code = enrichment.handle_enrichment_command(
        _parse(["enrich", "backfill", "--ids-file", str(ids_file)])
    )

    assert code == 0
    assert "nothing to do" in capsys.readouterr().out
