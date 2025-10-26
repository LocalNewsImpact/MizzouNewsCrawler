"""Unit tests for the content type detector heuristics."""

import pytest

from src.utils.content_type_detector import ContentTypeDetector


def _detector():
    return ContentTypeDetector()


def test_detects_obituary_from_title_and_url():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/news/obituaries/jane-doe-obituary",
        title="Jane Doe Obituary: Celebration of Life",
        metadata={"meta_description": "Obituary for Jane Doe"},
        content=None,
    )
    assert result is not None
    assert result.status == "obituary"
    assert "title" in result.evidence
    assert "url" in result.evidence
    assert "obituaries" in result.evidence["url"]
    assert result.confidence_score == pytest.approx(5 / 12, rel=1e-3)
    assert result.detector_version == ContentTypeDetector.VERSION


def test_detects_opinion_from_title_prefix():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/news/story",
        title="Opinion: Why local parks matter",
        metadata=None,
        content=None,
    )
    assert result is not None
    assert result.status == "opinion"
    assert "title" in result.evidence
    assert result.confidence_score == pytest.approx(2 / 6, rel=1e-3)
    assert result.detector_version == ContentTypeDetector.VERSION


def test_detects_opinion_from_url_segment():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/opinion/guest-columnist-views",
        title="Guest columnist discusses education",
        metadata=None,
        content=None,
    )
    assert result is not None
    assert result.status == "opinion"
    assert "url" in result.evidence
    assert result.confidence_score == pytest.approx(2 / 6, rel=1e-3)
    assert result.detector_version == ContentTypeDetector.VERSION


def test_returns_none_for_standard_articles():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/news/local-updates",
        title="City council approves new budget",
        metadata={"meta_description": "Latest city council updates"},
        content="City council met to approve the new budget on Tuesday.",
    )
    assert result is None


def test_obituary_url_segment_produces_medium_confidence():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/obituary/john-doe",
        title="John Doe",
        metadata=None,
        content="Sample article body without extra obituary cues.",
    )
    assert result is not None
    assert result.status == "obituary"
    assert result.confidence == "medium"
    assert result.confidence_score == pytest.approx(3 / 12, rel=1e-3)
    assert "url" in result.evidence
    assert "obituary" in result.evidence["url"]


def test_obituary_name_with_content_signals_is_high_confidence():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/news/randy-tallman",
        title="Randy Tallman",
        metadata=None,
        content=(
            "Randy Tallman passed away on Monday. Visitation will be held Friday."
        ),
    )
    assert result is not None
    assert result.status == "obituary"
    assert result.confidence == "high"
    assert result.confidence_score == pytest.approx(4 / 12, rel=1e-3)
    assert "title_patterns" in result.evidence
    assert "content" in result.evidence


def test_title_pattern_alone_is_not_enough():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/news/jane-doe",
        title="Jane Doe",
        metadata=None,
        content="Jane Doe discusses her new business venture downtown.",
    )
    assert result is None


def test_weak_title_keyword_requires_additional_signal():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/news/remembering-jane",
        title="Remembering Jane",
        metadata=None,
        content="Remembering Jane with a fundraiser for the local shelter.",
    )
    assert result is None


def test_weak_title_keyword_combined_with_obituary_url_detects():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/obituaries/remembering-jane",
        title="Remembering Jane",
        metadata={"meta_description": "Celebration of life for Jane"},
        content=None,
    )
    assert result is not None
    assert result.status == "obituary"
    assert result.confidence == "high"
    assert result.confidence_score == pytest.approx(6 / 12, rel=1e-3)
    assert "url" in result.evidence
    assert "obituaries" in result.evidence["url"]
    assert "title" in result.evidence


def test_opinion_without_strong_signal_is_ignored():
    detector = _detector()
    result = detector.detect(
        url="https://example.com/news/story",
        title="Community leaders gather",
        metadata={
            "keywords": ["Opinion", "Editorial"],
            "meta_description": "Opinion column about parks",
        },
        content="General coverage of the meeting.",
    )
    assert result is None
