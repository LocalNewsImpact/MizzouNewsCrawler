"""A curated link to audio, video or a PDF is held before extraction.

Decided 2026-10-15: "we can not extract or enrich video and audio files".
check-ingested records every rule and model doubt about a curated URL for a
person to judge, and the link is still fetched. A MEDIA doubt is different --
nothing can be extracted from the file -- so that link is set to `not_article`
before a worker fetches it. ptleader.com/audio-articles/player/... was fetched
about once a minute in the WSU credentialed run because nothing held it.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from src.services.url_verification import URLVerificationService
from tests.test_an_ingested_url_is_checked_not_filtered import _harness
from tests.test_the_backlog_of_decisions_can_be_reviewed import _Row


def _result(kind, status="not_article", **extra):
    return {
        "pattern_filtered": True,
        "pattern_type": kind,
        "pattern_status": status,
        "storysniffer_result": False,
        **extra,
    }


class TestWhatIsHeld:
    @pytest.mark.parametrize(
        "kind",
        [
            "audio",
            "video",
            "videos",
            "video_gallery",
            "pdf",
            "pdf_path",
            "asset_extension",
        ],
    )
    def test_a_media_rule_holds(self, kind):
        assert URLVerificationService.ingest_hold(_result(kind)) == kind

    @pytest.mark.parametrize("kind", ["section", "tag", "newsletter", "opinion"])
    def test_another_rule_is_only_a_doubt(self, kind):
        assert URLVerificationService.ingest_hold(_result(kind)) is None

    def test_storysniffer_alone_holds_nothing(self):
        assert (
            URLVerificationService.ingest_hold({"storysniffer_result": False}) is None
        )

    def test_a_rule_that_admits_holds_nothing(self):
        assert URLVerificationService.ingest_hold(_result("video", "article")) is None

    def test_an_error_holds_nothing(self):
        assert URLVerificationService.ingest_hold(_result("audio", error="x")) is None


class _Session:
    """Answers the harness's select with the rows; records the hold."""

    def __init__(self, rows):
        self.rows = rows
        self.statements: list[tuple[str, dict]] = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        if "SET status = 'not_article'" in sql:
            self.statements.append((sql, params or {}))
        return self

    def fetchall(self):
        return self.rows

    def commit(self):
        self.commits += 1


def _run(monkeypatch, status, kind="audio"):
    url = "https://ptleader.com/audio-articles/player/audio-article-242225"
    rows = [_Row("c1", url, status)]
    svc, written = _harness(monkeypatch, rows)
    monkeypatch.setattr(svc, "verify_url", lambda u: _result(kind))
    session = _Session(rows)

    @contextmanager
    def get_session():
        yield session

    monkeypatch.setattr(svc.db, "get_session", get_session)
    counts = svc.check_ingested()
    return counts, written, session


class TestTheHoldIsWritten:
    def test_an_unfetched_media_link_is_set_to_not_article(self, monkeypatch):
        counts, written, session = _run(monkeypatch, "article")
        assert counts["held"] == 1
        (row,) = written
        assert row.new_status == "not_article"
        sql, params = session.statements[-1]
        assert "SET status = 'not_article'" in sql
        assert params == {"id": "c1", "reason": "ingested URL is audio, not an article"}
        assert session.commits == 1

    def test_the_update_cannot_touch_a_link_with_an_article(self, monkeypatch):
        _, _, session = _run(monkeypatch, "article")
        sql = " ".join(session.statements[-1][0].split())
        assert "cl.status IN ('discovered', 'article')" in sql
        assert "NOT EXISTS ( SELECT 1 FROM articles a" in sql

    def test_a_link_with_an_outcome_keeps_it(self, monkeypatch):
        counts, written, session = _run(monkeypatch, "extracted")
        assert counts["held"] == 0
        assert written[0].new_status == "extracted"
        assert session.statements == []

    def test_a_dry_run_holds_nothing(self, monkeypatch):
        url = "https://ptleader.com/audio-articles/player/audio-article-242225"
        svc, written = _harness(monkeypatch, [_Row("c1", url, "article")])
        monkeypatch.setattr(svc, "verify_url", lambda u: _result("audio"))
        counts = svc.check_ingested(dry_run=True)
        assert counts["held"] == 1
        assert written == []


@pytest.fixture(scope="module")
def yaml():
    return pytest.importorskip("yaml")


@pytest.mark.parametrize(
    "path, template",
    [
        ("k8s/argo/dataset-extraction-workflow.yaml", "extract-dataset"),
        ("k8s/argo/authenticated-extraction-workflow.yaml", "extract-credentialed"),
    ],
)
class TestItRunsBeforeExtraction:
    def _first(self, yaml, path, template):
        spec = yaml.safe_load(Path(path).read_text())
        (tmpl,) = [t for t in spec["spec"]["templates"] if t["name"] == template]
        (first,) = tmpl["steps"][0]
        return first, tmpl

    def test_it_is_the_first_step(self, yaml, path, template):
        first, _ = self._first(yaml, path, template)
        assert first["name"] == "check-ingested"
        assert first["templateRef"] == {
            "name": "housekeeping-template",
            "template": "check-ingested-step",
        }

    def test_it_is_scoped_to_the_runs_dataset(self, yaml, path, template):
        first, _ = self._first(yaml, path, template)
        (param,) = first["arguments"]["parameters"]
        assert param == {"name": "dataset", "value": "{{inputs.parameters.dataset}}"}

    def test_a_failed_check_cannot_stop_extraction(self, yaml, path, template):
        first, _ = self._first(yaml, path, template)
        assert first["continueOn"] == {"failed": True}

    def test_extraction_follows_it(self, yaml, path, template):
        _, tmpl = self._first(yaml, path, template)
        assert tmpl["steps"][1][0]["name"] == "extract"
