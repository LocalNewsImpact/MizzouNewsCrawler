"""Selenium escalates on a missing BODY, not on missing metadata.

Selenium is the expensive last resort: it exists for pages a plain fetch cannot
get — bot walls, modals, JS-rendered bodies. It was also being launched whenever
*any* field was missing, which in practice meant chasing bylines over stories we
had already captured in full.

Production telemetry over 30 days: of 6,366 extractions where a non-Selenium
method supplied the content, Selenium then supplied the author exactly ONCE and
the publish_date ZERO times — while that path made up ~92% of all Selenium
invocations and ~67% of worker capacity. Most of those articles simply have no
byline to find.
"""

import pytest

from src.crawler import ContentExtractor


@pytest.fixture
def extractor():
    return ContentExtractor.__new__(ContentExtractor)


FULL_BODY = "A paragraph of real article text that runs on. " * 60  # ~2800 chars
TEASER = "Subscribers only. Sign in to continue reading."


def test_full_body_missing_author_does_not_escalate(extractor):
    """The case that burned ~67% of capacity for one success in 6,366."""
    result = {"content": FULL_BODY, "title": "A story"}

    assert extractor._selenium_would_add_value(result, ["author"]) is False


def test_full_body_missing_author_and_date_does_not_escalate(extractor):
    result = {"content": FULL_BODY}

    assert (
        extractor._selenium_would_add_value(result, ["author", "publish_date"]) is False
    )


def test_no_content_escalates(extractor):
    """Nothing captured — a browser is the last resort and worth the cost."""
    result = {"content": "", "title": "A story"}

    assert extractor._selenium_would_add_value(result, ["content", "author"]) is True


def test_missing_content_key_escalates(extractor):
    assert extractor._selenium_would_add_value({}, ["content"]) is True


def test_paywall_teaser_escalates(extractor):
    """A stub above a paywall is not the story; a real browser may reveal it."""
    result = {"content": TEASER, "title": "A story"}

    assert extractor._selenium_would_add_value(result, ["content"]) is True


def test_whitespace_only_body_escalates(extractor):
    assert (
        extractor._selenium_would_add_value({"content": "   \n\t "}, ["content"])
        is True
    )


def test_text_field_counts_as_body(extractor):
    """Some paths populate `text` rather than `content`."""
    result = {"text": FULL_BODY}

    assert extractor._selenium_would_add_value(result, ["author"]) is False


def test_boundary_is_inclusive_of_stub_threshold(extractor):
    """At exactly the threshold we still treat it as a teaser and escalate.

    Filler must be real prose: the quality gate now also rejects bodies that
    are not writing, so a run of "xxxx" would escalate for that reason
    instead and this would no longer be testing the length boundary.
    """
    prose = (
        "The council met on Tuesday evening to review the budget and heard "
        "from residents about the proposed changes to the fee schedule. "
    )
    at_limit = (prose * 40)[: ContentExtractor.PAYWALL_STUB_MAX_CHARS]
    over_limit = (prose * 40)[: ContentExtractor.PAYWALL_STUB_MAX_CHARS + 1]

    assert (
        extractor._selenium_would_add_value({"content": at_limit}, ["author"]) is True
    )
    assert (
        extractor._selenium_would_add_value({"content": over_limit}, ["author"])
        is False
    )
