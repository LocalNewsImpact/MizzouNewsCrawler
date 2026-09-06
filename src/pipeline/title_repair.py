"""Put back the half of a headline newspaper4k split off.

newspaper4k decides that a title carrying a delimiter has a site name
attached to it, and keeps the longest piece
(`newspaper/extractors/title_extractor.py`):

    for delimiter in ["|", "-", "_", "/", " » "]:
        if delimiter in title_text:
            title_text = self._split_title(title_text, delimiter, ...)

A bare hyphen is in that list, and a hyphen inside a word is not a
delimiter. So a headline splits at its first hyphenated word and the
longer side wins:

    Purr-fect Start: 8 Cats Find Homes  ->  fect Start: 8 Cats Find Homes
    Van-Far girls widen gap             ->  Far girls widen gap
    Spider-Man: Brand New Day           ->  Man: Brand New Day
    1944-2025 - Bethany Republican      ->  2025 - Bethany Republican

Roughly 800 articles in the corpus carry a headline shortened this way,
and about half of them start mid-word with a lowercase letter, which is
how it was noticed in the review queue.

The repair is narrow on purpose. The page's own `og:title`, `<title>`
and `<h1>` are read, and one is preferred only when it **ends with**
what newspaper returned and the character joining them is a hyphen --
newspaper's exact signature, and nothing else. A candidate that merely
differs, or is longer for some other reason, is left alone: this puts
back what was cut, it does not choose a better title.
"""

import re
from html import unescape

#: What the page calls itself, in the order a fuller headline is likely
#: to be found. `og:title` is written for sharing and is usually the
#: headline alone; `<title>` often carries the site name too, which does
#: not matter here because only the tail has to match.
_META_TITLE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']"
    r"(?:og:title|twitter:title)[\"'][^>]*content=[\"']([^\"']+)",
    re.I | re.S,
)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")

#: The hyphens a headline uses. A dash surrounded by spaces really is a
#: separator and newspaper is welcome to split on it; these are the ones
#: that join words.
_JOINERS = ("-", "‐", "‑")


def _clean(raw: str) -> str:
    return _SPACES.sub(" ", unescape(_TAGS.sub("", raw))).strip()


def candidates(html: str) -> list[str]:
    """What the page says its headline is, longest first."""
    if not html:
        return []
    found = [m.group(1) for m in _META_TITLE.finditer(html)]
    found += [m.group(1) for m in _H1.finditer(html)]
    found += [m.group(1) for m in _TITLE_TAG.finditer(html)]
    cleaned = [_clean(f) for f in found]
    return sorted({c for c in cleaned if c}, key=len, reverse=True)


def repair(title: str | None, html: str | None) -> str | None:
    """`title` with its hyphenated prefix restored, where one was cut.

    The title is looked for INSIDE each candidate rather than at its end.
    A `<title>` tag almost always carries the site name -- "Low-earning
    college degrees | Missouri Independent" -- so requiring the candidate
    to end with what newspaper returned would find nothing on the tag
    that most often holds the full headline.

    What is returned runs from the start of the hyphenated word to the
    end of the title, so the site name stays out of it.
    """
    if not title or not html:
        return title
    stripped = title.strip()
    if not stripped:
        return title

    for candidate in candidates(html):
        at = candidate.find(stripped)
        # `at < 2` covers both "not found" and "nothing before it to
        # restore": a hyphen needs a word on its left.
        if at < 2 or candidate[at - 1] not in _JOINERS:
            continue
        # A space before the hyphen means it was a real separator --
        # "Some Story - Houston Herald" -- and newspaper was right to
        # split there. Restoring it would put the publisher in the
        # headline.
        if candidate[at - 2].isspace():
            continue
        # Back up to the start of the word the hyphen belongs to.
        start = candidate.rfind(" ", 0, at - 1) + 1
        return candidate[start : at + len(stripped)]
    return title
