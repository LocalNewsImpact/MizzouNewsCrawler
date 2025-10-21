"""Test discovery CLI command defaults and behavior."""

from __future__ import annotations

import argparse

import pytest


def test_due_only_defaults_to_false():
    """Verify --due-only defaults to False for first-run friendliness."""
    from src.cli.commands.discovery import add_discovery_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_parser(subparsers)

    # Parse with no arguments
    args = parser.parse_args(["discover-urls"])

    # Should default to False to allow first run
    assert hasattr(args, "due_only")
    assert args.due_only is False, (
        "--due-only should default to False to enable first-run discovery"
    )


def test_force_all_flag_exists():
    """Verify --force-all flag is available."""
    from src.cli.commands.discovery import add_discovery_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_parser(subparsers)

    # Parse with --force-all
    args = parser.parse_args(["discover-urls", "--force-all"])

    assert hasattr(args, "force_all")
    assert args.force_all is True


def test_due_only_can_be_enabled():
    """Verify --due-only can be explicitly enabled."""
    from src.cli.commands.discovery import add_discovery_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_parser(subparsers)

    # Parse with --due-only
    args = parser.parse_args(["discover-urls", "--due-only"])

    assert args.due_only is True


def test_dataset_filter_works():
    """Verify --dataset argument works."""
    from src.cli.commands.discovery import add_discovery_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_parser(subparsers)

    # Parse with --dataset
    args = parser.parse_args(
        ["discover-urls", "--dataset", "Mizzou-Missouri-State"]
    )

    assert hasattr(args, "dataset")
    assert args.dataset == "Mizzou-Missouri-State"


def test_source_limit_works():
    """Verify --source-limit argument works."""
    from src.cli.commands.discovery import add_discovery_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_parser(subparsers)

    # Parse with --source-limit
    args = parser.parse_args(["discover-urls", "--source-limit", "10"])

    assert hasattr(args, "source_limit")
    assert args.source_limit == 10


def test_combined_flags():
    """Verify multiple flags work together."""
    from src.cli.commands.discovery import add_discovery_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_parser(subparsers)

    # Parse with multiple flags
    args = parser.parse_args(
        [
            "discover-urls",
            "--dataset",
            "test-dataset",
            "--source-limit",
            "5",
            "--due-only",
        ]
    )

    assert args.dataset == "test-dataset"
    assert args.source_limit == 5
    assert args.due_only is True


def test_discovery_status_command_exists():
    """Verify discovery-status command is registered."""
    from src.cli.commands.discovery_status import add_discovery_status_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_status_parser(subparsers)

    # Parse discovery-status command
    args = parser.parse_args(["discovery-status"])

    assert hasattr(args, "func")
    assert args.func.__name__ == "handle_discovery_status_command"


def test_discovery_status_with_dataset():
    """Verify discovery-status accepts --dataset."""
    from src.cli.commands.discovery_status import add_discovery_status_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_status_parser(subparsers)

    # Parse with --dataset
    args = parser.parse_args(
        ["discovery-status", "--dataset", "Mizzou-Missouri-State"]
    )

    assert args.dataset == "Mizzou-Missouri-State"


def test_discovery_status_with_verbose():
    """Verify discovery-status accepts --verbose."""
    from src.cli.commands.discovery_status import add_discovery_status_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_discovery_status_parser(subparsers)

    # Parse with --verbose
    args = parser.parse_args(["discovery-status", "--verbose"])

    assert hasattr(args, "verbose")
    assert args.verbose is True

    # Also test short form
    args_short = parser.parse_args(["discovery-status", "-v"])
    assert args_short.verbose is True
