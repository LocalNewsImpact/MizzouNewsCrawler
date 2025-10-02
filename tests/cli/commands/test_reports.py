from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

import src.cli.commands.reports as reports


class FixedDateTime(datetime):
    """Deterministic datetime replacement for predictable timestamps."""

    @classmethod
    def utcnow(cls) -> datetime:
        return cls(2024, 9, 1, 12, 0, 0)


def _dummy_dataframe(row_count: int = 2) -> pd.DataFrame:
    return pd.DataFrame([{"idx": i} for i in range(row_count)])


def test_handle_county_report_uses_default_output_path(monkeypatch, capsys):
    captured: dict[str, Any] = {}

    def fake_generate(config, output_path: Path):
        captured["config"] = config
        captured["output"] = output_path
        return _dummy_dataframe()

    monkeypatch.setattr(reports, "generate_county_report", fake_generate)
    monkeypatch.setattr(reports, "datetime", FixedDateTime)

    args = SimpleNamespace(
        counties=["Boone"],
        start_date=datetime(2024, 8, 1, 0, 0, 0),
        end_date=None,
        db_url="sqlite:///data/test.db",
        entity_separator="; ",
        label_version=None,
        no_entities=False,
        output=None,
    )

    exit_code = reports.handle_county_report_command(args)

    assert exit_code == 0
    expected_path = Path("reports/county_report_20240901_120000.csv")
    assert captured["output"] == expected_path
    config = captured["config"]
    assert config.counties == ["Boone"]
    assert config.include_entities is True
    assert config.database_url == "sqlite:///data/test.db"

    output = capsys.readouterr().out.strip()
    assert output == f"Wrote 2 rows to {expected_path}"


def test_handle_county_report_respects_cli_flags(monkeypatch, capsys, tmp_path):
    captured: dict[str, Any] = {}

    def fake_generate(config, output_path: Path):
        captured["config"] = config
        captured["output"] = output_path
        return _dummy_dataframe(row_count=3)

    monkeypatch.setattr(reports, "generate_county_report", fake_generate)

    custom_output = tmp_path / "custom.csv"
    args = SimpleNamespace(
        counties=["Boone", "Callaway"],
        start_date=datetime(2024, 7, 1, 0, 0, 0),
        end_date=datetime(2024, 9, 30, 23, 59, 0),
        db_url="sqlite:///memory",
        entity_separator=" | ",
        label_version="v5",
        no_entities=True,
        output=custom_output,
    )

    exit_code = reports.handle_county_report_command(args)

    assert exit_code == 0
    assert captured["output"] == custom_output
    config = captured["config"]
    assert config.counties == ["Boone", "Callaway"]
    assert config.include_entities is False
    assert config.end_date == datetime(2024, 9, 30, 23, 59, 0)
    assert config.label_version == "v5"
    assert config.entity_separator == " | "

    output = capsys.readouterr().out.strip()
    assert output == f"Wrote 3 rows to {custom_output}"


def test_handle_county_report_handles_generation_errors(monkeypatch, capsys):
    def fake_generate(config, output_path: Path):
        raise ValueError("invalid counties")

    monkeypatch.setattr(reports, "generate_county_report", fake_generate)

    args = SimpleNamespace(
        counties=["Unknown"],
        start_date=datetime(2024, 8, 1, 0, 0, 0),
        end_date=None,
        db_url="sqlite:///data/test.db",
        entity_separator="; ",
        label_version=None,
        no_entities=False,
        output=None,
    )

    exit_code = reports.handle_county_report_command(args)

    assert exit_code == 1
    stdout = capsys.readouterr().out.strip()
    assert stdout.startswith("County report failed:")
