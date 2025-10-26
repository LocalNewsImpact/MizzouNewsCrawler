import sys
from pathlib import Path

# Ensure repository root is on sys.path so `backend` package imports work
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main as app_main  # noqa: E402

client = TestClient(app_main.app)


def test_snapshot_flow(tmp_path, monkeypatch):
    # point DB_PATH to a temp DB
    tmpdb = tmp_path / "test_reviews.db"
    monkeypatch.setattr(app_main, "DB_PATH", tmpdb)
    # ensure tables init
    app_main.init_snapshot_tables()

    payload = {
        "url": "https://www.example.com/test-article",
        "host": "www.example.com",
        "html": (
            "<html><head><title>Test</title></head><body>"
            "<article><h1>Hi</h1><p>Body</p></article></body></html>"
        ),
        "pipeline_run_id": "run-1",
        "parsed_fields": {"headline": None},
        "model_confidence": 0.12,
        "failure_reason": "low_confidence",
    }

    r = client.post("/api/snapshots", json=payload)
    # Server may return 202 Accepted when snapshot is enqueued for background
    # processing; accept either 200 or 202 to be tolerant of implementation.
    assert r.status_code in (200, 202)
    js = r.json()
    sid = js.get("snapshot_id")
    assert sid

    # add candidates
    cand = [
        {
            "selector": "article",
            "field": "body",
            "score": 100.0,
            "words": 10,
            "snippet": "Body",
        }
    ]
    r2 = client.post(f"/api/snapshots/{sid}/candidates", json=cand)
    assert r2.status_code == 200
    js2 = r2.json()
    assert "inserted" in js2 and len(js2["inserted"]) == 1

    # retrieve snapshot
    r3 = client.get(f"/api/snapshots/{sid}")
    assert r3.status_code == 200
    rec = r3.json()
    assert rec["id"] == sid
    assert rec["host"] == "www.example.com"
    assert isinstance(rec.get("candidates"), list)
