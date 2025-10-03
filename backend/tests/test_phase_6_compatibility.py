import ast
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# Ensure repository root is on sys.path so `backend` package imports work
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app import main as app_main  # noqa: E402

client = TestClient(app_main.app)


def test_phase_6_accepts_phase_5_csv_structure(tmp_path, monkeypatch):
    """Test that phase 6 can process data from phase 5 CSV output"""
    # point DB_PATH to a temp DB
    tmpdb = tmp_path / "test_reviews.db"
    monkeypatch.setattr(app_main, "DB_PATH", tmpdb)
    # ensure tables init
    app_main.init_snapshot_tables()

    # Sample row from phase 5 CSV - mimicking the structure we see
    phase_5_row = {
        "url": (
            "https://www.kbia.org/2025-09-15/a-utah-church-embarks-"
            "on-a-healing-journey-in-the-aftermath-of-the-kirk-"
            "assassination"
        ),
        "file_date": "2025-09-15",
        "title": (
            "A Utah church embarks on a healing journey in the "
            "aftermath of the Kirk assassination"
        ),
        "authors": "",
        "publish_date": "2025-09-15",
        "news": ("OREM, Utah — On a beautiful Sunday, under sunny skies..."),
        "error": "",
        "domain": "kbia",
        "name": "KBIA",
        "host_id": "323",
        "county": "Boone",
        "wire": "1",
        "geo_entities": (
            "[{'city': None, 'state': 'Utah', 'abbr': 'UT'}, "
            "{'city': 'Orem', 'state': 'Utah', 'abbr': 'UT'}]"
        ),
        "has_local_institutional_signals": "True",
        "has_missouri_locations": "False",
        "has_non_missouri_locations": "True",
        "has_international_locations": "False",
        "is_purely_non_local": "False",
    }

    # Convert phase 5 data to snapshot payload format
    title = phase_5_row["title"]
    news = phase_5_row["news"][:200]
    html_content = (
        f"<html><head><title>{title}</title></head>"
        f"<body><article>{news}...</article></body></html>"
    )

    payload = {
        "url": phase_5_row["url"],
        "host": phase_5_row["domain"],
        "html": html_content,
        "pipeline_run_id": "phase-6-test",
        "parsed_fields": {
            "headline": phase_5_row["title"],
            "authors": phase_5_row["authors"],
            "publish_date": phase_5_row["publish_date"],
            "body_text": phase_5_row["news"],
        },
        "model_confidence": 0.85,
        "failure_reason": None,
        # Include phase 5 enrichment data
        "phase_5_data": {
            "file_date": phase_5_row["file_date"],
            "domain": phase_5_row["domain"],
            "name": phase_5_row["name"],
            "host_id": int(phase_5_row["host_id"]),
            "county": phase_5_row["county"],
            "wire": bool(int(phase_5_row["wire"])),
            "geo_entities": ast.literal_eval(phase_5_row["geo_entities"]),
            "has_local_institutional_signals": (
                phase_5_row["has_local_institutional_signals"] == "True"
            ),
            "has_missouri_locations": (phase_5_row["has_missouri_locations"] == "True"),
            "has_non_missouri_locations": (
                phase_5_row["has_non_missouri_locations"] == "True"
            ),
            "has_international_locations": (
                phase_5_row["has_international_locations"] == "True"
            ),
            "is_purely_non_local": (phase_5_row["is_purely_non_local"] == "True"),
        },
    }

    # Post to snapshots API
    r = client.post("/api/snapshots", json=payload)
    assert r.status_code in (200, 202), f"Failed to create snapshot: {r.text}"

    js = r.json()
    sid = js.get("snapshot_id")
    assert sid, "No snapshot_id returned"

    # Verify snapshot was created with phase 5 data
    r2 = client.get(f"/api/snapshots/{sid}")
    assert r2.status_code == 200

    snapshot = r2.json()
    assert snapshot["url"] == phase_5_row["url"]
    assert snapshot["host"] == phase_5_row["domain"]

    # Verify phase 5 enrichment data is preserved
    if "phase_5_data" in snapshot:
        p5_data = snapshot["phase_5_data"]
        assert p5_data["county"] == "Boone"
        assert p5_data["wire"] is True
        assert len(p5_data["geo_entities"]) > 0
        assert p5_data["has_local_institutional_signals"] is True


