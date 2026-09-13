"""Content-gate heuristic (docs/BACKFIELD_IMPLEMENTATION.md §5.6).

The deterministic first layer: term density over the full text. Free, and at
the threshold below it selected exactly the one known-bad article in the
Phase 0 samples while real news about Oreo cookies and consent legislation
scored 4.
"""

from __future__ import annotations

import re

from src.utils.boilerplate import looks_like_paywall, story_text

TERMS = re.compile(
    r"cookie(s)?\b|consent|privacy policy|advertising partner(s)?"
    r"|vendor list|manage preferences|opt out",
    re.IGNORECASE,
)

# Tuned in Phase 0 on an unbiased 300-article sample: no real article reached 5.
HEURISTIC_REJECT = 5


def boilerplate_score(text: str) -> int:
    return len(TERMS.findall(text or ""))


# A walled body is short because the wall truncated it -- so the length that
# decides has to be the length of the STORY, and the wall's own words are not
# part of it.
#
# Measuring the whole body counted the furniture as if it were reporting, and
# the threshold then moved with how much of the wall the extractor happened to
# capture. mycouriertribune.com's athlete-of-the-week stub exists twice in
# production from one page: at 343 characters it was caught free, and at 909 --
# the same story, nine characters past a 900-char ceiling, the difference being
# captured subscribe furniture -- it had to be paid for. The cliff was an
# artefact of the measurement, not a property of the article.
#
# Strip the furniture first and the question becomes the right one: how much
# reporting is actually here. A thousand characters of story followed by a
# subscribe prompt is a story, and is kept.
#
# 500 is set from evidence, not taste. Measured 2026-09-13 over 1,406
# production articles: 500 known stubs and 600 cleanly-enriched articles as the
# negative control. Recall rises 63.6% -> 81.6% against the old whole-body rule,
# at ZERO false positives on the control -- whose shortest wall-carrying article
# retains 936 characters of story, so 500 clears it with most of a threshold to
# spare. Raising it to 700 buys 0.8 points of recall and spends that headroom;
# above 500 the LLM gate still decides, which is the point of a free pre-check:
# it takes only the cases it cannot be wrong about.
#
# A third cohort -- 306 articles whose capture begins with a cookie banner and
# whose status is `enriched` -- is NOT a control, and was misread as one at
# first. 27 of them fall under this threshold, and reading them shows why: they
# end mid-word ("the following students were named WOW winn") behind "available
# in full to subscribers", or hold nothing but a related-items rail. They are
# stubs that were enriched, so selecting them is the rule working.
PAYWALL_STUB_MAX_STORY_CHARS = 500


def paywalled_stub(text: str | None) -> str | None:
    """The paywall prompt a truncated body contains, or None.

    Returns the matched phrase, not a bool, so the caller can record WHICH
    wall fired and the threshold can be retuned against evidence.
    """
    body = text or ""
    wall = looks_like_paywall(body)
    if wall is None:
        return None
    # The wall is real; the remaining question is whether a story came with
    # it. story_text() works segment by segment through THE furniture detector,
    # so the prompt, the login links and the nav around them all go and the
    # reporting stays. strip_boilerplate() is the weaker, write-path answer and
    # kept enough subscribe furniture to clear any threshold.
    if len(story_text(body)) >= PAYWALL_STUB_MAX_STORY_CHARS:
        return None
    return wall
