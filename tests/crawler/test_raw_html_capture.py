"""Tests for which fetched response the extractor keeps for the raw archive."""

from src.crawler import ContentExtractor


def _extractor():
    """A bare extractor with just the raw-HTML capture state initialized."""
    ex = ContentExtractor.__new__(ContentExtractor)
    ex._raw_html_by_method = {}
    ex._latest_raw_html = None
    ex._latest_raw_html_method = None
    return ex


def test_keeps_the_response_from_the_method_that_produced_the_article():
    """The archived page must match the row's recorded extraction_method."""
    ex = _extractor()
    ex._record_raw_html("<html>newspaper copy</html>", "newspaper4k")
    ex._record_raw_html("<html>selenium copy</html>", "selenium")

    ex._select_raw_html_for_archive("selenium")

    assert ex.get_last_raw_html() == ("<html>selenium copy</html>", "selenium")


def test_later_fetches_do_not_displace_the_winning_method():
    """A late fetch for a missing field shouldn't replace the content's page."""
    ex = _extractor()
    ex._record_raw_html("<html>mcmetadata copy</html>", "mcmetadata")
    # selenium re-fetches later only to fill in an author
    ex._record_raw_html("<html>selenium author refetch</html>", "selenium")

    ex._select_raw_html_for_archive("mcmetadata")

    assert ex.get_last_raw_html() == ("<html>mcmetadata copy</html>", "mcmetadata")


def test_falls_back_to_last_fetch_when_winner_fetched_nothing():
    """Parsers that reuse another method's HTML have no response of their own."""
    ex = _extractor()
    ex._record_raw_html("<html>fetched by bs4</html>", "beautifulsoup")

    ex._select_raw_html_for_archive("mcmetadata")

    assert ex.get_last_raw_html() == ("<html>fetched by bs4</html>", "beautifulsoup")


def test_nothing_fetched_yields_nothing_to_archive():
    ex = _extractor()

    ex._select_raw_html_for_archive("selenium")

    assert ex.get_last_raw_html() == (None, None)


def test_record_ignores_empty_and_decodes_bytes():
    ex = _extractor()
    ex._record_raw_html(None, "selenium")
    ex._record_raw_html("", "selenium")
    assert ex._raw_html_by_method == {}

    ex._record_raw_html(b"<html>bytes page</html>", "newspaper4k")
    ex._select_raw_html_for_archive("newspaper4k")

    assert ex.get_last_raw_html() == ("<html>bytes page</html>", "newspaper4k")


def test_repeat_fetch_by_same_method_keeps_the_latest():
    """A retry within one method should archive what it ended up with."""
    ex = _extractor()
    ex._record_raw_html("<html>attempt 1</html>", "selenium")
    ex._record_raw_html("<html>attempt 2 after retry</html>", "selenium")

    ex._select_raw_html_for_archive("selenium")

    assert ex.get_last_raw_html()[0] == "<html>attempt 2 after retry</html>"
