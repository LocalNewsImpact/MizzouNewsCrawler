"""A place the article never names is not a place the article is about.

Measured against production on 2026-09-15, over 20,521 enrichment rows:

    mentions (`geoids`)      16,758 checked   17.2% unsupported
    the point (`point_place`) 9,013 checked    9.7% unsupported

Three failures, and the famous one is the smallest:

1. THE NAME IS NOT IN THE ARTICLE -- 14.4% of mentions, 7.5% of points.
   98.7% of these appear nowhere in the body *or* the title, so they are
   not a text-field mismatch and not boilerplate that a later cleaning
   pass removed: the model returned a place the story does not contain. A
   Mexico, Missouri graduation story and a Rolla arrest story were both
   recorded as Boone County; neither contains the string "Columbia".

2. THE NAME IS ONLY IN FURNITURE -- 1.5%. `Currently in Columbia 45°F
   Sunny` is a weather widget. `Two Wendy's locations in Columbia close
   over the weekend` is the related-headline rail. A reporter's biography
   is not article content either, so the city in a sign-off line is not
   evidence the story went there. `story_text` cannot reach any of this:
   March bodies were stored already flattened, so the widget and the
   reporting are one segment and it strips nothing.

3. THE ONLY MENTION IS THE PUBLISHER'S OWN DATELINE -- 1.3% of mentions,
   2.2% of points. KMIZ is licensed to Columbia, so "COLUMBIA, Mo.
   (KMIZ)" opens a KMIZ story about B-2 bombers over Iran, a fire in
   Callaway County and a boil-water advisory in Fulton alike. The
   dateline is the newsroom's address, not the story's subject.

   A dateline is still evidence when it names somewhere ELSE: a
   Kirksville dateline on a KMIZ story does locate that story in
   Kirksville. Only the publisher's home city is disqualified, which is
   why this reads `publication_city` rather than dropping datelines.

The FIPS ladder is not implicated. City-to-county-to-state agreement
measured 100% on both codes and names; it faithfully carries a wrong city
up to a wrong county and introduces no error of its own. So the gate
belongs where the model's claim enters the record, before the ladder runs.

WHAT THIS DELIBERATELY DOES NOT CATCH: a place named in reporting but not
reported on. A Camdenton school-board questionnaire names Columbia
because a candidate wrote that she took her degree at the University of
Missouri there. That sentence is reporting, it is not near furniture, and
only a reader can say it is not story geography. Grounding is a floor.
"""

from __future__ import annotations

import re

#: Everything but word characters, whitespace and the internal apostrophe
#: of "Lee's Summit". Substituted one-for-one so offsets survive folding,
#: which is what lets the furniture window below mean anything.
_PUNCT = re.compile(r"[^\w\s']")
_WS = re.compile(r"\s+")

#: "COLUMBIA, Mo. (KMIZ) --", "By: Ryan Shiner COLUMBIA, Mo. (KMIZ)",
#: "Jefferson City, Missouri -". The byline prefix is optional because
#: some feeds put it ahead of the dateline and some do not; it is matched
#: case-insensitively while the city is not, because an all-caps or
#: Title-Case run is most of what identifies a dateline at all.
_DATELINE = re.compile(
    r"^(?:(?i:by):?\s+[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3}\s+)?"
    r"([A-Z][A-Z .'-]{2,26}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*,\s*"
    r"(?:Mo|Missouri|Kan|Kansas|Ill|Illinois|Iowa|Ark|Arkansas|Neb|Nebraska|"
    r"Okla|Oklahoma|Tenn|Tennessee|Ky|Kentucky|Wash|Washington|Vt|Vermont|"
    r"Mass|Conn|Colo|Calif|Fla|Ga|Ind|Mich|Minn|Miss|Mont|Ohio|Ore|Pa|"
    r"Texas|Va|Wis|Wyo)\.?\b"
)

#: Read within a window of a name, these say the line is not reporting.
#: Weather rails and headline rails were found in March bodies; the
#: sign-off group is there because a reporter's biography is not article
#: content, and the city in one is not evidence the story went there.
_FURNITURE = re.compile(
    r"°\s?[fc]\b|\b\d{1,2}\s?(?:am|pm)\s+\d{1,3}\s?°"
    r"|popular stories|most read|trending|latest headlines|top stories"
    r"|more from|related stories|you may also like|recommended for you"
    r"|print copy article link|share this|sign up for|subscribe to our"
    r"|advertisement|upcoming events"
    r"|is a reporter|is an editor|reporter for the|covers .{0,40} for the"
    r"|can be reached at|follow (?:him|her|us|me) on|on twitter|on facebook",
    re.IGNORECASE,
)

