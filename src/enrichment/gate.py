"""Content-gate heuristic (docs/BACKFIELD_IMPLEMENTATION.md §5.6).

The deterministic first layer: term density over the full text. Free, and at
the threshold below it selected exactly the one known-bad article in the
Phase 0 samples while real news about Oreo cookies and consent legislation
scored 4.
"""

from __future__ import annotations

import re

TERMS = re.compile(
    r"cookie(s)?\b|consent|privacy policy|advertising partner(s)?"
    r"|vendor list|manage preferences|opt out",
    re.IGNORECASE,
)

# Tuned in Phase 0 on an unbiased 300-article sample: no real article reached 5.
HEURISTIC_REJECT = 5


def boilerplate_score(text: str) -> int:
    return len(TERMS.findall(text or ""))
