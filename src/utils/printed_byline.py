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
#: How much of the body to read. Wider than the old 400 because the byline is no
#: longer assumed to be first: a headline, a timestamp and a CMS account can sit
#: in front of it.
_LOOK_AT = 700

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


#: How many non-empty lines of the head to consider. The byline sits near the
#: top, but not always ON the top: a TownNews capture opens with the headline,
#: then the timestamp, then the CMS account, and only then the byline.
#:
#: Bounded on purpose. A `By` further down belongs to a photo credit, a related
#: story or a quoted item, and taking one would put a photographer's name on a
#: reporter's story.
_LOOK_AT_LINES = 8

#: A line that reads as the story rather than as part of its header. The byline
#: sits in the header block -- headline, timestamp, account, byline -- so the
#: scan stops where the prose starts. Without this, `By John Smith / photo` four
#: lines into a story becomes the reporter.
#:
#: Not applied to the FIRST line, which is the headline: a headline ending in a
#: question mark ("Do you love Willow Springs?") would otherwise stop the scan
#: before it began.
_SENTENCE = re.compile(r"[.!?][\"'\u201d\u2019)]*\s*$")

#: The same, for a full stop alone. A headline ends in a question mark often
#: enough and in a period almost never.
_FULL_STOP = re.compile(r"\.[\"'\u201d\u2019)]*\s*$")


#: The longest a line can be and still be a byline rather than the story. A
#: byline with a title and a paper -- "Amanda Mendez, publisher", "Eli Hoff, St.
#: Louis Post-Dispatch" -- fits inside this; an opening sentence does not.
_NAME_LINE = 80


def _reads_as_prose(line: str, first: bool = False) -> bool:
    """Whether this line is the story rather than part of its header.

    The FIRST line is a headline, which can end in a question or an exclamation
    -- "Do you love Willow Springs?" -- and stopping there would end the scan
    before it began. A headline rarely ends in a FULL STOP, so that is what
    separates the two: a first line ending in a period is the story already
    running, and a `By` below it is a credit inside it.
    """
    words = line.split()
    if len(words) < 3:
        return False
    stripped = line.strip()
    if first:
        return bool(_FULL_STOP.search(stripped))
    return bool(_SENTENCE.search(stripped))


def printed_byline(text: str | None, cleaner=None) -> str | None:
    """The byline the story prints, as the cleaner reads it.

    None means "no confident answer", which is the normal case and leaves the
    structured author exactly as it was.

    THE BYLINE IS NOT ALWAYS THE FIRST LINE, and it is not always on the same
    line as its own label. A Howell County News capture reads:

        Speaking Personally: A last word before election day   <- the headline
                  Tue, 03/31/2026 - 2:11pm                     <- the timestamp
                  admin                                        <- the CMS account
            By:\u00a0                                          <- the label, alone
        Amanda Mendez, publisher                               <- the name

    Reading only the first line found the headline and gave up, which cost 35
    real bylines: they were emptied as CMS accounts on 2026-09-22 and restored by
    hand. So the first few lines are considered, and where a label stands alone
    the next line is read as the name.

    The cleaner has the last word: given the printed words it strips the title
    and the paper, keeps the particles, and returns nothing at all for a desk
    name. Where it returns nothing, so does this.
    """
    if not text:
        return None
    lines = [line for line in text[:_LOOK_AT].splitlines() if line.strip()]
    for index, line in enumerate(lines[:_LOOK_AT_LINES]):
        opener = _OPENER.match(line)
        if not opener:
            if _reads_as_prose(line, first=index == 0):
                # The story has started; anything below is not its byline.
                return None
            continue
        candidate = _candidate(line[opener.end() :])
        if candidate is None and index + 1 < len(lines):
            # The label stands alone, so the name is the next line -- read whole,
            # because it carries no label of its own to step over.
            #
            # Only when that line looks like a byline: short, and not a sentence.
            # A name line is "Amanda Mendez, publisher"; a story's opening line
            # read this way gave "Because Kansas" and "Chara According", two
            # words of prose that pass every test for a name.
            following = lines[index + 1].strip()
            if len(following) <= _NAME_LINE and not _reads_as_prose(following):
                candidate = _candidate(following)
        if candidate is None:
            # A byline line that cannot be read is not guessed at: the line after
            # it might be the story, and a wrong name looks reviewed.
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
