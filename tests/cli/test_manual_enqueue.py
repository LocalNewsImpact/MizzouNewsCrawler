"""Tests for the manual enqueue helper script."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import manual_enqueue_urls
from src.models import CandidateLink, Dataset
from src.models.database import DatabaseManager


class _TestDatabaseManager(DatabaseManager):
    """DatabaseManager subclass that forces a test database URL."""

    def __init__(self, database_url: str) -> None:
        super().__init__(database_url=database_url)


@pytest.fixture()
def test_db_url(tmp_path: Path) -> str:
    db_path = tmp_path / "manual_test.sqlite"
    return f"sqlite:///{db_path}"


@pytest.fixture()
def patch_database_manager(monkeypatch: pytest.MonkeyPatch, test_db_url: str):
    def _factory():
        return _TestDatabaseManager(database_url=test_db_url)

    monkeypatch.setattr(manual_enqueue_urls, "DatabaseManager", _factory)
    yield


def _write_urls_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "urls.txt"
    file_path.write_text("https://example.com/article-1\n")
    return file_path


def test_enqueue_creates_dataset_when_missing(
    tmp_path: Path, test_db_url: str, patch_database_manager
):
    input_path = _write_urls_file(tmp_path)

    inserted = manual_enqueue_urls.enqueue_urls(
        input_path=input_path,
        status="discovered",
        discovered_by="manual-test",
        priority=5,
        dataset_id=None,
        dataset_label="Manual Batch",
        column=None,
        metadata_flag=False,
        dry_run=False,
    )

    assert inserted == 1

    with _TestDatabaseManager(database_url=test_db_url) as db:
        session = db.session
        datasets = session.query(Dataset).all()
        assert len(datasets) == 1
        dataset = datasets[0]

        candidate = session.query(CandidateLink).one()
        assert str(candidate.dataset_id) == str(dataset.id)


def test_enqueue_reuses_existing_dataset(
    tmp_path: Path, test_db_url: str, patch_database_manager
):
    with _TestDatabaseManager(database_url=test_db_url) as db:
        session = db.session
        dataset = Dataset(
            slug="manual-existing",
            label="Existing",
            name="Existing",
        )
        session.add(dataset)
        session.flush()
        dataset_id = str(dataset.id)
        session.commit()

    input_path = _write_urls_file(tmp_path)

    inserted = manual_enqueue_urls.enqueue_urls(
        input_path=input_path,
        status="discovered",
        discovered_by="manual-test",
        priority=5,
        dataset_id=dataset_id,
        dataset_label=None,
        column=None,
        metadata_flag=False,
        dry_run=False,
    )

    assert inserted == 1

    with _TestDatabaseManager(database_url=test_db_url) as db:
        session = db.session
        datasets = session.query(Dataset).all()
        assert len(datasets) == 1
        candidate = session.query(CandidateLink).one()
        assert str(candidate.dataset_id) == dataset_id
