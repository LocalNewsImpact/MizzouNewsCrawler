"""A page that says it does not exist is a 404, not an article that failed.

Port Townsend Leader answers a removed story with HTTP 200 and its own "Page not
found" page. The crawler took the 200 at its word, stored the page as an article,
and the body gates later filed it `not_article`. Sixteen WSU rows (12 fetched
2026-09-19, 4 on 2026-09-21 with a confirmed login) were that, all at
ptleader.com: dead links reading as extractions that found nothing.

Pinned here: the detector, and that the extraction loop sends a soft 404 down the
same road as a real one -- `NotFoundError`, link marked `404`, not retried.
"""

from __future__ import annotations

import inspect

import pytest

from src.cli.commands import extraction
from src.utils.soft_404 import (
    MIN_PROSE_CHARS,
    is_page_not_found,
    title_says_not_found,
)

STORY = (
    "The city council voted 5-2 on Tuesday to close the bridge for repairs, after "
    "months of complaints from residents who use it daily.\n\n"
    "Public works director Maria Lopez said the work would take about six weeks "
    "and cost roughly $400,000, paid from the street fund.\n\n"
    "Detour signs will go up on Monday, and buses will be rerouted along Fourth "
    "Street until the bridge reopens in late spring."
)


class TestTheTitle:
    @pytest.mark.parametrize(
        "title",
        [
            "Page not found",
            "PAGE NOT FOUND",
            "Not Found",
            "404",
            "Error 404",
            "404 - Page Not Found",
            "404: Not Found",
            "The page you requested could not be found",
            "The page cannot be found",
            "Oops! Page not found",
            "Sorry, page not found.",
            "Page not found | Port Townsend Leader",
            "Port Townsend Leader - Page not found",
        ],
    )
    def test_a_not_found_title_is_recognised(self, title):
        assert title_says_not_found(title)

    @pytest.mark.parametrize(
        "title",
        [
            "Not found guilty: jury clears county clerk",
            "404 Grill reopens downtown",
            "Page found: the missing manual",
            "Council finds page not ready for vote",
            "Where to find a page not found in the archives",
            "Boeing machinists return to work Wednesday",
            "",
            None,
        ],
    )
    def test_a_headline_that_mentions_the_words_is_not(self, title):
        """Whole-segment matching: 'Not found guilty' is a headline."""
        assert not title_says_not_found(title)


class TestTheBody:
    def test_an_error_page_is_a_soft_404(self):
        body = "Sorry, we could not find that page.\n\nHome  News  Sports  Contact"
        assert is_page_not_found("Page not found", body)

    def test_an_empty_body_is_a_soft_404(self):
        """ptleader's 16 had 0-282 characters of text."""
        assert is_page_not_found("Page not found", "")
        assert is_page_not_found("Page not found", None)

    def test_a_story_with_that_title_is_not(self):
        """The body is what says it is not an error page."""
        assert is_page_not_found("Page not found", STORY) is False

    def test_the_bar_is_the_pipelines_own(self):
        """So this and the furniture gate cannot disagree about a paragraph."""
        from src.utils.boilerplate import longest_prose_run

        assert longest_prose_run(STORY) >= MIN_PROSE_CHARS

    def test_a_normal_title_is_never_a_soft_404(self):
        assert is_page_not_found("Boeing machinists return to work", "") is False


def _loop() -> str:
    source = inspect.getsource(extraction)
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


class TestTheExtractionLoop:
    def test_a_soft_404_raises_the_error_a_real_404_raises(self):
        body = _loop()
        assert 'is_page_not_found(content.get("title"), content.get("content"))' in body
        check = body[body.index("from src.utils.soft_404 import") :]
        assert "raise NotFoundError(" in check[:400]

    def test_it_runs_before_the_article_is_stored(self):
        """An insert follows it in the same loop -- the check gates it. (An
        earlier one belongs to the single-URL command and is not the subject.)"""
        body = _loop()
        check = body.index("from src.utils.soft_404 import")
        assert "ARTICLE_INSERT_SQL," in body[check:]
        handler = body.index("            except NotFoundError as e:", check)
        insert = body.index("ARTICLE_INSERT_SQL,", check)
        assert check < insert < handler

    def test_it_sits_inside_the_try_whose_handler_marks_the_link(self):
        """The raise must land in `except NotFoundError` -- the handler that
        sets the link to 404 and gives a refetch up."""
        body = _loop()
        check = body.index("from src.utils.soft_404 import")
        try_at = body.rindex("            try:\n", 0, check)
        handler = body.index("            except NotFoundError as e:", check)
        assert try_at < check < handler
        marks = body[handler : handler + 700]
        assert '"status": "404"' in marks
        assert 'outcome="404"' in body[handler : handler + 1400]

    def test_an_unconfirmed_login_session_is_not_evidence(self):
        """`authenticated_session` False is a login-gated host we are not
        signed in to: what an anonymous visitor is shown is not proof the page
        is gone. None (no login needed) and True (confirmed) both count."""
        body = _loop()
        check = body[: body.index("from src.utils.soft_404 import")]
        assert '"authenticated_session"' in check[-200:]
        assert "is not False" in check[-200:]
