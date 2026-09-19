"""The headline is the part before the publication, and sometimes only the h1 has it.

`<title>` on a news page is conventionally the headline, a separator, and the
publication: "City approves ARPA fund reallocation - Port Townsend & Jefferson
County Leader". Storing that whole string makes every headline from a publisher
carry its name, and the name is already on the row.

Worse, the convention is not reliably honoured. The Port Townsend Leader serves
`<title>` as "- Port Townsend & Jefferson County Leader" on a perfectly good
article page -- the separator and the publication with nothing before them. The
headline is in the `<h1>` and nowhere else. A reader that prefers `<title>` over
`<h1>` because `<title>` is non-empty therefore loses the headline on every
article that publisher has, and gains its name in exchange. That is what
happened: 26 clean headlines from the WSU tracker were overwritten by 4 rows
whose title was only the publication and 20 that carried it as a suffix.

So the rules are: take what is before the separator; if nothing is there, the
`<title>` has told you nothing and the `<h1>` is the better source.
"""

from __future__ import annotations

import re

#: Separators publishers put between the headline and their own name, longest
#: first so " -- " is not matched as " - ". Each is required to have space
#: around it: an unspaced hyphen belongs to the headline ("Jefferson
#: County to stop taking glass recycling Dec-1"), and an unspaced pipe does
#: not occur.
SEPARATORS = (" — ", " – ", " -- ", " | ", " - ", " · ", " » ", " :: ")

#: A title beginning with a separator carries no headline at all: everything
#: after it is the publication. Matched with or without a space, because the
#: space that normally precedes a separator has nothing to precede.
_LEADING_SEPARATOR = re.compile(r"^\s*[-\u2013\u2014|:\u00b7\u00bb]+\s*")

#: A trailing segment no longer than this may be a publication name.
#: "Port Townsend & Jefferson County Leader" is 38.
MAX_PUBLICATION_CHARS = 45


def _looks_like_a_masthead(tail: str) -> bool:
    """Whether a trailing segment is the publication rather than headline text.

    Length alone does not settle it. "and Jefferson County is done hauling it to
    the coast" is 52 characters and a clause; "Port Townsend & Jefferson County
    Leader" is 38 and a masthead. So the test is also that it reads as a name:
    a masthead is a proper noun and starts upper case, while a clause carried on
    after a dash generally continues in lower case.

    This is a heuristic, and the reliable signal is the publisher's own recorded
    name -- `sources.canonical_name` -- which this function is not given. It is
    the right thing to pass in if a case turns up that the shape cannot settle.
    """
    if not tail or len(tail) > MAX_PUBLICATION_CHARS:
        return False
    first = tail.lstrip()[:1]
    return bool(first) and not first.islower()


def split_publication(title: str) -> tuple[str, str | None]:
    """Return (headline, publication) from a `<title>`-style string.

    The publication is only separated off when the separator is the LAST one and
    what follows is short enough to be a masthead. A headline that contains a
    spaced dash keeps it: "Glass is trash - and the county is done with it"
    would lose its second half to a naive split, so length is what distinguishes
    a masthead from a clause.
    """
    text = (title or "").strip()
    if not text:
        return "", None

    # A TITLE THAT STARTS WITH THE SEPARATOR HAS NO HEADLINE.
    #
    # This is the real ptleader shape: "- Port Townsend & Jefferson County
    # Leader". There is no space before the hyphen, so a scan for a spaced
    # separator never finds it and the whole string reads as a headline -- which
    # is how the masthead came to be stored as 4 articles' names.
    if _LEADING_SEPARATOR.match(text):
        return "", _LEADING_SEPARATOR.sub("", text).strip() or None

    best: tuple[int, str] | None = None
    for sep in SEPARATORS:
        idx = text.rfind(sep)
        if idx == -1:
            continue
        tail = text[idx + len(sep) :].strip()
        if not _looks_like_a_masthead(tail):
            continue
        # The rightmost qualifying separator wins, so a headline containing one
        # keeps it and only the masthead is removed.
        if best is None or idx > best[0]:
            best = (idx, tail)
    if best is None:
        return text, None
    return text[: best[0]].strip(), best[1]


def headline_from_title(title: str) -> str:
    """The headline a `<title>` carries, or "" when it carries none.

    Empty is the important answer. "- Port Townsend & Jefferson County Leader"
    is a title tag that says only who published it, and a caller that treats
    that as a headline stores the publication as the story's name.
    """
    headline, _ = split_publication(title)
    # A residue of punctuation is not a headline: a title of "- Publication"
    # leaves "" and one of ": Publication" leaves ":".
    return "" if not re.search(r"\w", headline) else headline