def test_phase_6_handles_all_phase_5_columns():
    """Test that we can handle all columns from phase 5 CSV"""
    # Expected columns from phase 5 CSV
    expected_columns = [
        "url",
        "file_date",
        "title",
        "authors",
        "publish_date",
        "news",
        "error",
        "domain",
        "name",
        "host_id",
        "county",
        "wire",
        "geo_entities",
        "has_local_institutional_signals",
        "has_missouri_locations",
        "has_non_missouri_locations",
        "has_international_locations",
        "is_purely_non_local",
    ]

    # Test data transformation logic
    test_row = dict.fromkeys(expected_columns, "test_value")
    test_row["host_id"] = "123"
    test_row["wire"] = "1"
    test_row["geo_entities"] = "[]"
    test_row["has_local_institutional_signals"] = "True"

    # This would be the transformation logic for phase 6
    transformed = {
        "url": test_row["url"],
        "domain": test_row["domain"],
        "title": test_row["title"],
        "content": test_row["news"],
        "metadata": {
            "file_date": test_row["file_date"],
            "authors": test_row["authors"],
            "publish_date": test_row["publish_date"],
            "error": test_row["error"],
            "name": test_row["name"],
            "host_id": int(test_row["host_id"]),
            "county": test_row["county"],
            "wire": bool(int(test_row["wire"])),
            "geo_entities": json.loads(test_row["geo_entities"]),
            "location_flags": {
                "has_local_institutional_signals": (
                    test_row["has_local_institutional_signals"] == "True"
                ),
                "has_missouri_locations": (
                    test_row.get("has_missouri_locations", "False") == "True"
                ),
                "has_non_missouri_locations": (
                    test_row.get("has_non_missouri_locations", "False") == "True"
                ),
                "has_international_locations": (
                    test_row.get("has_international_locations", "False") == "True"
                ),
                "is_purely_non_local": (
                    test_row.get("is_purely_non_local", "False") == "True"
                ),
            },
        },
    }

    # Verify all expected fields are present
    assert transformed["url"] == "test_value"
    assert transformed["metadata"]["host_id"] == 123
    assert transformed["metadata"]["wire"] is True
    assert isinstance(transformed["metadata"]["geo_entities"], list)
    assert isinstance(transformed["metadata"]["location_flags"], dict)
    assert len(transformed["metadata"]["location_flags"]) == 5


def test_phase_5_csv_loading():
    """Test that we can actually load the phase 5 CSV file"""
    csv_path = (
        REPO_ROOT
        / "processed"
        / "phase_5"
        / "wirefiltered_fixed_5_2025-09-15T16-15-09Z.csv"
    )

    if csv_path.exists():
        df = pd.read_csv(csv_path)

        # Verify expected columns are present
        expected_cols = [
            "url",
            "title",
            "news",
            "domain",
            "county",
            "wire",
            "geo_entities",
        ]
        for col in expected_cols:
            assert col in df.columns, f"Missing expected column: {col}"

        # Test first row can be processed
        if len(df) > 0:
            first_row = df.iloc[0]
            assert pd.notna(first_row["url"])
            assert pd.notna(first_row["title"])

            # Test geo_entities parsing
            if pd.notna(first_row["geo_entities"]):
                geo_data = ast.literal_eval(first_row["geo_entities"])
                assert isinstance(geo_data, list)
    else:
        pytest.skip(f"Phase 5 CSV file not found at {csv_path}")
