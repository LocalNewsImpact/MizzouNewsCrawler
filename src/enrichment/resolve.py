"""Point resolution (docs/BACKFIELD_IMPLEMENTATION.md §5.5).

Zero model calls: the single mentioned city, else the publication's city when
it appears among the mentions. Anything else is unresolved and stays that way
unless the geocode step is enabled for the dataset.
"""

from __future__ import annotations

import re

_PUNCT = re.compile(r"[^\w\s']")
_APOSTROPHE_EDGE = re.compile(r"(^')|('$)|(\s')|('\s)")
_WS = re.compile(r"\s+")


def norm(value: str | None) -> str:
    """lowercase, collapse whitespace, strip punctuation except internal
    apostrophes ("Lee's Summit"), strip a leading "the"."""
    text = (value or "").lower()
    text = _PUNCT.sub(" ", text)
    text = _APOSTROPHE_EDGE.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    if text.startswith("the "):
        text = text[4:]
    return text


def extracted_cities(places_payload: dict) -> list[str]:
    """Distinct city components from a place_extract payload, original casing,
    first-seen order."""
    seen: dict[str, str] = {}
    for location in places_payload.get("locations") or []:
        components = (location.get("location") or {}).get("components") or {}
        city = (components.get("city") or "").strip()
        if city and norm(city) not in seen:
            seen[norm(city)] = city
    return list(seen.values())


def resolve_point(
    places_payload: dict, publication_city: str | None
) -> tuple[str, str] | None:
    """Return (place, method) or None when ambiguous."""
    cities = extracted_cities(places_payload)
    if len(cities) == 1:
        return cities[0], "single_city"
    if publication_city and norm(publication_city) in {norm(c) for c in cities}:
        return publication_city, "publication_city"
    return None
