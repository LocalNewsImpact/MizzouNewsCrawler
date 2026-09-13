"""Content-gate heuristic (docs/BACKFIELD_IMPLEMENTATION.md §5.6).

The deterministic first layer: term density over the full text. Free, and at
the threshold below it selected exactly the one known-bad article in the
Phase 0 samples while real news about Oreo cookies and consent legislation
scored 4.
"""

from __future__ import annotations

import re

from src.utils.boilerplate import flatten, looks_like_paywall, story_text

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


#: Walls that settle it on their own, with no length test.
#:
#: These do not hint that a subscription exists; they STATE that the content
#: is withheld. A complete article does not contain one, and the length of
#: whatever came with it is beside the point.
#:
#: Measured 2026-09-13 against 600 cleanly-enriched articles and 500 known
#: stubs -- appearances in real articles first, because that is the number
#: that matters:
#:
#:     available in full to subscribers       0 real   105 stubs
#:     login to continue reading              0 real   303 stubs
#:     sign up for complimentary access       0 real   303 stubs
#:     this content is for subscribers only   0 real    11 stubs
#:     for subscribers only                   0 real    11 stubs
#:     unlimited digital access               0 real     1 stub
#:
#: The bare substring "subscribers only" is deliberately NOT here: it hits 2
#: real articles. Neither is "premium content", which TownNews injects into
#: real ones ("Javascript is required for you to be able to read premium
#: content") and which the boilerplate module already removed from its
#: entitlement list for condemning four joplinglobe stories.
#:
#: WHY THE LENGTH TEST CANNOT GUARD THESE
#:
#: It declined six stubs in one run that each said "available in full to
#: subscribers", because `story_text` measured 893-2,827 characters. Reading
#: what it had counted: the teaser REPEATED, the headline again, "Posted
#: 3/23/26", "| Log in", and "Attention subscribers We have recently
#: launched a new and improved website" -- furniture and duplication, not
#: reporting. A measurement that can be inflated by the capture is not a
#: safe guard on a phrase that is already conclusive.
DECISIVE_WALLS: tuple[str, ...] = (
    "available in full to subscribers",
    "this item is available in full to subscribers",
    "this content is for subscribers only",
    "for subscribers only",
    "login to continue reading",
    "please log in to continue reading",
    "please login to continue reading",
    "sign up for complimentary access",
    "unlimited digital access",
)


def decisive_wall(text: str | None) -> str | None:
    """The conclusive wall phrase this body states, or None."""
    lowered = flatten(text or "")
    return next((phrase for phrase in DECISIVE_WALLS if phrase in lowered), None)


def paywalled_stub(text: str | None) -> str | None:
    """The paywall prompt a truncated body contains, or None.

    Returns the matched phrase, not a bool, so the caller can record WHICH
    wall fired and the threshold can be retuned against evidence.
    """
    body = text or ""
    stated = decisive_wall(body)
    if stated is not None:
        # The body says the content is withheld. There is nothing to measure.
        return stated
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


# A body with no reporting in it is not an article, whatever the reason.
#
# The gate asked two questions and not this one. `boilerplate_score` finds
# consent text and `paywalled_stub` finds walls; a body that is neither --
# a signup form, a related-items rail, a photo caption, an events listing --
# answered neither and was sent to a model, which enriched it.
#
# Measured 2026-09-13 on twelve articles enriched in forty minutes: eight
# held ZERO characters of reporting (emissourian captures whose stored body
# is a subscription form: every country, then all fifty states), one event
# listing held 49 and another story 87.
#
# 100 is set from the clean control of 600 enriched articles. Two fall
# below it and neither is an article -- a photo caption page and a run of
# headlines with no body. The shortest REAL article in that set is a
# 123-character sports brief ("Jason Lazo's 8th-inning grand slam lifts the
# Lions over the Panthers"), and it stays. A floor of 150 would have taken
# it, which is why the number is not rounder.
MIN_STORY_CHARS = 100

#: Named so a reviewer can tell these apart in `article_enrichment`.
#:
#: `not_news` from the paid gate had NO skip reason at all: the mapping
#: covered `paywall` and nothing else, so a gate rejection wrote NULL and
#: was indistinguishable from a completed enrichment. 179 rows read as
#: "fully enriched" on that basis until the entities were counted.
NO_STORY_SKIP_REASON = "no_story"
BOILERPLATE_SKIP_REASON = "boilerplate_dump"
NOT_NEWS_SKIP_REASON = "not_news_gate"


def no_story(text: str | None) -> bool:
    """Whether the body holds too little reporting to be an article.

    Measured with `story_text`, so furniture does not count towards it --
    the same reasoning as the paywall rule, and the reason a 8,924-character
    subscription form scores zero.
    """
    return len(story_text(text or "")) < MIN_STORY_CHARS
