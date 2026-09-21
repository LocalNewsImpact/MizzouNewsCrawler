"""A page that says it does not exist, served with a 200.

Port Townsend Leader answers a removed story with HTTP 200 and its own "Page not
found" page. The crawler took the 200 at its word: the page had a title, went
into `articles`, and was later filed `not_article` by the body gates -- so a dead
link read as an extracted article that happened not to be one. Sixteen WSU rows
were like that (2026-09-21), all at ptleader.com.

A real 404 is already handled: `NotFoundError` marks the link `404` and the
record is not retried. This module lets a soft 404 take the same road.

Two conditions, both required, so a story that merely mentions a missing page is
not lost:

  * the TITLE is, in whole, a not-found phrase -- possibly with a site name
    around it ("Page not found | Port Townsend Leader");
  * the body holds no prose. A story about a missing page has paragraphs; an
    error page has a sentence or a menu. The bar is the pipeline's own
    `MIN_PROSE_CHARS`, so this and the furniture gate cannot disagree about what
    a paragraph is.
"""

from __future__ import annotations

import re

from src.utils.boilerplate import longest_prose_run

#: Prose this pipeline needs before it calls something an article.
MIN_PROSE_CHARS = 150

_SEPARATORS = re.compile(r"\s+[|\-–—:]+\s+|\s*[|–—]\s*")

#: Each is matched against a WHOLE title segment, never a substring: "Not found
#: guilty" is a headline, "Not found" is an error page.
_NOT_FOUND_PHRASES = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(?:error\s+)?404(?:\s*[-:]?\s*(?:error|not\s+found|page\s+not\s+found))?",
        r"(?:oops[!.,]?\s*)?(?:sorry[,!.]?\s*)?(?:the\s+)?page\s+not\s+found",
        r"(?:the\s+)?page\s+(?:you\s+(?:requested|are\s+looking\s+for)\s+)?"
        r"(?:could\s+not\s+be|cannot\s+be|can'?t\s+be|was\s+not|is\s+not)\s+found",
        r"(?:file\s+)?not\s+found",
        r"page\s+unavailable",
    )
)


def title_says_not_found(title: str | None) -> bool:
    """Whether a whole segment of the title is a not-found phrase."""
    if not title or not title.strip():
        return False
    segments = [s.strip(" .!") for s in _SEPARATORS.split(title.strip())]
    return any(
        phrase.fullmatch(segment)
        for segment in segments
        if segment
        for phrase in _NOT_FOUND_PHRASES
    )


def is_page_not_found(title: str | None, text: str | None) -> bool:
    """A capture that is the site's own "this does not exist" page."""
    return title_says_not_found(title) and longest_prose_run(text) < MIN_PROSE_CHARS
