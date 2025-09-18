import sys
import time
import multiprocessing as mp
from pathlib import Path
import os
import pytest

# Ensure src is importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from models import versioning
except Exception as e:  # pragma: no cover - skip in minimal envs
    pytest.skip(f"Skipping concurrency tests; can't import models: {e}", allow_module_level=True)


def _make_db_path(tmpdir_path: str) -> str:
    path = os.path.join(tmpdir_path, "concurrent_mizzou.db")
    return f"sqlite:///{path}"


def _worker_attempt_claim(db_url: str, dv_id: str, claimer: str, out_q: mp.Queue):
    # Each worker gets its own import & DB session
    try:
        # Re-import inside child process to ensure fresh engine/session
        from models import versioning as v
        ok = v.claim_dataset_version(dv_id, claimer=claimer, database_url=db_url)
        out_q.put((claimer, bool(ok)))
    except Exception as e:
        out_q.put((claimer, False, str(e)))


def test_concurrent_claims(tmp_path):
    db_url = _make_db_path(str(tmp_path))

    # Create DB and a version
    versioning.create_versioning_tables(database_url=db_url)
    dv = versioning.create_dataset_version("concurrent", "v1", created_by_job="init", database_url=db_url)

    # Spawn multiple processes attempting to claim the same dv
    q = mp.Queue()
    workers = []
    n = 6
    for i in range(n):
        p = mp.Process(target=_worker_attempt_claim, args=(db_url, dv.id, f"proc-{i}", q))
        workers.append(p)
        p.start()

    results = []
    for _ in range(n):
        results.append(q.get(timeout=5))

    for p in workers:
        p.join(timeout=1)

    # Count successes
    successes = [r for r in results if len(r) >= 2 and r[1] is True]
    assert len(successes) == 1, f"Expected exactly one success, got: {results}"
