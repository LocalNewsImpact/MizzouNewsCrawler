from __future__ import annotations

import hashlib
from pathlib import Path


import pytest
from sqlalchemy import text

from src.models import create_database_engine
from src.models.versioning import (
    _compute_advisory_lock_id,
    _compute_file_checksum,
    _fsync_path,
    claim_dataset_version,
    create_dataset_version,
    create_versioning_tables,
    export_dataset_version,
    export_snapshot_for_version,
    finalize_dataset_version,
    list_dataset_versions,
)


@pytest.fixture()
def sqlite_db_url(tmp_path: Path) -> str:
    db_path = tmp_path / "versioning.db"
    return f"sqlite:///{db_path}"


@pytest.fixture()
def ensure_tables(sqlite_db_url: str) -> str:
    create_versioning_tables(sqlite_db_url)
    return sqlite_db_url


def test_create_claim_and_finalize_dataset_version(
    ensure_tables: str,
    tmp_path: Path,
):
    db_url = ensure_tables
    snapshot_path = tmp_path / "snapshot.parquet"

    version = create_dataset_version(
        dataset_name="articles",
        version_tag="2025-10-01",
        description="daily export",
        database_url=db_url,
    )

    assert str(version.status) == "pending"
    assert str(version.dataset_name) == "articles"

    assert claim_dataset_version(
        str(version.id),
        claimer="worker-1",
        database_url=db_url,
    )
    assert not claim_dataset_version(
        str(version.id),
        claimer="worker-2",
        database_url=db_url,
    )

    finalized = finalize_dataset_version(
        str(version.id),
        snapshot_path=str(snapshot_path),
        row_count=5,
        checksum="abc123",
        database_url=db_url,
    )

    assert str(finalized.status) == "ready"
    assert finalized.row_count == 5  # type: ignore[comparison-overlap]
    assert str(finalized.checksum) == "abc123"
    assert str(finalized.snapshot_path) == str(snapshot_path)


def test_finalize_unknown_version_raises(ensure_tables: str):
    with pytest.raises(ValueError, match="DatasetVersion not found"):
        finalize_dataset_version("missing", database_url=ensure_tables)


def test_export_dataset_version_without_snapshot(ensure_tables: str):
    db_url = ensure_tables
    version = create_dataset_version(
        dataset_name="news",
        version_tag="v1",
        database_url=db_url,
    )

    with pytest.raises(NotImplementedError):
        export_dataset_version(
            str(version.id),
            "/tmp/output.parquet",
            database_url=db_url,
        )


def test_export_dataset_version_copies_snapshot(
    ensure_tables: str,
    tmp_path: Path,
):
    db_url = ensure_tables
    source = tmp_path / "source.parquet"
    source.write_text("payload")

    version = create_dataset_version(
        dataset_name="news",
        version_tag="v1",
        database_url=db_url,
    )
    finalize_dataset_version(
        version.id,
        snapshot_path=str(source),
        database_url=db_url,
    )

    destination = tmp_path / "export.parquet"
    returned = export_dataset_version(
        str(version.id),
        str(destination),
        database_url=db_url,
    )

    assert returned == str(destination)
    assert destination.read_text() == "payload"


def test_compute_helpers(tmp_path: Path):
    file_path = tmp_path / "data.bin"
    file_path.write_bytes(b"newsroom")

    expected = hashlib.sha256(b"newsroom").hexdigest()
    assert _compute_file_checksum(str(file_path)) == expected

    _fsync_path(str(file_path))  # Should not raise

    value = _compute_advisory_lock_id("dataset", "v1")
    assert value == _compute_advisory_lock_id("dataset", "v1")
    assert 0 <= value < 2**63


def test_export_snapshot_for_version_pandas_fallback(
    monkeypatch: pytest.MonkeyPatch,
    ensure_tables: str,
    tmp_path: Path,
):
    db_url = ensure_tables
    engine = create_database_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE snapshot_source (id INTEGER, value TEXT)"))

    version = create_dataset_version(
        dataset_name="news",
        version_tag="v2",
        created_by_job="snapshotter",
        database_url=db_url,
    )

    # Force pandas fallback path
    import src.models.versioning as versioning_module

    monkeypatch.setattr(versioning_module, "_HAS_PYARROW", False)

    class FakeFrame:
        def __len__(self) -> int:
            return 2

        def to_parquet(
            self,
            path: str,
            index: bool = False,
            compression: str | None = None,
        ) -> None:  # noqa: ARG002
            Path(path).write_text("fake-parquet")

    def fake_read_sql_table(
        table_name: str,
        con: object,
    ) -> FakeFrame:  # noqa: ARG001
        assert table_name == "snapshot_source"
        return FakeFrame()

    monkeypatch.setattr(
        versioning_module.pd,
        "read_sql_table",
        fake_read_sql_table,
    )

    output_path = tmp_path / "snapshot.parquet"
    result_path = export_snapshot_for_version(
        str(version.id),
        "snapshot_source",
        str(output_path),
        database_url=db_url,
        compression=None,
        chunksize=1,
    )

    assert result_path == str(output_path)
    assert output_path.read_text() == "fake-parquet"

    # Inspect stored version record
    versions = list_dataset_versions(database_url=db_url)
    assert len(versions) == 1
    stored = versions[0]
    assert str(stored.status) == "ready"
    # SQLite may return numeric types that are coercible to int
    assert int(stored.row_count) == 2  # type: ignore[arg-type]
    assert str(stored.snapshot_path) == str(output_path)
    assert stored.checksum is not None
