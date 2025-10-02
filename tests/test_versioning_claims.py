import os
import sys
from pathlib import Path

# Make `src` importable when tests run from the project root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

try:
    from models import versioning
except Exception as e:  # pragma: no cover - skip in minimal envs
    pytest.skip(
        f"Skipping versioning tests; can't import models: {e}",
        allow_module_level=True)


def _make_db_path(tmpdir_path: str) -> str:
    path = os.path.join(tmpdir_path, "test_mizzou.db")
    return f"sqlite:///{path}"


def test_claim_succeeds_first_try(tmp_path):
    db_url = _make_db_path(str(tmp_path))
    versioning.create_versioning_tables(database_url=db_url)

    # create a dataset version
    dv = versioning.create_dataset_version(
        "testset",
        "v1",
        created_by_job="job-a",
        database_url=db_url,
    )

    claimed = versioning.claim_dataset_version(
        dv.id, claimer="job-a", database_url=db_url
    )

    assert claimed is True


def test_claim_fails_if_already_claimed(tmp_path):
    db_url = _make_db_path(str(tmp_path))
    versioning.create_versioning_tables(database_url=db_url)

    dv = versioning.create_dataset_version(
        "testset",
        "v2",
        created_by_job="job-a",
        database_url=db_url,
    )

    # first claim
    first = versioning.claim_dataset_version(
        dv.id, claimer="job-a", database_url=db_url
    )
    assert first is True

    # second claim should fail
    second = versioning.claim_dataset_version(
        dv.id, claimer="job-b", database_url=db_url
    )
    assert second is False


def test_finalize_updates_metadata_and_status(tmp_path):
    db_url = _make_db_path(str(tmp_path))
    versioning.create_versioning_tables(database_url=db_url)

    dv = versioning.create_dataset_version(
        "testset",
        "v3",
        created_by_job="job-a",
        database_url=db_url,
    )

    # claim then finalize
    assert versioning.claim_dataset_version(
        dv.id, claimer="job-a", database_url=db_url)

    # create a small temp file to act as snapshot
    fp = Path(tmp_path) / "snap.parquet"
    fp.write_text("dummycontent")

    finalized = versioning.finalize_dataset_version(
        dv.id,
        snapshot_path=str(fp),
        row_count=123,
        checksum="deadbeef",
        succeeded=True,
        database_url=db_url,
    )

    assert finalized.status == "ready"
    assert finalized.snapshot_path == str(fp)
    assert finalized.row_count == 123
    assert finalized.checksum == "deadbeef"
