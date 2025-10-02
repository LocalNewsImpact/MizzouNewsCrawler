import json

import pytest

from src.telemetry.store import TelemetryStore
from src.utils import byline_telemetry as bt


def _make_store(tmp_path):
    return TelemetryStore(
        database=f"sqlite:///{tmp_path/'byline_telemetry.db'}",
        async_writes=False,
    )


def test_byline_cleaning_session_persists_steps(tmp_path):
    store = _make_store(tmp_path)
    telemetry = bt.BylineCleaningTelemetry(store=store)

    telemetry_id = telemetry.start_cleaning_session(
        raw_byline="By Jane Doe, Example News",
        article_id="art-1",
        candidate_link_id="cl-9",
        source_id="src-5",
        source_name="Example News",
        source_canonical_name="Example",
    )

    telemetry.log_transformation_step(
        step_name="email_removal",
        input_text="By Jane Doe <jane@example.com>",
        output_text="By Jane Doe",
        removed_content="jane@example.com",
        confidence_delta=0.1,
    )
    telemetry.log_transformation_step(
        step_name="source_removal",
        input_text="By Jane Doe, Example News",
        output_text="By Jane Doe",
        removed_content="Example News",
        confidence_delta=0.2,
    )
    telemetry.log_transformation_step(
        step_name="wire_service_detection",
        input_text="Example News wire service",
        output_text="Example News wire service",
        notes="Wire Service flag",
        confidence_delta=0.15,
    )
    telemetry.log_transformation_step(
        step_name="duplicate_removal",
        input_text="Jane Doe, Jane Doe",
        output_text="Jane Doe",
        removed_content="Jane Doe,Jane Doe",
        confidence_delta=-0.05,
    )

    telemetry.log_error("parser exploded")
    telemetry.log_warning("noisy suffix")

    summary = telemetry.get_session_summary()
    assert summary == {
        "telemetry_id": telemetry_id,
        "raw_byline": "By Jane Doe, Example News",
        "steps_completed": 4,
        "confidence_score": pytest.approx(0.4),
        "has_errors": True,
        "has_warnings": True,
    }

    telemetry.finalize_cleaning_session(
        ["Jane Doe"],
        cleaning_method="ml",
        likely_valid_authors=True,
        likely_noise=False,
        requires_manual_review=None,
    )
    telemetry.flush()

    with store.connection() as conn:
        row = conn.execute(
            (
                "SELECT raw_byline, final_authors_json, has_email, "
                "has_wire_service, source_name_removed, "
                "duplicates_removed_count, likely_valid_authors, "
                "likely_noise, requires_manual_review, cleaning_errors, "
                "parsing_warnings, confidence_score "
                "FROM byline_cleaning_telemetry"
            )
        ).fetchone()
        assert row is not None
        (
            raw_byline,
            authors_json,
            has_email,
            has_wire_service,
            source_name_removed,
            duplicates_removed,
            likely_valid,
            likely_noise,
            manual_review,
            errors_json,
            warnings_json,
            confidence_score,
        ) = row
        assert raw_byline == "By Jane Doe, Example News"
        assert json.loads(authors_json) == ["Jane Doe"]
        assert has_email == 1
        assert has_wire_service == 1
        assert source_name_removed == 1
        assert duplicates_removed == 2
        assert likely_valid == 1
        assert likely_noise == 0
        assert manual_review is None
        assert json.loads(errors_json)[0]["message"] == "parser exploded"
        assert json.loads(warnings_json)[0]["message"] == "noisy suffix"
        assert confidence_score == pytest.approx(0.4)

        steps = conn.execute(
            (
                "SELECT step_number, step_name, input_text, output_text, "
                "confidence_delta FROM byline_transformation_steps "
                "ORDER BY step_number"
            )
        ).fetchall()
        assert len(steps) == 4
        assert steps[0][1] == "email_removal"
        assert steps[-1][1] == "duplicate_removal"

    assert telemetry.current_session is None
    assert telemetry.transformation_steps == []
    assert telemetry.step_counter == 0


def test_byline_telemetry_disabled_is_noop(tmp_path):
    store = _make_store(tmp_path)
    telemetry = bt.BylineCleaningTelemetry(enable_telemetry=False, store=store)

    telemetry_id = telemetry.start_cleaning_session("By Someone")
    telemetry.log_transformation_step("email_removal", "in", "out")
    telemetry.log_error("should be ignored")
    telemetry.log_warning("should be ignored")
    telemetry.finalize_cleaning_session(
        ["Someone"],
        cleaning_method="standard",
    )
    telemetry.flush()

    assert telemetry_id

    with store.connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM byline_cleaning_telemetry"
        ).fetchone()[0]
        assert count == 0