#: Furniture is looked for in the CLAUSE around a name rather than in a
#: fixed window, because a fixed window is wrong in both directions.
#:
#: Widgets and rails carry no sentence punctuation at all -- "Save
#: Currently in Columbia 45°F Sunny 45°F / 36°F 9 AM 46°F" -- so the
#: clause containing one runs long and catches its markers. Reporting
#: ends in a full stop, so "The Columbia City Council met Monday." is
#: bounded at "Monday." and is not condemned by a widget further down the
#: same flattened body. A 160-character window failed exactly there.
_CLAUSE_END = re.compile(r"[.!?;](?:\s|$)|\n")

#: A bound on how far the clause may run, so a body with no punctuation
#: anywhere cannot make one occurrence answer for the whole page.
CLAUSE_LIMIT = 400


def fold(text: str | None) -> str:
    """Lowercase, punctuation to spaces, LENGTH PRESERVED.

    Offsets in the result index the same characters as the input, so a
    match position can be used to slice a window out of it.
    """
    return _PUNCT.sub(" ", (text or "").lower())


def _patterns(name: str) -> list[re.Pattern]:
    """Word-bounded patterns for one place name.

    Whitespace is elastic because folding turns "St. Louis" into "st
    louis" with two spaces and "St Louis" into one. The saint/mount
    aliases are spelled out because folding cannot reach them.
    """
    words = fold(name).split()
    if not words:
        return []
    forms = [words]
    # Census files the apostrophe ("Lee's Summit"); copy frequently drops
    # it, and the two must not read as different towns.
    bare = [w.replace("'", "") for w in words]
    if bare != words:
        forms.append(bare)
    for form in list(forms):
        head, tail = form[0], form[1:]
        for short, long in (("st", "saint"), ("ste", "sainte"), ("mt", "mount")):
            if head == short:
                forms.append([long, *tail])
            elif head == long:
                forms.append([short, *tail])
    return [
        re.compile(
            r"(?<![a-z0-9])" + r"\s+".join(re.escape(w) for w in form) + r"(?![a-z0-9])"
        )
        for form in forms
    ]


def occurrences(name: str, folded: str) -> list[tuple[int, int]]:
    """(start, end) of every place-name match in a folded haystack."""
    spans = {
        (m.start(), m.end())
        for pattern in _patterns(name)
        for m in pattern.finditer(folded)
    }
    return sorted(spans)


def clause(lowered: str, start: int, end: int) -> str:
    """The sentence-bounded span an occurrence sits in."""
    floor = max(0, start - CLAUSE_LIMIT)
    opens = [m.end() for m in _CLAUSE_END.finditer(lowered, floor, start)]
    left = opens[-1] if opens else floor
    closes = _CLAUSE_END.search(lowered, end, min(len(lowered), end + CLAUSE_LIMIT))
    right = closes.start() if closes else min(len(lowered), end + CLAUSE_LIMIT)
    return lowered[left:right]


def in_furniture(lowered: str, start: int, end: int) -> bool:
    """Does furniture sit in the same clause as this occurrence?

    Read against the LOWERCASED text rather than the folded one: folding
    turns "45°F" into "45 F" and the degree sign is most of what
    identifies a weather rail. Folding preserves length, so an offset
    found in one indexes the same character in the other.
    """
    return bool(_FURNITURE.search(clause(lowered, start, end)))


def dateline_city(content: str | None) -> str | None:
    """The city in the article's opening dateline, or None."""
    if not content:
        return None
    match = _DATELINE.match(_WS.sub(" ", content or "").strip())
    return match.group(1).strip() if match else None


def _dateline_end(flat: str) -> int:
    match = _DATELINE.match(flat)
    return match.end() if match else 0


def grounded(
    name: str | None,
    *,
    content: str | None,
    title: str | None = None,
    publication_city: str | None = None,
) -> bool:
    """Is recording `name` as this article's geography defensible?

    True when the article names the place in reporting -- its body or its
    headline, outside furniture, and outside a dateline that only says
    where the newsroom is.
    """
    if not name or not name.strip():
        return False

    if title and occurrences(name, fold(_WS.sub(" ", title).strip())):
        return True

    flat = _WS.sub(" ", content or "").strip()
    if not flat:
        return False
    folded, lowered = fold(flat), flat.lower()
    hits = occurrences(name, folded)
    if not hits:
        return False

    opener = dateline_city(flat)
    own_dateline = bool(
        opener
        and publication_city
        and fold(opener).split() == fold(publication_city).split()
    )
    end_of_dateline = _dateline_end(flat) if own_dateline else 0

    for start, end in hits:
        if start < end_of_dateline:
            continue  # the newsroom's own address
        if in_furniture(lowered, start, end):
            continue  # a weather rail, a headline rail, a reporter's bio
        return True
    return False
