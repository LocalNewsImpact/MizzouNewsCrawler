"""Content-gate heuristic (docs/BACKFIELD_IMPLEMENTATION.md §5.6).

The deterministic first layer: term density over the full text. Free, and at
the threshold below it selected exactly the one known-bad article in the
Phase 0 samples while real news about Oreo cookies and consent legislation
scored 4.
"""

from __future__ import annotations

import re

from src.utils.boilerplate import looks_like_paywall

TERMS = re.compile(
    r"cookie(s)?\b|consent|privacy policy|advertising partner(s)?"
    r"|vendor list|manage preferences|opt out",
    re.IGNORECASE,
)

# Tuned in Phase 0 on an unbiased 300-article sample: no real article reached 5.
HEURISTIC_REJECT = 5


def boilerplate_score(text: str) -> int:
    return len(TERMS.findall(text or ""))


# A walled body is short because the wall truncated it. Measured against
# production on 2026-09-06: the phrase alone selects real articles that
# merely mention subscribing, but the phrase AND a body under this length
# selected paywall stubs at 100% precision -- 75.7% of known stubs, and no
# real article. Above it the LLM gate still decides, which is the point of
# a free pre-check: it takes only the cases it cannot be wrong about.
PAYWALL_STUB_MAX_CHARS = 900


def paywalled_stub(text: str | None) -> str | None:
    """The paywall prompt a truncated body contains, or None.

    Returns the matched phrase, not a bool, so the caller can record WHICH
    wall fired and the threshold can be retuned against evidence.
    """
    body = text or ""
    if len(body) >= PAYWALL_STUB_MAX_CHARS:
        return None
    return looks_like_paywall(body)
