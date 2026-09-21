"""An ingested URL is checked, and the check changes nothing about it.

Ingested URLs skip URL verification so that no rule or model can remove a URL
a person chose. That also meant nothing looked at them: KHQ's `/video_` pages
and ptleader's e-edition viewers came in through the WSU tracker and were
fetched, stored and filed before anything read the URL.

Decided 2026-09-21: run the URL rules and storysniffer over them, record the
answer, send a doubt to a person -- and still fetch. The external wire check
stays off for them.

Measured on the 2,681 WSU ingested links, dry run: 27 flagged.
"""

from __future__ import annotations

import inspect

import pytest

from src.services.url_verification import URLVerificationService
from tests.test_the_backlog_of_decisions_can_be_reviewed import (
    _Row,
    _rows,
    _service,
    _Sniffer,
)


def _harness(monkeypatch, rows, sniffer=None):
    svc = _service(sniffer or _Sniffer())
    _rows(svc, rows, monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )
    return svc, written


class TestTheFlag:
    @pytest.mark.parametrize(
        "result, expected",
        [
            (
                {
                    "pattern_filtered": True,
                    "pattern_status": "not_article",
                    "pattern_type": "eedition_viewer",
                },
                "pattern:eedition_viewer",
            ),
            (
                {
                    "pattern_filtered": True,
                    "pattern_status": None,
                    "pattern_type": None,
                },
                "pattern:unknown",
            ),
            ({"wire_filtered": True}, "wire_url"),
            ({"storysniffer_result": False}, "storysniffer_no"),
        ],
    )
    def test_a_doubt_names_its_mechanism(self, result, expected):
        assert URLVerificationService.ingest_flag(result) == expected

    def test_a_rule_that_admits_is_not_a_doubt(self):
        result = {"pattern_filtered": True, "pattern_status": "article"}
        assert URLVerificationService.ingest_flag(result) is None

    def test_a_story_is_not_a_doubt(self):
        assert URLVerificationService.ingest_flag({"storysniffer_result": True}) is None

    def test_an_error_is_not_a_doubt(self):
        """Nothing was learned, so there is nothing for a person to judge."""
        result = {"error": "timeout", "storysniffer_result": False}
        assert URLVerificationService.ingest_flag(result) is None

    def test_the_rule_outranks_the_model(self):
        """The same order `process_batch` decides in."""
        result = {
            "pattern_filtered": True,
            "pattern_status": "not_article",
            "pattern_type": "profile",
            "storysniffer_result": False,
        }
        assert URLVerificationService.ingest_flag(result) == "pattern:profile"


class TestWhatIsWritten:
    def test_a_doubted_url_is_flagged_for_review(self, monkeypatch):
        url = (
            "https://www.khq.com/news/x/video_2b995642-3400-4000-8000-000000000000.html"
        )
        svc, written = _harness(
            monkeypatch,
            [_Row("c1", url, "article")],
            sniffer=_Sniffer(answers={url: False}),
        )
        counts = svc.check_ingested()
        (row,) = written
        assert row.meta["verdict_kind"] == "ingested"
        assert row.meta["flagged"] is True
        assert row.meta["flag_reason"] == "storysniffer_no"
        assert counts["flagged"] == 1

    def test_an_unremarkable_url_is_recorded_unflagged(self, monkeypatch):
        """Every ingested link gets a row, so 'checked, fine' and 'never
        checked' are different in the data."""
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/news/council-votes", "article")]
        )
        svc.check_ingested()
        (row,) = written
        assert row.meta["flagged"] is False
        assert row.meta["flag_reason"] is None

    def test_the_link_status_is_recorded_unchanged(self, monkeypatch):
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/x", "extracted")]
        )
        svc.check_ingested()
        assert written[0].previous_status == "extracted"
        assert written[0].new_status == "extracted"

    def test_it_never_writes_the_link_status(self, monkeypatch):
        """Still fetched: that is the decision. A status write here is a
        filter by another name."""
        url = "https://a.example/x"
        svc, _ = _harness(
            monkeypatch, [_Row("c1", url, "article")], sniffer=_Sniffer(default=False)
        )
        calls = []
        monkeypatch.setattr(
            svc, "update_candidate_status", lambda *a, **k: calls.append(a)
        )
        svc.check_ingested()
        assert calls == []

    def test_it_makes_no_request(self, monkeypatch):
        """storysniffer is local; the session raises on any request."""
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/x", "article")]
        )
        svc.check_ingested()
        assert len(written) == 1

    def test_a_dry_run_writes_nothing(self, monkeypatch):
        svc, written = _harness(
            monkeypatch,
            [_Row("c1", "https://a.example/x", "article")],
            sniffer=_Sniffer(default=False),
        )
        counts = svc.check_ingested(dry_run=True)
        assert written == []
        assert counts["considered"] == 1
        assert counts["flagged"] == 1

    def test_the_dataset_comes_from_the_row(self, monkeypatch):
        svc, written = _harness(
            monkeypatch,
            [_Row("c1", "https://a.example/x", "article", dataset_id="wsu")],
        )
        svc.check_ingested()
        assert written[0].dataset_id == "wsu"


class TestTheSelection:
    def _select(self):
        source = inspect.getsource(URLVerificationService.check_ingested)
        return source[source.index("SELECT cl.id") : source.index("params: dict")]

    def test_only_ingested_links(self):
        assert "WHERE cl.is_curated" in self._select()

    def test_a_link_is_checked_once(self):
        """An `ingested` row already there means it has been checked. Any
        other verification row -- a backfill, a prescore -- does not."""
        select = self._select()
        assert "NOT EXISTS" in select
        assert ":ingested_marker" in select

    def test_the_wire_check_is_not_part_of_it(self):
        """It stays off for ingested URLs (2026-09-20)."""
        source = inspect.getsource(URLVerificationService.check_ingested)
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        assert "mediacloud" not in code.lower().split('"""')[-1]


def test_the_cli_offers_it():
    from pathlib import Path

    source = Path("src/cli/commands/ingest_check.py").read_text()
    assert "def add_check_ingested_parser" in source
    assert '"--dry-run"' in source
    registry = Path("src/cli/cli_modular.py").read_text()
    assert '"check-ingested": "handle_ingest_check_command"' in registry
    assert '"check-ingested": "ingest_check"' in registry


class TestItRunsWithHousekeeping:
    @pytest.fixture(scope="class")
    def housekeeping(self):
        from pathlib import Path

        yaml = pytest.importorskip("yaml")
        spec = yaml.safe_load(Path("k8s/argo/housekeeping-workflow.yaml").read_text())
        return {t["name"]: t for t in spec["spec"]["templates"]}

    def _step(self, housekeeping):
        for group in housekeeping["housekeeping"]["steps"]:
            for step in group:
                if step["name"] == "check-ingested":
                    return step
        raise AssertionError("no check-ingested step")

    def test_it_is_a_step(self, housekeeping):
        assert self._step(housekeeping)["template"] == "check-ingested-step"

    def test_a_failure_cannot_stop_the_run(self, housekeeping):
        """Steps are sequential; a failed step stops the list."""
        assert self._step(housekeeping)["continueOn"] == {"failed": True}

    def test_it_runs_the_command(self, housekeeping):
        command = housekeeping["check-ingested-step"]["container"]["command"]
        assert command[-1] == "check-ingested"
