"""Which gazetteer names are safe to match, and how a name is normalised.

OSM is full of named things whose names are not names: bus stops lettered
A through P, ball fields numbered #1 through #6, emergency access points
called "2", building numbers like "1327". They are legitimate map data
and useless as text.

The matcher turns every gazetteer name into an EntityRuler pattern, so a
POI called "A" becomes a pattern that fires on every "a" in an article.
Before the length guard, 68,676 of 142,282 gazetteer entity matches in
the corpus -- 48.3%, across 27,360 articles and 60 publishers -- were on
names of two characters or fewer: "A" alone accounted for 22,251.

Two rules, drawn from the corpus rather than from taste:

- Fewer than three characters is rejected. Length 1 and 2 are 68,676
  matches over 58 distinct names, effectively all noise. The real
  businesses in that band -- BP, QT, TA -- are unrecoverable as bare
  tokens anyway.
- No alphabetic character is rejected at any length, which catches
  "1327", "1501", "1984" and "99+" that survive the length rule.

Length 3 is kept: 265 matches over 26 names, nearly all real (CVS, AMC,
IRS, DMV, Kia, Cox).

A THIRD RULE FOR THE STATEWIDE POOL. Those two sufficed against one
publisher's 20-mile slice. Against a whole state they do not: they admit
"City Hall", "Post Office", "Public Library", "Fire Station" -- names
that are a description rather than an identity, and that occur in every
town. `docs/STATEWIDE_GAZETTEER.md` §3.1 discards a name occurring in
more than one Census place, which catches most of these, but a generic
name that happens to occur exactly once in a state would survive it and
resolve a story to the wrong town with total confidence.

So a name whose every token is a generic facility word is rejected on its
face. "Fire Station" goes; "Boone County Fire Protection District" stays,
because "boone" is not generic. The rule is deliberately conservative:
one distinctive token is enough to keep a name.
"""

from __future__ import annotations

import re

#: Words that describe a KIND of place rather than name one. A name made
#: only of these is a description, not an identity.
GENERIC_TOKENS = frozenset(
    {
        # the thing
        "airport",
        "apartments",
        "arena",
        "bank",
        "bar",
        "bridge",
        "building",
        "cafe",
        "campus",
        "cemetery",
        "center",
        "centre",
        "chapel",
        "church",
        "city",
        "clinic",
        "club",
        "college",
        "community",
        "complex",
        "corner",
        "corners",
        "county",
        "courthouse",
        "department",
        "district",
        "dam",
        "office",
        "estates",
        "field",
        "fields",
        "fire",
        "garage",
        "garden",
        "gardens",
        "grill",
        "gym",
        "gymnasium",
        "hall",
        "health",
        "high",
        "historical",
        "home",
        "hospital",
        "hotel",
        "house",
        "inn",
        "junior",
        "lake",
        "library",
        "lodge",
        "market",
        "medical",
        "memorial",
        "middle",
        "mill",
        "motel",
        "municipal",
        "museum",
        "park",
        "parking",
        "pharmacy",
        "place",
        "playground",
        "plaza",
        "police",
        "pool",
        "post",
        "primary",
        "public",
        "restaurant",
        "rural",
        "school",
        "senior",
        "service",
        "services",
        "shop",
        "society",
        "square",
        "stadium",
        "station",
        "store",
        "supply",
        "theater",
        "theatre",
        "tower",
        "town",
        "township",
        "trail",
        "village",
        "works",
        # the qualifier
        "and",
        "at",
        "east",
        "el",
        "for",
        "la",
        "las",
        "los",
        "lower",
        "new",
        "north",
        "northeast",
        "northwest",
        "of",
        "old",
        "on",
        "south",
        "southeast",
        "southwest",
        "the",
        "upper",
        "west",
        # the address
        "avenue",
        "boulevard",
        "circle",
        "court",
        "drive",
        "highway",
        "lane",
        "road",
        "route",
        "street",
        "way",
    }
)

_APOSTROPHES = {"’": "'", "‘": "'"}
_DASHES = {"–": "-", "—": "-"}
#: Only at the very END of a name. "kansas city's" is a possessive;
#: "lee's summit" is a town, and stripping inside a name destroys it.
_TRAILING_POSSESSIVE = re.compile(r"'s?$")
_LEADING_ARTICLE = re.compile(r"^the\s+")


def normalize_name(value: object) -> str:
    """The form a name is compared in, for gazetteer and article text alike.

    Both sides must pass through this or the comparison is not the one
    anybody intended. Beyond case and punctuation it does two things that
    a scorer was doing badly:

    - strips a LEADING article, so "the Kansas City Police Department"
      and "Kansas City Police Department" are one name;
    - strips a TRAILING possessive, so "Kansas City's" is "Kansas City".

    Those two were 640 of the corpus's fuzzy matches -- work a 0.85
    similarity threshold was doing because normalisation had not. They
    become exact matches here, and the threshold can go.
    """
    if not isinstance(value, str):
        return ""
    text = value.lower()
    for source, target in {**_APOSTROPHES, **_DASHES}.items():
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9\s'-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _LEADING_ARTICLE.sub("", text)
    text = _TRAILING_POSSESSIVE.sub("", text).strip()
    return re.sub(r"\s+", " ", text)


def is_generic_name(name: object) -> bool:
    """True when every token describes a kind of place rather than names one."""
    tokens = normalize_name(name).split()
    if not tokens:
        return True
    return all(token in GENERIC_TOKENS for token in tokens)


def is_matchable_gazetteer_name(name: object) -> bool:
    """True when this name can be matched against prose without poisoning it."""
    if not isinstance(name, str):
        return False
    stripped = name.strip()
    if len(stripped) < 3:
        return False
    if not any(character.isalpha() for character in stripped):
        return False
    return not is_generic_name(stripped)
