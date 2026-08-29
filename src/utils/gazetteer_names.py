"""Which gazetteer names are safe to match against article text.

OSM is full of named things whose names are not names: bus stops lettered
A through P, ball fields numbered #1 through #6, emergency access points
called "2", building numbers like "1327". They are legitimate map data
and useless as text.

The matcher turns every gazetteer name into an EntityRuler pattern, so a
POI called "A" becomes a pattern that fires on every "a" in an article.
Before this guard, 68,676 of 142,282 gazetteer entity matches in the
corpus -- 48.3%, across 27,360 articles and 60 publishers -- were on
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
"""


def is_matchable_gazetteer_name(name: object) -> bool:
    """True when this name can be matched against prose without poisoning it."""
    if not isinstance(name, str):
        return False
    stripped = name.strip()
    if len(stripped) < 3:
        return False
    return any(character.isalpha() for character in stripped)
