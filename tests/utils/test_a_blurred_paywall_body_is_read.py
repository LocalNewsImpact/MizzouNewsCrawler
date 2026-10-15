"""The paywall's blurred text is the story, shifted one letter on.

The markup below is the Yakima Herald-Republic's, from the page archived for
`recall-petition-against-mabton-mayor-rachel-ruelas-moves-forward` (2026-10-15).
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from src.utils.blurry_text import SHIFTED_BODY, unmask_blurry_text, unshift

PAGE = (
    "<html><head><title>t</title></head><body>"
    '<div class="asset-content subscriber-premium">'
    '<p class="mark-text">A petition by Mabton City Council members to recall '
    "Mayor Rachel Ruelas is moving forward after a re"
    '<span class="blurry-text">wjfx cz b Zbljnb kvehf po Xfeoftebz.</span></p>'
    '<p class="blurry-text">Nbcupo, qpqvmbujpo 2,000, jt jo uif Mpxfs Zbljnb '
    "Wbmmfz.</p>"
    "<p>A plain paragraph the page left alone.</p>"
    "</div>"
    "<script>var blurry = 'blurry-text';</script>"
    "</body></html>"
)


def test_letters_move_back_one_and_nothing_else_does():
    assert unshift("Zbljnb, 2,000 b'oe") == "Yakima, 2,000 a'nd"
    assert unshift("ab") == "za"  # a wraps to z


def _text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text()


def test_the_blurred_text_is_read_back():
    out = _text(unmask_blurry_text(PAGE))
    assert "after a review by a Yakima judge on Wednesday." in out
    assert "Mabton, population 2,000, is in the Lower Yakima Valley." in out


def test_text_outside_the_class_is_untouched():
    out = _text(unmask_blurry_text(PAGE))
    assert "A petition by Mabton City Council members" in out
    assert "A plain paragraph the page left alone." in out
    assert "var blurry = 'blurry-text';" in unmask_blurry_text(PAGE)


@pytest.mark.parametrize(
    "html", [None, "", "<p>No paywall here, the and of.</p>", "<p>blurry-text</p>"]
)
def test_a_page_without_the_class_comes_back_as_it_was(html):
    assert unmask_blurry_text(html) == html


def test_a_nested_blurry_element_is_shifted_once():
    html = '<p class="blurry-text">uif <span class="blurry-text">uif</span></p>'
    assert unmask_blurry_text(html) == (
        '<p class="blurry-text">the <span class="blurry-text">the</span></p>'
    )


def test_the_shifted_body_signature():
    assert SHIFTED_BODY.search("after a rewjfx cz b Zbljnb kvehf jo uif npoui")
    assert not SHIFTED_BODY.search("a review by a Yakima judge in the month")
