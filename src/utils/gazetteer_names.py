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
#:
#: THE SPORTS AND FACILITY VOCABULARY WAS MISSING (2026-09-17). The set
#: held `field`, `pool`, `court`, `gym`, `parking` -- so the rule was
#: right and its vocabulary was half-written. `Basketball`, `Locker
#: Rooms`, `The Track` and `High School football field` are real OSM
#: features: a mapper put a description in the `name` tag, which is what
#: that tag is not for. Each became an EntityRuler pattern, so the word
#: "basketball" anywhere in an article proposed a city -- `basketball` ->
#: Springfield on an MU sports-betting story, `honor roll` -> North
#: Kansas City on an elementary school honour roll.
GENERIC_TOKENS = frozenset(
    {
        # Sports and the parts of a sports facility.
        "baseball",
        "basketball",
        "bleachers",
        "concessions",
        "courts",
        "diamond",
        "dugout",
        "football",
        "golf",
        "gymnasium",
        "hockey",
        "locker",
        "lockers",
        "pitch",
        "rink",
        "soccer",
        "softball",
        "stands",
        "tennis",
        "track",
        "volleyball",
        # Plaques and markers. `Honor Roll` is a memorial board, and the
        # all-tokens-generic rule keeps anything with a real name in it:
        # "Vietnam Veterans Memorial" survives because `vietnam` does.
        "honor",
        "marker",
        "memorial",
        "plaque",
        "roll",
        # Rooms and fixtures somebody named instead of describing.
        "bathroom",
        "bathrooms",
        "entrance",
        "exit",
        "pavilion",
        "restroom",
        "restrooms",
        "room",
        "rooms",
        "storage",
        "toilets",
        "a",
        "airport",
        "an",
        "and",
        "annex",
        "apartments",
        "arena",
        "at",
        "avenue",
        "bank",
        "bar",
        "boulevard",
        "bridge",
        "building",
        "cafe",
        "campus",
        "cemetery",
        "center",
        "centre",
        "chapel",
        "church",
        "circle",
        "city",
        "clinic",
        "club",
        "college",
        "community",
        "complex",
        "corner",
        "corners",
        "county",
        "court",
        "courthouse",
        "dam",
        "department",
        "district",
        "drive",
        "east",
        "el",
        "estates",
        "field",
        "fieldhouse",
        "fields",
        "fire",
        "for",
        "garage",
        "garden",
        "gardens",
        "grill",
        "gym",
        "hall",
        "health",
        "high",
        "highway",
        "historical",
        "home",
        "hospital",
        "hotel",
        "house",
        "inn",
        "junior",
        "la",
        "lake",
        "lane",
        "las",
        "library",
        "lodge",
        "los",
        "lot",
        "lots",
        "lower",
        "market",
        "medical",
        "middle",
        "mill",
        "motel",
        "municipal",
        "museum",
        "new",
        "north",
        "northeast",
        "northwest",
        "of",
        "office",
        "old",
        "on",
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
        "road",
        "route",
        "rural",
        "school",
        "senior",
        "service",
        "services",
        "shelter",
        "shop",
        "site",
        "society",
        "south",
        "southeast",
        "southwest",
        "square",
        "stadium",
        "station",
        "store",
        "street",
        "supply",
        "the",
        "theater",
        "theatre",
        "tower",
        "town",
        "township",
        "trail",
        "upper",
        "village",
        "way",
        "west",
        "works",
    }
)

_APOSTROPHES = {"’": "'", "‘": "'"}
_DASHES = {"–": "-", "—": "-"}
#: Only at the very END of a name. "kansas city's" is a possessive;
#: "lee's summit" is a town, and stripping inside a name destroys it.
_TRAILING_POSSESSIVE = re.compile(r"'s?$")
_LEADING_ARTICLE = re.compile(r"^the\s+")


def normalize_name(value: object) -> str:
    """The canonical form of a name, for the gazetteer and for storage.

    Case, punctuation and whitespace only. AFFIXES ARE KEPT -- both the
    leading article and the trailing possessive -- and that is the whole
    point of having two functions. An earlier version stripped it here, which turned
    "Love's" into "love", "Casey's" into "casey" and "Applebee's" into
    "applebee" -- 335 Missouri names collapsing to a single common word,
    after which the matcher fired on the word "love" in ordinary prose.
    Measured on the SEMO gymnastics article: `love` -> Love's, `a lot` ->
    A Lot, `Show Me` -> Show Me's, none of them a place the story names.

    The leading article is the same trap one word earlier: stripping it
    here turned "The Hill" into "hill" and "The Ridge" into "ridge",
    which then fired on those words in prose. Measured on a boil-water
    story: `Hill` -> The Hill, `Ridge` -> The Ridge.

    An affix is part of the place's name. It is only noise on the
    ARTICLE's side -- "the Kansas City Police Department", "Kansas
    City's mayor" -- which is what `lookup_keys` is for.
    """
    if not isinstance(value, str):
        return ""
    text = value.lower()
    for source, target in {**_APOSTROPHES, **_DASHES}.items():
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9\s'-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def lookup_keys(value: object) -> list[str]:
    """The forms an ARTICLE's entity may be looked up under.

    The canonical form first, then the same with a trailing possessive
    removed. Asymmetric on purpose:

        gazetteer "Love's"      -> key "love's"
        article   "Love's"      -> tries "love's"          -> matches
        article   "love"        -> tries "love"            -> no match
        gazetteer "The Hill"    -> key "the hill"
        article   "Hill"        -> tries "hill"            -> no match
        gazetteer "Kansas City" -> key "kansas city"
        article   "Kansas City's" -> "kansas city's", then
                                     "kansas city"         -> matches
        article   "the KC Police Department" -> "the kc police
                                     department", then "kc police
                                     department"           -> matches

    That keeps the 640 possessive matches a 0.85 threshold was papering
    over, without turning 335 business names into common words.
    """
    canonical = normalize_name(value)
    if not canonical:
        return []
    keys = [canonical]
    for form in (
        _LEADING_ARTICLE.sub("", canonical),
        _TRAILING_POSSESSIVE.sub("", canonical),
        _TRAILING_POSSESSIVE.sub("", _LEADING_ARTICLE.sub("", canonical)),
    ):
        form = re.sub(r"\s+", " ", form).strip()
        if form and form not in keys:
            keys.append(form)
    return keys


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
