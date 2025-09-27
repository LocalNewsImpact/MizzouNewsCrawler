"""Reusable helpers for normalizing heuristic confidence scores."""

from __future__ import annotations


def normalize_score(score: int, max_score: int) -> float:
    """Return a 0-1 normalized confidence score.

    Args:
        score: The raw heuristic score accumulated by the detector.
        max_score: The theoretical maximum score that detector can produce.

    Returns:
        A float between 0.0 and 1.0 inclusive representing relative strength.
    """

    if max_score <= 0:
        return 0.0
    normalized = score / max_score
    if normalized < 0.0:
        return 0.0
    if normalized > 1.0:
        return 1.0
    return normalized


def score_to_label(score: int) -> str:
    """Convert the raw score into qualitative tiers.

    The tiers reflect our current heuristic expectations:
    - score >= 4 ⇒ "high"
    - score >= 2 ⇒ "medium"
    - otherwise "low"

    Args:
        score: Raw detection score.

    Returns:
        The label "high", "medium", or "low".
    """

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"
