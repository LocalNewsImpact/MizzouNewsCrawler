"""A consent notice is removed from a body without flattening the story.

`_parse_with_mcmetadata` stored strip_furniture's text whenever it found
consent furniture. strip_furniture is the DETECTION helper: it rejoins what it
keeps with " ", so every paragraph break went with the notice. Measured
2026-10-14: 236 of 2,515 WSU bodies stored as a single paragraph, all 30 of
Wenatchee World's -- its privacy opt-out notice is consent furniture -- and
30 of Tacoma's. On the real Wenatchee capture mcmetadata returned 35 line
breaks and the stored body had 0.

The stored body is now the line-level excision, layout intact, whenever that
removes the notice; the segment-level text is kept only for a table buried in
one giant line (kq2's 27,372 chars without a line break).
"""

from __future__ import annotations

import inspect

from src.crawler import ContentExtractor, consent_free_body
from tests.test_furniture_is_one_detector import COOKIE_TABLE, STORY

# Wenatchee World's opt-out notice as mcmetadata returned it, 2026-10-14.
PRIVACY_NOTICE = (
    "As described in our Privacy Policy, we collect personal information from "
    "your interactions with us and our website, including through cookies and "
    "similar technologies. We may also share this personal information with "
    "third parties, including advertising partners. We do this in order to show "
    "you ads on other websites that are more relevant to your interests and for "
    "other reasons outlined in our privacy policy."
)

PARAGRAPHS = [
    "WENATCHEE - A new event series will help residents who arrived in the last "
    "five years connect with local organizations and each other.",
    "The program introduces the valley's history, services and amenities, and "
    "gives participants tools to get involved in civic life.",
    "The first event is April 25 at the Hilton Garden Inn in Wenatchee, and "
    "registration opens March 4.",
]


class TestTheStoryKeepsItsParagraphs:
    # The line-level excision edits a mixed line rather than dropping it, so a
    # sentence of the notice that carries no consent marker can remain; that
    # is excise_furniture_lines' documented behaviour. What is asserted here
    # is the regression: the consent text goes and every paragraph survives
    # as its own line.

    def test_a_notice_line_is_removed_and_the_breaks_survive(self):
        body, found = consent_free_body("\n".join([*PARAGRAPHS, PRIVACY_NOTICE]))
        assert found is True
        assert "Privacy Policy" not in body
        assert body.split("\n")[: len(PARAGRAPHS)] == PARAGRAPHS

    def test_a_notice_above_the_story_is_removed_too(self):
        body, found = consent_free_body("\n".join([PRIVACY_NOTICE, *PARAGRAPHS]))
        assert found is True
        assert "Privacy Policy" not in body
        assert body.split("\n")[-len(PARAGRAPHS) :] == PARAGRAPHS

    def test_a_body_without_consent_is_returned_untouched(self):
        text = "\n".join(PARAGRAPHS)
        assert consent_free_body(text) == (text, False)


class TestATableInOneGiantLine:
    """kq2: the segment-level removal is still what saves the story."""

    def test_the_table_goes_and_the_story_stays(self):
        body, found = consent_free_body(COOKIE_TABLE + "\n\n" + STORY)
        assert found is True
        assert "Ethan Corson announced his campaign" in body
        assert "cf_ob_info" not in body

    def test_a_table_alone_leaves_no_body(self):
        assert consent_free_body(COOKIE_TABLE) == (None, True)


def test_the_mcmetadata_parse_stores_this_body():
    source = inspect.getsource(ContentExtractor._parse_with_mcmetadata)
    assert "consent_free_body(text_content)" in source
    assert "stripped.text" not in source
