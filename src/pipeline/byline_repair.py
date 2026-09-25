"""Drop the authors newspaper4k collected from outside the byline.

newspaper4k gathers authorship document-wide -- every `rel="author"`, every
`[itemprop="author"]`, wherever it sits -- and joins what it finds. On a page
whose template prints *other* stories with their authors, every one of those
authors arrives in the byline.

The Missouri Independent is the clear case. Its pages carry four
`rel="author"` links:

    <span class="singleBylineAuthor"><a rel="author">Rudi Keller</a>    the byline
    <span class="crp_author">by <a rel="author">Jason Hancock</a>       related post
    <span class="crp_author">by <a rel="author">Jason Hancock</a>       related post
    <span class="crp_author">by <a rel="author">Annelise Hanshaw</a>    related post

`crp_author` is Contextual Related Posts, a WordPress plugin, and its
suggestions are recomputed per request. Re-fetching one story three months
later kept the first name and replaced every other one:

    Rudi Keller, Jason Hancock, Annelise Hanshaw, Ryleigh Hindle
      -> Rudi Keller, Jason Hancock, Annelise Hanshaw

    Mark Modrcin, Jazzmine Nolan-Echols, Janice Ellis, Emir Phillips
      -> Mark Modrcin, Chris Gaines, Judy Young, Doug Wojcieszak

That is the proof that the trailing names are furniture and not authorship:
the story did not change, the widget did. 402 of 557 Missouri Independent
articles (72%) carried a multi-name byline this way, against 10% on the pages
where structured data supplied the author instead.

WHAT THIS DOES. Where the page marks its own byline, the authors inside that
mark are the byline and everything outside it is dropped. Where it does not,
the parser's list is returned untouched -- this removes what the page proves
is not authorship, it does not guess at a better byline.

NOT A COUNT RULE. "Keep the first name" would work on this template by an
accident of document order, and break on any site that prints a related block
above the story. "Trim to one name" would destroy real co-bylines, which are
10% of the Independent's output.
"""

import re

#: Containers a page uses to mark ITS OWN byline. Matched as a substring of
#: the class attribute, so `singleBylineAuthor` and `article__byline` both
#: hit on `byline`.
_BYLINE_MARKS = ("byline", "author-name", "article-author", "post-author")

#: Containers that carry SOMEBODY ELSE'S byline: related posts, recirculation
#: modules, "more from this author". Anything inside these is never the
#: article's own byline, whatever it is marked as.
_FOREIGN_MARKS = (
    "crp_",  # Contextual Related Posts
    "related",
    "recirc",
    "more-from",
    "morefrom",
    "sidebar",
    "widget",
    "popular",
    "trending",
    "footer",
)

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")

#: An element with a class attribute, its content, to the matching close tag.
#: Deliberately non-greedy and shallow: this finds a marked region to read
#: names out of, it does not parse the document.
_MARKED = re.compile(
    r"<(span|div|p|section|header|li|address)[^>]*class=[\"']([^\"']*)[\"'][^>]*>(.*?)</\1>",
    re.I | re.S,
)

#: A link that names an author, inside whatever region is being read.
_AUTHOR_LINK = re.compile(r"<a[^>]*rel=[\"']author[\"'][^>]*>(.*?)</a>", re.I | re.S)


def _text(raw: str) -> str:
    from html import unescape

    return _SPACES.sub(" ", _TAGS.sub(" ", unescape(raw))).strip()


def _marked_regions(html: str):
    """`(classes, inner_html)` for every element carrying a class."""
    for match in _MARKED.finditer(html):
        yield match.group(2).lower(), match.group(3)


def byline_names(html: str | None) -> list[str]:
    """The names the page marks as ITS OWN byline, in document order.

    Empty when the page marks no byline, which is the signal to leave the
    parser's answer alone.
    """
    if not html:
        return []
    names: list[str] = []
    for classes, inner in _marked_regions(html):
        if any(mark in classes for mark in _FOREIGN_MARKS):
            continue
        if not any(mark in classes for mark in _BYLINE_MARKS):
            continue
        for link in _AUTHOR_LINK.finditer(inner):
            name = _text(link.group(1))
            if name and name not in names:
                names.append(name)
        if not _AUTHOR_LINK.search(inner):
            name = _text(inner)
            # A byline container with no author link may hold the name as
            # text. Bounded, because a container that holds the whole story
            # is not a byline.
            if name and len(name) < 120 and name not in names:
                names.append(name)
    return names


def repair(authors, html: str | None):
    """Keep only the authors the page marks as its byline.

    `authors` is what the parser returned, a list or a comma-joined string;
    the return matches. Unchanged when the page marks no byline, or when the
    marked byline names nobody the parser found -- a repair that replaces the
    answer rather than narrowing it is a different decision, and this one only
    removes what the page shows is somebody else's.
    """
    joined = isinstance(authors, str)
    parsed = (
        [part.strip() for part in authors.split(",") if part.strip()]
        if joined
        else [str(part).strip() for part in (authors or []) if str(part).strip()]
    )
    if len(parsed) < 2:
        return authors

    marked = byline_names(html)
    if not marked:
        return authors

    lowered = {name.lower() for name in marked}
    kept = [name for name in parsed if name.lower() in lowered]
    if not kept:
        return authors
    return ", ".join(kept) if joined else kept
