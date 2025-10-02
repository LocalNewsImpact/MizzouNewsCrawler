"""Tests for cleaned author formatting utilities."""

from src.cli.commands.extraction import _format_cleaned_authors


def test_format_cleaned_authors_empty_list():
    """No authors should yield None."""
    assert _format_cleaned_authors([]) is None


def test_format_cleaned_authors_single_author():
    """Single author should be returned without list syntax."""
    original = ' John "J.T." Jones '
    expected = 'John "J.T." Jones'
    assert _format_cleaned_authors([original]) == expected


def test_format_cleaned_authors_multiple_authors():
    """Multiple authors should be joined with commas."""
    authors = ["Alice Smith", " Bob Brown ", "Charlie Doe"]
    expected = "Alice Smith, Bob Brown, Charlie Doe"
    assert _format_cleaned_authors(authors) == expected


def test_format_cleaned_authors_whitespace_only_entries():
    """Whitespace-only entries should be ignored when formatting."""
    authors = ["  ", "Dana Fox"]
    assert _format_cleaned_authors(authors) == "Dana Fox"
