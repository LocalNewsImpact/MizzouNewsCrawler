import multiprocessing as mp
import os
import sys
from pathlib import Path

import pytest

# Ensure src is importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from models import versioning
except Exception as e:  # pragma: no cover - skip in minimal envs
    pytest.skip(
        f"Skipping concurrency stress tests; can't import models: {e}",
        allow_module_level=True,
    )


RUN_STRESS = os.getenv("RUN_STRESS_TESTS", "0") == "1"


def _make_db_path(tmpdir_path: str) -> str:
    path = os.path.join(tmpdir_path, "stress_mizzou.db")
    return f"sqlite:///{path}"


def _worker_attempt_claim(db_url: str, dv_id: str, claimer: str, out_q: mp.Queue):
    try:
        from models import versioning as v

        ok = v.claim_dataset_version(dv_id, claimer=claimer, database_url=db_url)
        out_q.put((claimer, bool(ok)))
    except Exception as e:
        out_q.put((claimer, False, str(e)))


@pytest.mark.skipif(
    not RUN_STRESS, reason="Stress tests are gated behind RUN_STRESS_TESTS=1"
)
def test_concurrent_claims_stress(tmp_path):
    db_url = _make_db_path(str(tmp_path))

    versioning.create_versioning_tables(database_url=db_url)

    iterations = 50
    procs = 8

    for it in range(iterations):
        dv = versioning.create_dataset_version(
            "stress", f"iter-{it}", created_by_job="init", database_url=db_url
        )

        q = mp.Queue()
        workers = []
        for i in range(procs):
            p = mp.Process(
                target=_worker_attempt_claim, args=(db_url, dv.id, f"proc-{i}", q)
            )
            workers.append(p)
            p.start()

        results = [q.get(timeout=5) for _ in range(procs)]

        for p in workers:
            p.join(timeout=1)

        successes = [r for r in results if len(r) >= 2 and r[1] is True]
        assert len(successes) == 1, f"Expected exactly one success, got: {results}"
