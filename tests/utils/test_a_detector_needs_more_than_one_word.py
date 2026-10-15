"""One word in a headline, a slug or a body is not a story's kind.

Every case is a real article (production, 2026-10-15). The first group are
WSU reporters' own stories the detector excluded; the second are articles it
must still catch.
"""

from __future__ import annotations

import pytest

from src.utils.content_type_detector import ContentTypeDetector


@pytest.fixture
def detector():
    return ContentTypeDetector()


def _opinion(d, url, title):
    return d._detect_opinion(url=url, title=title, keywords=[], meta_description=None)


def _obituary(d, url, title, content):
    return d._detect_obituary(
        url=url, title=title, keywords=[], meta_description=None, content=content
    )


@pytest.mark.parametrize(
    "url, title",
    [
        (
            "https://myedmondsnews.com/2025/06/have-an-opinion-about-housing-in-washington-state-heres-a-chance-to-weigh-in/",
            "Have an opinion about housing in Washington state? Here's a chance",
        ),
        (
            "https://www.cascadiadaily.com/2025/may/01/dueling-perspectives-on-display-at-hearing-over-ferndale-foster-home/",
            "Dueling perspectives on display at hearing over Ferndale foster home",
        ),
        (
            "https://www.thenewstribune.com/news/local/article1.html",
            "Have an opinion on county's controversial homeless village?",
        ),
        (
            "https://mexicoledger.com/stories/2025-letters-to-santa,147059",
            "2025 Letters to Santa",
        ),
        (
            "https://www.examiner.net/blue-springs-athletes-sign-letters-of-intent",
            "Blue Springs athletes sign letters of intent",
        ),
    ],
)
def test_a_news_story_with_the_word_in_it_is_not_opinion(detector, url, title):
    assert _opinion(detector, url, title) is None


@pytest.mark.parametrize(
    "url, title",
    [
        (
            "https://www.ozarkcountytimes.com/letters-editor/property-tax-increases-threaten-ozark-county",
            "Property tax increases threaten Ozark County",
        ),
        (
            "https://www.ozarkcountytimes.com/news-local-news-opinions-guest-blogs/old-county-jail-part-3-0",
            "The Old County Jail, Part 3",
        ),
        (
            "https://www.nwaonline.com/news/2025/may/01/opinion-putthoff-mushrooms-hide-while-hunters-seek",
            "Putthoff Mushrooms hide while hunters seek",
        ),
        (
            "https://www.bransontrilakesnews.com/perspectives/article_ba7d5c26.html",
            "Do we just move on?",
        ),
        (
            "https://www.example.com/2026/03/04/x",
            "Opinion Submission: The frustration of group therapy",
        ),
        (
            "https://www.example.com/2026/03/04/y",
            "Letter to the Editor: UAS Chancellor Aparna Palmer Responds",
        ),
    ],
)
def test_real_opinion_is_still_opinion(detector, url, title):
    result = _opinion(detector, url, title)
    assert result is not None and result.status == "opinion"


@pytest.mark.parametrize(
    "title, content",
    [
        (
            "Replacement chosen for Washington state senator who died",
            "The senator, who passed away in March, served three terms.",
        ),
        (
            "Veterans Day parade, ceremonies and more set to honor those who served",
            "Veterans who were laid to rest at the national cemetery will be honored.",
        ),
        (
            "Hollywood legend Robert Redford dies at age 89",
            "Redford passed away at his home in Utah, his publicist said.",
        ),
    ],
)
def test_news_about_a_death_is_not_an_obituary(detector, title, content):
    assert _obituary(detector, "https://example.com/news/x", title, content) is None


@pytest.mark.parametrize(
    "title",
    [
        "Rebecca John 1961-2025",
        "Dorothy H. Moll - Perryville Republic Monitor",
        "Perry Smith – Service 02/17/2026 11:00 am",
        "Anna &quot;Jean&quot; Adams 1932-2025",
    ],
)
def test_an_obituary_by_its_name_and_its_text(detector, title):
    content = "She passed away peacefully at home. She is survived by two sons."
    result = _obituary(detector, "https://example.com/stories/x,1", title, content)
    assert result is not None and result.status == "obituary"


def test_an_obituary_slug_still_counts(detector):
    result = _obituary(
        detector,
        "https://example.com/obituaries/remembering-jane",
        "Remembering Jane",
        None,
    )
    assert result is None or result.status == "obituary"
    assert "obituaries" in detector._find_segment_matches(
        "https://example.com/news/john-doe-obituary",
        detector._OBITUARY_URL_SEGMENTS,
        slug_words=True,
    ) or "obituary" in detector._find_segment_matches(
        "https://example.com/news/john-doe-obituary",
        detector._OBITUARY_URL_SEGMENTS,
        slug_words=True,
    )
