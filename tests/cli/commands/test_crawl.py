from __future__ import annotations

import argparse
from argparse import Namespace
from types import SimpleNamespace

import pytest

import src.cli.commands.crawl as crawl


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    crawl.add_crawl_parser(subparsers)
    return parser


def test_add_crawl_parser_registers_command():
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["crawl"])  # --filter required

    args = parser.parse_args(["crawl", "--filter", "HOST", "--host", "example.com"])

    assert args.func is crawl.handle_crawl_command
    assert args.filter == "HOST"
    assert args.host == "example.com"
    assert args.article_limit is None
    assert args.host_limit is None


@pytest.mark.parametrize(
    "filter_name, missing_field",
    [
        ("HOST", "host"),
        ("CITY", "city"),
        ("COUNTY", "county"),
    ],
)
def test_handle_crawl_command_requires_target(monkeypatch, filter_name, missing_field):
    errors = []
    monkeypatch.setattr(
        crawl,
        "logger",
        SimpleNamespace(
            error=lambda message: errors.append(message),
            warning=lambda *_a, **_k: None,
        ),
    )
    monkeypatch.setattr(
        crawl,
        "handle_discovery_command",
        lambda *_a, **_k: pytest.fail("forwarded despite missing field"),
    )

    args = Namespace(
        filter=filter_name,
        host=None,
        city=None,
        county=None,
        article_limit=None,
        host_limit=None,
    )

    exit_code = crawl.handle_crawl_command(args)

    assert exit_code == 1
    assert any(missing_field in message for message in errors)


def test_handle_crawl_command_forwards_to_discovery(monkeypatch):
    captured = {}
    warnings = []
    printed = []

    monkeypatch.setattr(
        crawl,
        "logger",
        SimpleNamespace(
            error=lambda *_a, **_k: None,
            warning=lambda message: warnings.append(message),
        ),
    )
    monkeypatch.setattr(
        crawl,
        "handle_discovery_command",
        lambda mapped: captured.update({"args": mapped}) or 0,
    )
    monkeypatch.setattr(
        "builtins.print",
        lambda *a, **_k: printed.append(" ".join(str(part) for part in a)),
    )

    args = Namespace(
        filter="HOST",
        host="example.com",
        city=None,
        county=None,
        article_limit=25,
        host_limit=3,
    )

    exit_code = crawl.handle_crawl_command(args)
    forwarded = captured["args"]
    state = vars(forwarded)

    assert exit_code == 0
    assert warnings and "deprecated" in warnings[0]
    assert printed and "discover-urls" in printed[0]
    assert state["command"] == "discover-urls"
    assert state["host"] == "example.com"
    assert state["city"] is None
    assert state["county"] is None
    assert state["source_limit"] == 3
    assert state["host_limit"] == 3
    assert state["max_articles"] == 25
    assert state["legacy_article_limit"] == 25
    assert state["existing_article_limit"] == 25
    assert state["force_all"] is True


def test_handle_crawl_command_defaults_for_all_filter(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        crawl,
        "logger",
        SimpleNamespace(
            error=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
        ),
    )
    monkeypatch.setattr(
        crawl,
        "handle_discovery_command",
        lambda mapped: captured.update({"args": mapped}) or 0,
    )

    args = Namespace(
        filter="ALL",
        host=None,
        city=None,
        county=None,
        article_limit=None,
        host_limit=None,
    )

    exit_code = crawl.handle_crawl_command(args)
    forwarded = captured["args"]
    state = vars(forwarded)

    assert exit_code == 0
    assert state["max_articles"] == 50
    assert state["existing_article_limit"] is None
    assert state["legacy_article_limit"] is None
    assert state["force_all"] is True
