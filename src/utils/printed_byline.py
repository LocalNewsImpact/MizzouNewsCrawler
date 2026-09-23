"""Where a byline ends in the body, so the cleaner can be asked what it says.

WHY THIS EXISTS. The extractors take the author from the page's structured data
-- JSON-LD, meta tags, CMS fields -- and nothing compared that against the line
the paper printed for its readers. Where the two disagree the printed line is
the one that is right: it is what the newsroom put on the page, while the
structured field is CMS output nobody proofreads.

WHAT IT WAS COSTING, measured on the Mizzou corpus 2026-09-22:

  * `Karl Zinke` and `Jeffrey` on examiner.net stories written by Mike Genet,
    Bill Althaus and Ashley Bastock -- 489 rows.
  * `Admin` on 405 of 405 eldoradospringsmo.com stories (100%).
  * `Luis Merlo` on 344 of 354 dosmundos.com stories (97.2%), whose bodies name
    Tere Siqueira and Angie Baldelomar.
  * `Christopher Replogle`, a KY3 reporter with 896 stories there, on one
    unterrifieddemocrat.com school board story reading "By Neal A. Johnson, UD
    Editor". Its url, title, body and date are all correct: nothing was
    contaminated, the structured field simply named the wrong person.

THIS MODULE FINDS THE BOUNDARY AND NOTHING ELSE. `BylineCleaner` already knows
what a byline says -- it strips titles and publications, keeps name particles,
drops desk names ("Staff Reports" -> nothing) and decides what is a person. What
it cannot know is where a byline ENDS, because it was written for a byline field
and a cleaned body runs the byline into the story:

    By Tere Siqueira Protests over immigration enforcement in Minnesota...

Handed that whole line, the cleaner answers "Tere Siqueira Protests Over
Immigration Enforcement In Minnesota" -- correctly, for the input it was given.
So the rules below are about where the name stops, and every question of what
the name IS goes to the cleaner.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

#: How far into the body to look. The byline is the first thing printed; a `By`
#: five paragraphs down belongs to a quoted item, a photo credit or a related
#: story, and is not this story's byline.
_LOOK_AT = 400

#: The byline line. The cleaner's own `^by\s+(.+)$` takes it from here; this only
#: has to recognise that the line IS one before measuring where it ends.
_OPENER = re.compile(r"^\s*By[:\s]+", re.IGNORECASE)

#: One word of the candidate, and the space before it. A lowercase particle is
#: included because a name continues through one -- "Juan de la Cruz" -- and the
#: walk has to reach "Cruz" to know where the byline ends. The `\s*` is what lets
#: the reader step word by word: `match(string, pos)` requires the match to begin
#: AT pos, so a pattern without it stops at the first space.
_WORD = re.compile(
    r"\s*([A-Z][A-Za-z.'’-]*"
    r"|de|del|della|di|da|dos|das|la|le|van|von|der|den|ter|bin|al|y)"
)

#: What ends a byline: punctuation, a dash, a pipe, a slash, or the line.
_ENDS_IT = re.compile(r"^\s*(?:[,;|/–—-]|$)")

#: Words that continue a name without being part of where it ends: an initial,
#: a particle, a generational suffix. Boundary knowledge, not name knowledge --
#: the walk needs them to know the name has not finished.
_CONTINUES = {
    "jr",
    "jr.",
    "sr",
    "sr.",
    "ii",
    "iii",
    "iv",
    "de",
    "del",
    "della",
    "di",
    "da",
    "dos",
    "das",
    "la",
    "le",
    "van",
    "von",
    "der",
    "den",
    "ter",
    "bin",
    "al",
    "y",
    "mac",
    "mc",
}

#: A title in front of a name moves where the name starts, so the walk steps over
#: it -- otherwise "By Congressman Mark Alford" is measured as "Congressman
#: Mark" and the surname is cut off. What to DO with the title is the cleaner's
#: business; it is passed the words as printed.
_TITLES = {
    "congressman",
    "congresswoman",
    "senator",
    "sen",
    "rep",
    "representative",
    "gov",
    "governor",
    "mayor",
    "sheriff",
    "dr",
    "rev",
    "pastor",
    "judge",
    "coach",
    "capt",
    "sgt",
    "officer",
    "mr",
    "mrs",
    "ms",
    "prof",
    "professor",
    "attorney",
}

#: A word with a lowercase letter running into a capital. The cleaned body
#: sometimes loses the space between the byline and what follows --
#: "Jayme LachnerPrairie", "Jason VanceCherryRoad" -- and there is no way to
#: split those apart, so no boundary can be found and the line is refused.
_GLUED = re.compile(r"[a-z][A-Z]")


def _is_initial(word: str) -> bool:
    return len(word.rstrip(".")) == 1


def _candidate(tail: str) -> str | None:
    """The words of `tail` that belong to the byline, as printed.

    Two words are taken on sight. A third and fourth are taken only when the
    byline visibly ENDS after them -- a comma, a dash, the end of the line -- or
    when the word continues a name (an initial, a particle, a suffix). That cap
    is the whole boundary: a sentence's first word is capitalised exactly like a
    surname, so nothing but "a byline is two to four words" separates
    "Tere Siqueira" from "Tere Siqueira Protests".
    """
    words: list[str] = []
    position = 0
    # A title shifts where the name starts, so step over it to measure the rest.
    for _ in range(2):
        lead = _WORD.match(tail, position)
        if lead and lead.group(1).lower().rstrip(".") in _TITLES:
            words.append(lead.group(1))
            position = lead.end()
        else:
            break
    titles = len(words)

    while len(words) - titles < 4:
        match = _WORD.match(tail, position)
        if not match:
            break
        word = match.group(1)
        after = tail[match.end() :]
        if len(words) - titles < 2:
            words.append(word)
            position = match.end()
            continue
        if _is_initial(word):
            words.append(word)
            position = match.end()
            continue
        if word.lower() in _CONTINUES:
            # A particle only continues a name when a name follows it. "By Eli
            # Hoff St. Louis Post-Dispatch" is a byline followed by a paper.
            if not _WORD.match(after):
                break
            words.append(word)
            position = match.end()
            continue
        if _ENDS_IT.match(after):
            words.append(word)
            position = match.end()
            continue
        break

    # A name cannot end on an initial, a particle or a dateline. "By Neal A." is
    # a byline the capture cut off; "By Jason Vance COLUMBIA" is a byline and a
    # dateline, which is conventionally set in capitals.
    while words and (
        _is_initial(words[-1])
        or words[-1].lower() in _CONTINUES
        or (len(words) > 2 and words[-1].isupper() and len(words[-1]) > 1)
    ):
        words.pop()

    if len(words) - titles < 2:
        return None
    if any(_GLUED.search(word) for word in words):
        return None
    if any(word.isupper() and "-" in word for word in words):
        # "STURMC-T" is Paul Sturm run into the Constitution-Tribune.
        return None
    return " ".join(words)


def printed_byline(text: str | None, cleaner=None) -> str | None:
    """The byline the story prints, as the cleaner reads it.

    None means "no confident answer", which is the normal case and leaves the
    structured author exactly as it was. Only the first non-empty line is read.

    The cleaner has the last word: given the printed words it strips the title
    and the paper, keeps the particles, and returns nothing at all for a desk
    name. Where it returns nothing, so does this.
    """
    if not text:
        return None
    for line in text[:_LOOK_AT].splitlines():
        if not line.strip():
            continue
        opener = _OPENER.match(line)
        if not opener:
            # Only the first line is considered.
            return None
        candidate = _candidate(line[opener.end() :])
        if candidate is None:
            return None
        if cleaner is None:
            from src.utils.byline_cleaner import BylineCleaner

            cleaner = BylineCleaner(enable_telemetry=False)
        result = cleaner.clean_byline(candidate, return_json=True)
        authors = result.get("authors") or []
        if not authors:
            return None
        return ", ".join(authors)
    return None


def _names_in(value: str | None) -> set[str]:
    """The name words in a byline, lowercased, for comparing two bylines."""
    if not value:
        return set()
    return {word for word in re.split(r"[^A-Za-z’']+", value.lower()) if len(word) > 1}


def disagrees(stored: str | None, printed: str | None) -> bool:
    """Whether these two bylines name different people.

    A SHARED NAME WORD IS AGREEMENT. "Neal Johnson" against "Neal A. Johnson" is
    one person spelled two ways, which the byline review queue exists to settle;
    swapping one for the other here would spend a write on nothing and hide the
    variant from the reviewer. Only a byline with no name word in common names
    somebody else.
    """
    if not stored or not printed:
        return False
    return not (_names_in(stored) & _names_in(printed))


def choose(
    stored: str | None, text: str | None, cleaner=None
) -> tuple[str | None, dict | None]:
    """The byline to store, and the note recording the swap.

    Returns `(author, note)`. `note` is None when nothing changed, which is the
    common case: a swap is made only where the body confidently prints a name and
    the structured field names somebody else entirely.

    The note goes in the article's metadata rather than a log line, because "why
    does this row say a different name than the page's JSON-LD" is a question
    asked months later, about one row, by somebody reading the database.
    """
    printed = printed_byline(text, cleaner=cleaner)
    if printed is None or not disagrees(stored, printed):
        return stored, None
    logger.info("printed byline %r replaces structured %r", printed, stored)
    return printed, {
        "byline_source": "printed_in_body",
        "byline_replaced": stored,
        "byline_printed": printed,
    }
