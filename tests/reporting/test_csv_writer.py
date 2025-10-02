from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.csv_writer import (
    DEFAULT_REPORT_CSV_ENCODING,
    write_report_csv,
)


def test_write_report_csv_creates_parent_directory(
    tmp_path: Path,
    sample_dataframe: pd.DataFrame,
) -> None:
    output_dir = tmp_path / "nested" / "reports"
    output_path = output_dir / "sample.csv"

    result_path = write_report_csv(sample_dataframe, output_path)

    assert result_path == output_path
    assert output_path.exists()
    # pandas should include the header row using the default encoding
    contents = output_path.read_text(encoding=DEFAULT_REPORT_CSV_ENCODING)
    assert "article_id" in contents
    assert "Example" in contents


def test_write_report_csv_logs_message(
    tmp_path: Path,
    sample_dataframe: pd.DataFrame,
    caplog: pytest.LogCaptureFixture,
) -> None:
    output_path = tmp_path / "report.csv"
    logger = logging.getLogger("reporting-test")

    with caplog.at_level(logging.INFO):
        write_report_csv(sample_dataframe, output_path, logger=logger)

    assert any("Wrote report to" in message for message in caplog.messages)


def test_write_report_csv_suppresses_logging_with_none_message(
    tmp_path: Path,
    sample_dataframe: pd.DataFrame,
    caplog: pytest.LogCaptureFixture,
) -> None:
    output_path = tmp_path / "report.csv"
    logger = logging.getLogger("reporting-test-none")

    with caplog.at_level(logging.INFO):
        write_report_csv(
            sample_dataframe,
            output_path,
            logger=logger,
            log_message=None,
        )

    assert output_path.exists()
    assert not caplog.messages


def test_write_report_csv_respects_index_flag(
    tmp_path: Path,
    sample_dataframe: pd.DataFrame,
) -> None:
    output_path = tmp_path / "report_with_index.csv"

    write_report_csv(sample_dataframe, output_path, index=True)

    contents = (
        output_path.read_text(encoding=DEFAULT_REPORT_CSV_ENCODING)
        .splitlines()[0]
    )
    parts = contents.split(",")
    assert parts[0] == ""
    assert parts[1:3] == ["article_id", "title"]
