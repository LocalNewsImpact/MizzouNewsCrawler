"""Remove leading/trailing text that is not the story.

mcmetadata returns the first extractor in its cascade whose text clears 200
characters -- almost always trafilatura -- and nothing compares that text with
anything else. trafilatura's text is the most complete body and keeps the
paragraph layout, so it stays the base. What it also keeps is page text above
and below the story: Wenatchee World's "As a subscriber, you can share up to 3
articles..." gift prompt, My Edmonds News's "Will you chip in to support our
nonprofit newsroom...", a repeated headline, "Read" / "Listen" media labels.
Measured 2026-10-14 on 247 archived WSU captures, every such block was leading
or trailing text; none was in the middle of a story.

So only leading/trailing text is ever removed -- lines before the first line,
and after the last line, that most extractors agree on -- and a line is removed
only when two independent signals agree:

1. **Few of the other extractors found it.** readability, boilerpipe3, goose3
   and newspaper3k each extract the same HTML their own way. A gift prompt is in
   one of them; a story paragraph is in most. An extractor that returned a
   fragment (under ``MIN_VOTER_SHARE`` of the base) gets no vote: on a Yakima
   Herald capture three fragments outvoted the two complete bodies, and a pure
   vote reduced 2,282 chars of story to 58.
2. **The line is recognisably not prose of the story:** furniture by the shared
   classifier, the article's own title repeated, a short label that is not a
   sentence, or a reader-revenue / gift-article call to action.

Low support alone is never enough. tdn.com's opening paragraphs had support 0
and 1 because goose3 and readability start mid-story; they are full sentences,
so they stay. And the page's og:description is not a usable lede: on both tdn
pages measured it quotes the third or fifth paragraph.

A line carrying ROT47 markers is never removed: TownNews/BLOX encodes only the
premium story body, so the markers are evidence FOR the story, and ciphertext
looks like furniture to every shape rule.

Nothing here is per site, and lines in the middle of the story are never touched.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, NamedTuple, Optional

from src.utils.boilerplate import classify_furniture

#: A candidate shorter than this share of the base is a fragment, not a body.
MIN_VOTER_SHARE = 0.4

#: Characters of normalised text that identify a sentence across extractors.
KEY_CHARS = 80

#: A line shorter than this that does not end like a sentence is a label.
MAX_LABEL_CHARS = 40

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?”\"])\s+(?=[A-Z“\"])")
_NON_WORD = re.compile(r"[^a-z0-9]+")
_SENTENCE_END = re.compile(r"[.!?”\"']\s*$")
_ROT47_MARKER = re.compile(r"k\^?Am")

#: Reader-revenue and gift-article calls to action. A concept, not a site list:
#: these are the asks a publisher puts around a story, and they apply here only
#: to leading/trailing lines most extractors left out. Kept out of the shared
#: furniture classifier on purpose -- that one also edits lines in the middle of
#: stored stories, where a story about a fundraiser would lose its sentences.
_CALL_TO_ACTION = re.compile(
    r"chip\s+in|make\s+a\s+(?:tax-deductible\s+)?donation|donate\s+(?:now|today)"
    r"|support\s+(?:our|local|independent|nonprofit)\s+(?:\w+\s+)?"
    r"(?:newsroom|journalism|news|reporting)"
    r"|yes,\s+i\s+want\s+to\s+support|become\s+a\s+(?:member|supporter|subscriber)"
    r"|gift\s+this\s+article|share\s+up\s+to\s+\d+\s+articles",
    re.IGNORECASE,
)


class Trimmed(NamedTuple):
    """The kept text and what was removed from each end."""

    text: str
    leading: tuple[str, ...]
    trailing: tuple[str, ...]


def _norm(text: str) -> str:
    return _NON_WORD.sub(" ", text.lower()).strip()


def _sentence_keys(text: str) -> set[str]:
    return {
        _norm(s)[:KEY_CHARS]
        for s in _SENTENCE_SPLIT.split(text.strip())
        if len(s.strip()) >= 20
    }


def _is_title(line: str, title: Optional[str]) -> bool:
    if not title:
        return False
    a, b = _norm(line), _norm(title)
    return bool(b) and (a == b or (a.startswith(b) and len(a) <= len(b) + 40))


def _is_furniture_or_ask(text: str) -> bool:
    """A strong signal: the shared furniture classifier, or a call to action."""
    return classify_furniture(text) is not None or bool(_CALL_TO_ACTION.search(text))


def _is_title_or_label(text: str, title: Optional[str]) -> bool:
    """A weak signal: a repeated headline, or a short line that is not a sentence."""
    return _is_title(text, title) or (
        len(text) < MAX_LABEL_CHARS and not _SENTENCE_END.search(text)
    )


def trim_leading_trailing(
    base: str, others: Iterable[str], title: Optional[str] = None
) -> Trimmed:
    """Remove leading/trailing lines of ``base`` that are not the story.

    ``others`` are the other extractors' texts for the same HTML; ``title`` is
    the article's headline, when known.
    """
    lines = [line for line in (base or "").split("\n") if line.strip()]
    if not lines:
        return Trimmed(base or "", (), ())

    floor = MIN_VOTER_SHARE * len(base)
    voters = [_sentence_keys(t) for t in others if t and len(t) >= floor]
    if not voters:
        # Nothing to compare against: removing on shape alone is exactly what
        # this module exists not to do.
        return Trimmed(base, (), ())
    majority = max(1, math.ceil(len(voters) / 2))

    def support(line: str) -> int:
        keys = _sentence_keys(line)
        if not keys:
            return 0
        return sum(1 for v in voters if len(keys & v) * 2 >= len(keys))

    def backed(line: str) -> bool:
        return support(line) >= majority

    def removable(line: str) -> bool:
        text = line.strip()
        if _ROT47_MARKER.search(text):
            return False
        # A strong signal needs at least two other extractors to keep the
        # line: with one voter, "most" is that one extractor, and on Wenatchee
        # World it was boilerpipe3, which had kept the gift prompt too.
        if _is_furniture_or_ask(text):
            return support(line) < max(2, majority)
        return not backed(line) and _is_title_or_label(text, title)

    # A line removable on a strong signal is not agreed story, even when its
    # one voter kept it -- otherwise the gift prompt, as line 0, would mark
    # where the story starts and nothing before it could be examined.
    agreed = [i for i, line in enumerate(lines) if backed(line) and not removable(line)]
    if not agreed:
        return Trimmed(base, (), ())

    start = 0
    while start < agreed[0] and removable(lines[start]):
        start += 1
    end = len(lines) - 1
    while end > agreed[-1] and removable(lines[end]):
        end -= 1

    return Trimmed(
        "\n".join(lines[start : end + 1]),
        tuple(lines[:start]),
        tuple(lines[end + 1 :]),
    )
