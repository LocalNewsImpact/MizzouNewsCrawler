from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.dashboard import seed_dashboard_telemetry


@pytest.fixture()
def dashboard_fixture(tmp_path: Path):
    fixture = seed_dashboard_telemetry(tmp_path, async_writes=False)
    try:
        yield fixture
    finally:
        fixture.flush()


def _patch_dashboard_paths(monkeypatch: pytest.MonkeyPatch, fixture) -> None:
    from backend.app import main as app_main

    monkeypatch.setattr(app_main, "DB_PATH", fixture.db_path)
    monkeypatch.setattr(app_main, "MAIN_DB_PATH", fixture.db_path)
    monkeypatch.setattr(app_main, "ARTICLES_CSV", fixture.csv_path)


def test_ui_overview_highlights_dashboard_failures(
    dashboard_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import main as app_main

    _patch_dashboard_paths(monkeypatch, dashboard_fixture)

    result = app_main.ui_overview()

    assert result["total_articles"] == 2
    assert result["wire_count"] == 1
    assert result["candidate_issues"] == 2
    assert result["dedupe_near_misses"] == 1


def test_http_errors_surface_verification_outages(
    dashboard_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import main as app_main

    _patch_dashboard_paths(monkeypatch, dashboard_fixture)

    payload = app_main.get_http_errors(days=7, status_code=429)
    errors = payload["http_errors"]

    verification_rows = [row for row in errors if row["host"] == "verification.local"]
    assert verification_rows, "expected verification.local to appear in outage alerts"
    assert verification_rows[0]["error_count"] == 2


def test_domain_issues_group_by_host(
    dashboard_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import main as app_main

    _patch_dashboard_paths(monkeypatch, dashboard_fixture)

    issues = app_main.get_domain_issues()

    assert set(issues) == {"broken.local"}
    broken = issues["broken.local"]
    assert broken["total_urls"] == 2
    assert broken["issues"] == {"title": 1, "description": 1}
