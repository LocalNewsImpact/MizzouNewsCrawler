"""Read the paywall's blurred text back as the story it hides.

TownNews's paywall (`Mg2`) does not withhold a premium story from a reader it
does not recognise as a subscriber. It serves the whole story with every letter
moved one place on -- `the` as `uif`, `Yakima` as `Zbljnb` -- inside elements
classed `blurry-text`, and blurs them with CSS. Digits and punctuation are left
alone, and so is anything outside a `blurry-text` element: the first words of
the opening paragraph, a link, a phrase the page left plain.

The parsers read the letters, not the blur, so 69 WSU articles from the Yakima
Herald-Republic and the Walla Walla Union-Bulletin were stored as `A petition
by Mabton City Council members ... after a rewjfx cz b Zbljnb kvehf po
Xfeoftebz`, and 59 of them were classified and enriched from it.

The class marks the shifted text exactly, to the letter -- `re<span
class="blurry-text">wjfx` -- so the text inside it is shifted back and
nothing else is touched. There is no guessing where the shift starts.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString

#: The class the paywall puts on shifted text.
BLURRY_CLASS = "blurry-text"

_SKIP_PARENTS = frozenset({"script", "style", "noscript", "template"})


def unshift(text: str) -> str:
    """Move every ASCII letter one place back: `Zbljnb` -> `Yakima`."""
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 - 1) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 - 1) % 26 + 65))
        else:
            out.append(ch)
    return "".join(out)


def unmask_blurry_text(html: str | None) -> str | None:
    """``html`` with the text of every `blurry-text` element shifted back.

    Returned unchanged when the page carries no such element, which is every
    page but a paywalled TownNews one served to an unrecognised reader.
    """
    if not html or BLURRY_CLASS not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    blurred = soup.find_all(class_=BLURRY_CLASS)
    if not blurred:
        return html
    # Collected first, replaced after: `replace_with` makes a new node, so a
    # `blurry-text` inside another would otherwise be shifted twice.
    targets: dict[int, NavigableString] = {}
    for element in blurred:
        for node in element.descendants:
            if not isinstance(node, NavigableString) or isinstance(node, Comment):
                continue
            if node.parent is not None and node.parent.name in _SKIP_PARENTS:
                continue
            targets.setdefault(id(node), node)
    for node in targets.values():
        node.replace_with(unshift(str(node)))
    return str(soup)


#: A body still carrying the shift: `uif` (the), `boe` (and), `jo uif` (in the).
SHIFTED_BODY = re.compile(r" uif [a-z]| boe [a-z]| jo uif ")
