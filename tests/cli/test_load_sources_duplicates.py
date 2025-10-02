import logging
from argparse import Namespace
from textwrap import dedent

import pytest

from src.cli.commands.load_sources import handle_load_sources_command


@pytest.fixture
def base_csv_headers() -> str:
    return "host_id,name,city,county,url_news\n"


def _run_loader(
    tmp_path,
    csv_body: str,
    caplog: pytest.LogCaptureFixture,
) -> int:
    csv_path = tmp_path / "sources.csv"
    csv_path.write_text(csv_body, encoding="utf-8")

    args = Namespace(csv=str(csv_path))

    with caplog.at_level(logging.ERROR):
        return handle_load_sources_command(args)


def test_load_sources_fails_on_duplicate_hosts(
    tmp_path,
    caplog,
    base_csv_headers,
):
    csv_rows = dedent(
        """
        1,Outlet One,Town A,County A,https://duplicate.example.com/a
        2,Outlet Two,Town B,County B,https://duplicate.example.com/b
        """
    ).strip()

    exit_code = _run_loader(
        tmp_path,
        base_csv_headers + csv_rows + "\n",
        caplog,
    )

    assert exit_code == 1
    assert any(
        "Duplicate host values detected" in message for message in caplog.messages
    )


def test_load_sources_fails_on_duplicate_urls(
    tmp_path,
    caplog,
    base_csv_headers,
):
    duplicate_url = "https://unique.example.com/story"
    csv_rows = dedent(
        f"""
        10,Outlet Alpha,Metro,Metro County,{duplicate_url}
        11,Outlet Beta,Metro,Metro County,{duplicate_url}
        """
    ).strip()

    exit_code = _run_loader(
        tmp_path,
        base_csv_headers + csv_rows + "\n",
        caplog,
    )

    assert exit_code == 1
    assert any(
        "Duplicate url_news entries detected" in message for message in caplog.messages
    )
