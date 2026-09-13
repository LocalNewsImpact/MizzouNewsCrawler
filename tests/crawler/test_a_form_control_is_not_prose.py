"""A dropdown's option list is not article text.

100 articles across 8 hosts hold a subscription checkout form as their
body: every country on earth, then "What's your delivery address?", then
all fifty states. They average 8,924 characters. 73 were CIN-classified
on that text and 12 were enriched.

`_extract_content` removed `script`, `style`, `nav`, `header`, `footer`
and `aside`, and nothing else. A `<select>` inside the content block
contributed every one of its options, and a country list is the largest
block of text on many pages.

The capture landing on a subscribe page rather than the story is a
separate failure with its own fix. This one is narrower and holds
regardless: even on the right page, a signup form in the article body
must not become part of the article.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.crawler import ContentExtractor

#: The shape of the real captures, trimmed. The full ones run through
#: every country and every state.
CHECKOUT_FORM = """
<form id="subscribe">
  <label>Country</label>
  <select name="country">
    <option>United States of America</option>
    <option>US Virgin Islands</option>
    <option>United States Minor Outlying Islands</option>
    <option>Canada</option>
    <option>Mexico, United Mexican States</option>
    <option>Zimbabwe</option>
  </select>
  <label>State</label>
  <select name="state">
    <option>Alabama</option><option>Alaska</option><option>Arizona</option>
    <option>Missouri</option><option>Wyoming</option>
  </select>
</form>
"""

STORY = (
    "The Folsom Transportation Museum will open its restored depot to the "
    "public on Saturday, the board announced Tuesday. Volunteers spent two "
    "years rebuilding the platform and the signal tower, using photographs "
    "from the 1940s to match the original paint. Admission will be free for "
    "the first weekend, and the museum expects to open regular hours in May."
)


def extract(html):
    return ContentExtractor()._extract_content(BeautifulSoup(html, "html.parser"))


class TestADropdownDoesNotBecomeTheArticle:
    def test_the_country_list_is_gone(self):
        text = extract(
            f"<html><body><article><p>{STORY}</p>{CHECKOUT_FORM}</article></body></html>"
        )
        for country in ("Zimbabwe", "US Virgin Islands", "United Mexican States"):
            assert country not in text, country

    def test_the_state_list_is_gone(self):
        text = extract(
            f"<html><body><article><p>{STORY}</p>{CHECKOUT_FORM}</article></body></html>"
        )
        for state in ("Alabama", "Alaska", "Wyoming"):
            assert state not in text, state

    def test_the_story_is_untouched(self):
        """The point is to remove the form, not to lose the reporting that
        shares a page with it."""
        text = extract(
            f"<html><body><article><p>{STORY}</p>{CHECKOUT_FORM}</article></body></html>"
        )
        assert "Folsom Transportation Museum" in text
        assert "restored depot" in text
        assert "signal tower" in text

    def test_a_page_that_is_only_a_form_yields_almost_nothing(self):
        """The emissourian captures are this: a subscribe page reached
        instead of the story. It should come back too thin to classify
        rather than as 8,924 characters of geography."""
        text = (
            extract(f"<html><body><article>{CHECKOUT_FORM}</article></body></html>")
            or ""
        )
        assert "Zimbabwe" not in text
        assert len(text) < 200, text[:200]

    def test_missouri_in_the_story_still_survives(self):
        """A state name is only furniture inside a dropdown. The same word
        in a sentence is reporting, and a text-level blocklist of state
        names -- the tempting shortcut -- would have destroyed it."""
        story = f"{STORY} The board met in Missouri on Tuesday."
        html = (
            f"<html><body><article><p>{story}</p>{CHECKOUT_FORM}"
            "</article></body></html>"
        )
        text = extract(html)
        assert "Missouri" in text
        assert "Alabama" not in text


class TestTheOtherControlsGoToo:
    def test_a_datalist_is_not_prose(self):
        html = (
            f"<html><body><article><p>{STORY} The water main work begins "
            "in April.</p>"
            '<datalist id="c"><option>Aardvark</option>'
            "<option>Zebra</option></datalist></article></body></html>"
        )
        text = extract(html)
        assert "Aardvark" not in text and "Zebra" not in text
        assert "water main" in text

    def test_a_template_is_not_prose(self):
        """`<template>` holds markup the page has not rendered. Anything it
        contains is by definition not on the page."""
        html = (
            f"<html><body><article><p>{STORY} The water main work begins "
            "in April.</p><template><p>UNRENDERED PLACEHOLDER</p>"
            "</template></article></body></html>"
        )
        assert "UNRENDERED PLACEHOLDER" not in extract(html)

    def test_a_noscript_fallback_is_not_prose(self):
        html = (
            f"<html><body><article><p>{STORY} The water main work begins "
            "in April.</p><noscript>Please enable JavaScript to view this "
            "site.</noscript></article></body></html>"
        )
        assert "enable JavaScript" not in extract(html)

    def test_what_was_removed_before_is_still_removed(self):
        """Added to, not replaced."""
        html = (
            f"<html><body><article><p>{STORY} The water main work begins "
            "in April.</p><nav>Home Sports Classifieds</nav>"
            "<footer>Copyright 2026</footer>"
            "<aside>Related stories</aside></article></body></html>"
        )
        text = extract(html)
        assert "Classifieds" not in text
        assert "Copyright 2026" not in text
        assert "Related stories" not in text
        assert "water main" in text
