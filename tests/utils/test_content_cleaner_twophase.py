from __future__ import annotations

from typing import List

import pytest

from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner

COMMON_SEGMENT = (
    "Subscribe now for premium access to investigative reporting"
    " and exclusive benefits"
)


def _article(article_id: int) -> dict:
    unique_intro = (
        f"Top story {article_id} leads with relevant context and detailed "
        "background about community events across the region."
    )
    return {
        "id": article_id,
        "url": f"https://example.com/story-{article_id}",
        "content": (
            f"{unique_intro}\n"
            f"{COMMON_SEGMENT}\n"
            "Further analysis and quotes from officials provide the"
            " necessary depth.\n"
        ),
        "text_hash": f"hash-{article_id}",
    }


def test_analyze_domain_identifies_shared_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaner = TwoPhaseContentCleaner(db_path=":memory:")

    articles = [_article(1), _article(2), _article(3)]

    monkeypatch.setattr(
        cleaner,
        "_get_articles_for_domain",
        lambda domain, sample_size=None: articles,
    )

    result = cleaner.analyze_domain("example.com", min_occurrences=2)

    assert result["domain"] == "example.com"
    assert result["article_count"] == 3
    assert result["segments"], "Expected at least one repeated segment"

    segment_texts = {segment["text"] for segment in result["segments"]}
    assert COMMON_SEGMENT in segment_texts

    target_segment = next(
        segment
        for segment in result["segments"]
        if segment["text"] == COMMON_SEGMENT
    )
    assert target_segment["occurrences"] == 3
    assert target_segment["pattern_type"] == "subscription"
    assert target_segment["position_consistency"] > 0

    stats = result["stats"]
    assert stats["total_articles"] == 3
    assert stats["total_segments"] >= 1
    assert stats["affected_articles"] == 3
    assert stats["removal_percentage"] > 0


def test_analyze_domain_handles_insufficient_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaner = TwoPhaseContentCleaner(db_path=":memory:")

    monkeypatch.setattr(
        cleaner,
        "_get_articles_for_domain",
        lambda domain, sample_size=None: [_article(1)],
    )

    result = cleaner.analyze_domain("example.com", min_occurrences=2)

    assert result == {
        "domain": "example.com",
        "article_count": 1,
        "segments": [],
    }


@pytest.mark.parametrize(
    "segments_to_remove, expected",
    [
        (
            [
                {"text": COMMON_SEGMENT, "length": len(COMMON_SEGMENT)},
            ],
            (
                "Breaking news update\n\n"
                "Reader support keeps local journalism strong\n"
                "More details follow."
            ),
        ),
        (
            [
                {"text": COMMON_SEGMENT, "length": len(COMMON_SEGMENT)},
                {
                    "text": "Reader support keeps local journalism strong",
                    "length": len(
                        "Reader support keeps local journalism strong"
                    ),
                },
            ],
            "Breaking news update\n\nMore details follow.",
        ),
    ],
)
def test_clean_article_content_removes_segments(
    segments_to_remove: List[dict], expected: str
) -> None:
    cleaner = TwoPhaseContentCleaner(db_path=":memory:")

    content = (
        "Breaking news update\n"
        f"{COMMON_SEGMENT}\n"
        "Reader support keeps local journalism strong\n"
        "More details follow."
    )

    cleaned = cleaner.clean_article_content(content, segments_to_remove)

    assert cleaned == expected
    for segment in segments_to_remove:
        assert segment["text"] not in cleaned
