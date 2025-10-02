"""Integration tests for BylineCleaner end-to-end outputs."""

import pytest

from src.utils.byline_cleaner import BylineCleaner

INTEGRATION_CASES = [
    (
        "wire_passthrough",
        {"byline": "Associated Press", "return_json": True},
        {
            "authors": [],
            "count": 0,
            "has_multiple_authors": False,
            "is_wire_content": True,
            "primary_author": None,
            "primary_wire_service": "The Associated Press",
            "wire_services": ["The Associated Press"],
        },
    ),
    (
        "simple_author",
        {"byline": "By Jane Doe, Staff Writer", "return_json": True},
        {
            "authors": ["Jane Doe"],
            "count": 1,
            "has_multiple_authors": False,
            "is_wire_content": False,
            "primary_author": "Jane Doe",
            "primary_wire_service": None,
            "wire_services": [],
        },
    ),
    (
        "multiple_authors",
        {"byline": "By Jane Doe and John Smith", "return_json": True},
        {
            "authors": ["Jane Doe", "John Smith"],
            "count": 2,
            "has_multiple_authors": True,
            "is_wire_content": False,
            "primary_author": "Jane Doe",
            "primary_wire_service": None,
            "wire_services": [],
        },
    ),
    (
        "source_suffix",
        {
            "byline": "By Jane Doe Springfield News-Leader",
            "return_json": True,
            "source_name": "Springfield News-Leader",
        },
        {
            "authors": ["Jane Doe"],
            "count": 1,
            "has_multiple_authors": False,
            "is_wire_content": False,
            "primary_author": "Jane Doe",
            "primary_wire_service": None,
            "wire_services": [],
        },
    ),
    (
        "special_contributor",
        {
            "byline": "Jane Doe Special to The Post-Dispatch",
            "return_json": True,
        },
        {
            "authors": ["Jane Doe"],
            "count": 1,
            "has_multiple_authors": False,
            "is_wire_content": False,
            "primary_author": "Jane Doe",
            "primary_wire_service": None,
            "wire_services": [],
        },
    ),
]


@pytest.mark.parametrize("_name, kwargs, expected", INTEGRATION_CASES)
def test_clean_byline_integration_snapshots(_name, kwargs, expected):
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline(**kwargs)

    assert result == expected
