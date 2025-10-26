#!/usr/bin/env python3

"""Smoke tests for wire service detection within content cleaning."""

import types

from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def _make_pattern(text: str, pattern_type: str = "other") -> dict:
    """Build a persistent-pattern record for testing."""
    return {
        "text_content": text,
        "confidence_score": 0.95,
        "occurrences_total": 5,
        "pattern_type": pattern_type,
        "removal_reason": "stored_pattern",
    }


def run_wire_detection_smoke_tests() -> None:
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=True)

    # Avoid mutating the production database in tests
    cleaner._mark_article_as_wire = lambda *_args, **_kwargs: None  # type: ignore

    pattern_map = {
        "localpaper.com": [_make_pattern("By The Associated Press")],
        "partnerstation.com": [
            _make_pattern(
                (
                    "& © 2025 Cable News Network, Inc., "
                    "a Warner Bros. Discovery Company."
                ),
                pattern_type="footer",
            )
        ],
        "mytownnews.com": [_make_pattern("Community Calendar\nUpcoming events")],
    }

    # type: ignore[attr-defined] -- telemetry is patched just for tests
    cleaner.telemetry.get_persistent_patterns = types.MethodType(
        lambda _self, domain: pattern_map.get(domain, []),
        cleaner.telemetry,
    )

    scenarios = [
        {
            "article_id": "article_ap_001",
            "domain": "localpaper.com",
            "text": (
                "Local coverage with syndicated reporting. "
                "By The Associated Press appears at the top of the story."
            ),
            "expected_provider": "The Associated Press",
        },
        {
            "article_id": "article_cnn_001",
            "domain": "partnerstation.com",
            "text": (
                "Station update and credits. "
                "& © 2025 Cable News Network, Inc., "
                "a Warner Bros. Discovery Company."
            ),
            "expected_provider": "CNN NewsSource",
        },
        {
            "article_id": "article_local_001",
            "domain": "mytownnews.com",
            "text": (
                "Community notes prepared by staff. "
                "Upcoming events are listed "
                "without any syndication clues."
            ),
            "expected_provider": None,
        },
    ]

    for scenario in scenarios:
        cleaned_text, metadata = cleaner.process_single_article(
            text=scenario["text"],
            domain=scenario["domain"],
            article_id=scenario["article_id"],
        )

        wire_info = metadata.get("wire_detected")
        provider = wire_info.get("provider") if wire_info else None

        print("-" * 72)
        print(f"Processed article: {scenario['article_id']}")
        print(f"Expected provider: {scenario['expected_provider']}")
        print(f"Detected provider: {provider}")
        print(f"Removed characters: {metadata.get('chars_removed')}")

        if scenario["expected_provider"]:
            assert provider == scenario["expected_provider"], (
                "Wire provider detection mismatch"
            )
        else:
            assert provider is None, "Unexpected wire provider detected"

    print("-" * 72)
    print("Wire detection smoke tests passed ✅")


if __name__ == "__main__":
    run_wire_detection_smoke_tests()
