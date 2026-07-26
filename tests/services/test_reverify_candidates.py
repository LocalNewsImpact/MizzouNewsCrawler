"""Unit tests for backlog re-verification (reverify_candidates et al.).

Postgres integration coverage lives in
tests/integration/test_reverify_candidates_postgres.py.
"""

from unittest.mock import Mock

import pytest

from src.services import url_verification


def _service() -> url_verification.URLVerificationService:
    return url_verification.URLVerificationService(
        batch_size=100,
        http_backoff_seconds=0,
        run_http_precheck=False,
    )


class TestDecideStatus:
    def test_error_maps_to_uncertain_without_precheck(self) -> None:
        service = _service()
        status, error = service.decide_status(
            {"error": "boom", "storysniffer_result": None}
        )
        assert status == "verification_uncertain"
        assert error == "boom"

    def test_error_maps_to_failed_with_precheck(self) -> None:
        service = url_verification.URLVerificationService(
            http_backoff_seconds=0, run_http_precheck=True
        )
        status, _ = service.decide_status(
            {"error": "boom", "storysniffer_result": None}
        )
        assert status == "verification_failed"

    def test_wire_beats_everything_else(self) -> None:
        service = _service()
        status, error = service.decide_status(
            {"wire_filtered": True, "storysniffer_result": True}
        )
        assert status == "wire"
        assert error is None

    def test_pattern_status_used_when_pattern_filtered(self) -> None:
        service = _service()
        status, _ = service.decide_status(
            {"pattern_filtered": True, "pattern_status": "obituary"}
        )
        assert status == "obituary"

    def test_sniffer_true_is_article(self) -> None:
        service = _service()
        status, _ = service.decide_status({"storysniffer_result": True})
        assert status == "article"

    def test_default_is_not_article(self) -> None:
        service = _service()
        status, _ = service.decide_status({"storysniffer_result": False})
        assert status == "not_article"


class TestReverifyCandidates:
    def test_junk_is_reclassified_and_updated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _service()
        updates: list[tuple] = []
        monkeypatch.setattr(
            service,
            "update_candidate_status",
            lambda cid, status, err=None: updates.append((cid, status)),
        )
        monkeypatch.setattr(
            service,
            "verify_url",
            lambda url: {
                "pattern_filtered": True,
                "pattern_status": "not_article",
            },
        )

        metrics = service.reverify_candidates(
            [{"id": "c1", "url": "https://x.com/scripts/junk.php", "status": "article"}]
        )

        assert metrics["total"] == 1
        assert metrics["kept"] == 0
        assert metrics["reclassified"] == {"not_article": 1}
        assert updates == [("c1", "not_article")]

    def test_still_article_is_kept_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _service()
        update_mock = Mock()
        monkeypatch.setattr(service, "update_candidate_status", update_mock)
        monkeypatch.setattr(
            service, "verify_url", lambda url: {"storysniffer_result": True}
        )

        metrics = service.reverify_candidates(
            [{"id": "c1", "url": "https://x.com/real-story", "status": "article"}]
        )

        assert metrics["kept"] == 1
        assert metrics["reclassified"] == {}
        update_mock.assert_not_called()

    def test_verification_error_leaves_row_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient verify error must never demote an existing row."""
        service = _service()
        update_mock = Mock()
        monkeypatch.setattr(service, "update_candidate_status", update_mock)
        monkeypatch.setattr(
            service,
            "verify_url",
            lambda url: {"error": "sniffer exploded", "storysniffer_result": None},
        )

        metrics = service.reverify_candidates(
            [{"id": "c1", "url": "https://x.com/a", "status": "article"}]
        )

        assert metrics["errors"] == 1
        assert metrics["kept"] == 0
        assert metrics["reclassified"] == {}
        update_mock.assert_not_called()

    def test_dry_run_reports_without_updating(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _service()
        update_mock = Mock()
        monkeypatch.setattr(service, "update_candidate_status", update_mock)
        monkeypatch.setattr(
            service,
            "verify_url",
            lambda url: {"wire_filtered": True},
        )

        metrics = service.reverify_candidates(
            [{"id": "c1", "url": "https://x.com/ap-wire", "status": "article"}],
            dry_run=True,
        )

        assert metrics["reclassified"] == {"wire": 1}
        update_mock.assert_not_called()

    def test_mixed_batch_counts_are_correct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _service()
        monkeypatch.setattr(service, "update_candidate_status", lambda *a, **k: None)
        results = {
            "https://x.com/keep": {"storysniffer_result": True},
            "https://x.com/wire": {"wire_filtered": True},
            "https://x.com/junk": {
                "pattern_filtered": True,
                "pattern_status": "not_article",
            },
        }
        monkeypatch.setattr(service, "verify_url", lambda url: results[url])

        metrics = service.reverify_candidates(
            [
                {"id": "1", "url": "https://x.com/keep", "status": "article"},
                {"id": "2", "url": "https://x.com/wire", "status": "article"},
                {"id": "3", "url": "https://x.com/junk", "status": "article"},
            ]
        )

        assert metrics["total"] == 3
        assert metrics["kept"] == 1
        assert metrics["reclassified"] == {"wire": 1, "not_article": 1}
        assert metrics["errors"] == 0
