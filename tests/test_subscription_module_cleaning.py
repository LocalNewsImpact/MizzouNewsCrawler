"""Tests for subscription module removal heuristics."""

# pylint: disable=protected-access

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.content_cleaner_balanced import (  # noqa: E402
    BalancedBoundaryContentCleaner,
)

SUBSCRIPTION_SNIPPET = (
    "This item is available in full to subscribers.\n"
    "Please log in to continue reading.\n"
    "Need an account? Print subscribers receive free access."
)


def _build_cleaner_with_stubbed_telemetry():
    """Create a cleaner whose telemetry hooks are stubbed for unit tests."""
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    # Enable persistent pattern path without spawning background writers.
    cleaner.enable_telemetry = True
    cleaner.telemetry.enable_telemetry = True

    cleaner.telemetry.start_cleaning_session = lambda *args, **kwargs: ""
    cleaner.telemetry.finalize_cleaning_session = lambda *args, **kwargs: None
    cleaner.telemetry.log_segment_detection = lambda *args, **kwargs: None
    cleaner.telemetry.log_wire_detection = lambda *args, **kwargs: None
    cleaner.telemetry._enqueue_payload = lambda *args, **kwargs: None

    return cleaner


def test_subscription_snippet_marked_high_confidence():
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    assert cleaner._is_high_confidence_boilerplate(SUBSCRIPTION_SNIPPET)


def test_subscription_persistent_pattern_is_removed():
    cleaner = _build_cleaner_with_stubbed_telemetry()

    cleaner.telemetry.get_persistent_patterns = lambda domain: [
        {
            "pattern_type": "subscription",
            "text_content": SUBSCRIPTION_SNIPPET,
            "confidence_score": 0.92,
            "occurrences_total": 12,
            "removal_reason": "Subscription module",
        }
    ]

    article_body = "Actual article content starts now."
    original_text = f"{SUBSCRIPTION_SNIPPET}\n\n{article_body}"

    cleaned_text, metadata = cleaner.process_single_article(
        original_text, "www.fayettenewspapers.com"
    )

    assert "available in full to subscribers" not in cleaned_text
    assert "Please log in" not in cleaned_text
    assert article_body in cleaned_text
    assert cleaned_text.lstrip().startswith(article_body)
    assert metadata["persistent_removals"] == 1
    assert "subscription" in metadata["patterns_matched"]
    assert metadata["chars_removed"] == len(original_text) - len(cleaned_text)
