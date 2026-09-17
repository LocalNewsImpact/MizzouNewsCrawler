"""Schools, from the federal surveys rather than from whoever mapped them.

OSM is where the gazetteer's schools come from, and OSM school coverage is
whatever volunteers happened to map. Missouri's index held 3,759 names
under `schools` and did not hold Battle High School, Smith-Cotton High
School, Warrior Ridge Elementary, Hickman or Rock Bridge -- the schools
local stories are actually about.

That is not a small gap. The grounding gate admits a place the article
does not name ONLY when an institution the article DOES name resolves
there, so a missing school means a refused point: measured over 150
stories the pipeline had classified as local, the model designated a
point 215 times and the gate accepted 1.

    Battle High School, Columbia, MO        refused
    Smith-Cotton High School, Sedalia, MO   refused
    Warrenton, MO                           refused

NCES has all of them. CCD covers public schools, PSS private, and the
Census place gazetteer turns a school's city into the place geoid the
index needs -- three static files, no request at load time.

THE OFFICIAL NAME IS NOT THE NAME A NEWSPAPER PRINTS. CCD carries what is
on the paperwork -- `MURIEL W. BATTLE HIGH SCHOOL`, `DAVID H. HICKMAN
HIGH`, `WARRIOR RIDGE ELEM.` -- and a story says Battle High School,
Hickman High School, Warrior Ridge Elementary. Loading the official
string alone matches nothing, which is the same failure as not loading
it, so each school contributes every form a reporter would write.
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Iterable, Iterator

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from src.utils.gazetteer_names import is_matchable_gazetteer_name, normalize_name

logger = logging.getLogger(__name__)

GCS_BUCKET = "mizzou-osm-extracts"
GCS_PREFIX = "schools"

#: Everything under `schools` in the OSM category vocabulary, so the gate
#: and the index treat these exactly as they treat a mapped school.
CATEGORY = "schools"

#: What a Census place name carries after its own name.
_LSAD = re.compile(r"\s+(city|town|village|CDP|borough|municipality)$", re.I)

#: A middle initial marks a person's name in front of the school's own.
#: `MURIEL W. BATTLE HIGH SCHOOL` is Battle High School to everyone who
#: is not filling in a federal form.
_HONOURED = re.compile(r"^(?:[A-Z][A-Za-z'\-]*\s+)+[A-Z]\.\s+")

#: Survey shorthand, expanded to what a story would print.
_ABBREVIATIONS = (
    (r"\bELEM\.?\b", "ELEMENTARY"),
    (r"\bSCHL\.?\b", "SCHOOL"),
    (r"\bJR\.?/SR\.?\s+HIGH\b", "HIGH SCHOOL"),
    (r"\bSR\.?\s+HIGH\b", "HIGH SCHOOL"),
    (r"\bJR\.?\s+HIGH\b", "JUNIOR HIGH SCHOOL"),
    (r"\bACAD\.?\b", "ACADEMY"),
    (r"\bCTR\.?\b", "CENTER"),
    (r"\bINT\.?\b", "INTERMEDIATE"),
    (r"\bPRI\.?\b", "PRIMARY"),
)


def _expand(name: str) -> str:
    out = name
    for pattern, replacement in _ABBREVIATIONS:
        out = re.sub(pattern, replacement, out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip(" .")


def name_variants(name: str) -> list[str]:
    """Every form of this school's name worth matching, official first."""
    if not name or not name.strip():
        return []
    forms: list[str] = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value or "").strip(" .")
        if value and value.upper() not in {form.upper() for form in forms}:
            forms.append(value)

    add(name)
    expanded = _expand(name)
    add(expanded)
    short = _HONOURED.sub("", expanded)
    if short != expanded:
        add(short)
    # `HICKMAN HIGH` is written `Hickman High School`.
    for form in list(forms):
        if re.search(r"\b(HIGH|ELEMENTARY)$", form, re.I):
            add(f"{form} SCHOOL")
    return [form.title() for form in forms]


#: What a school is called once the kind of school is dropped. A story
#: writes "Southern Boone beat Blair Oaks", not "Southern Boone High
#: School beat Blair Oaks High School".
_TYPE_TAIL = re.compile(
    r"\s+(senior\s+)?(high|elementary|middle|junior\s+high|primary|"
    r"intermediate|university|college|community\s+college)(\s+school)?$",
    re.I,
)

#: A stem that IS one of these says WHICH school in town rather than
#: naming one. Matched whole, not as a prefix: `Central Methodist` and
#: `North Callaway` are real names and a prefix rule refused both.
#: Single generic words are already refused by the two-word rule.
_GENERIC_STEM = frozenset(
    {"main street", "north", "south", "east", "west", "central", "city", "county"}
)

#: `Missouri Western State University` is `Missouri Western` in a story,
#: never `Missouri Western State`. Stripped after the type word.
_TRAILING_STATE = re.compile(r"\s+state$", re.I)


def school_stem(name: str, places: set[str]) -> str | None:
    """`Southern Boone High School` -> `Southern Boone`, when that is safe.

    Universities too: a story writes "Southeast Missouri State gymnastics"
    and "Missouri Western hosts", never the registered name. Ten such
    stems appear in 335 Missouri articles and none of them is a town --
    `Missouri Western`, `Missouri Southern`, `Central Methodist`,
    `Mineral Area`, `Southwest Baptist`.

    THE STEM MUST NOT BE A PLACE. Most school names are their own town --
    `Poplar Bluff High School`, `St. Clair High School` -- and the stem is
    then the town, which locates nothing new and can locate the WRONG
    thing: `St Peters Elementary` is in Joplin, and St. Peters is a city
    near St. Louis. 184 stems are excluded on that rule, against 107 kept.

    Two words at least, so a stem cannot collapse to a surname.
    """
    stem = _TYPE_TAIL.sub("", name).strip()
    if stem.lower() == name.lower():
        return None
    stem = _TRAILING_STATE.sub("", stem).strip()
    if len(stem.split()) < 2:
        return None
    if stem.lower() in _GENERIC_STEM or normalize_city(stem) in places:
        return None
    return stem if is_matchable_gazetteer_name(stem) else None


def normalize_city(value: str | None) -> str:
    """`St Louis`, `Saint Louis`, `St.Louis` and `St. Louis` are one place.

    164 Missouri schools give their city as `St Louis` and 92 as `Saint
    Louis`; the Census file says `St. Louis`. Left alone, 474 of 2,974
    schools resolved to no place at all -- almost every one of them a
    saint.
    """
    text_value = (value or "").strip().lower()
    text_value = re.sub(r"\bsaint\b", "st", text_value)
    text_value = re.sub(r"\bst\.?\s*", "st ", text_value)
    text_value = re.sub(r"[^a-z0-9 ]", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def read_places(handle: Iterable[str]) -> dict[str, tuple[str, str]]:
    """City name -> (place geoid, place name), from the Census gazetteer.

    A name borne by more than one place is dropped rather than guessed:
    the index's own rule is that a name in two places locates nothing.
    """
    seen: dict[str, set[tuple[str, str]]] = {}
    for row in csv.DictReader(handle, delimiter="\t"):
        raw = _LSAD.sub("", (row.get("NAME") or "").strip()).strip()
        geoid = (row.get("GEOID") or "").strip()
        if not raw or not geoid:
            continue
        seen.setdefault(normalize_city(raw), set()).add((geoid, raw))
    return {key: next(iter(v)) for key, v in seen.items() if len(v) == 1}


def read_schools(
    handle: Iterable[str], places: dict[str, tuple[str, str]]
) -> Iterator[dict]:
    """Gazetteer features from a school extract, one per name variant.

    A school with no resolvable place is skipped: the index answers with a
    place geoid, and a feature that cannot supply one would enter the
    ambiguity count while never being able to answer.
    """
    for row in csv.DictReader(handle):
        resolved = places.get(normalize_city(row.get("city")))
        if not resolved:
            continue
        place_geoid, place_name = resolved
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        source = (row.get("source") or "ccd").strip()
        school_id = (row.get("school_id") or "").strip()
        if not school_id:
            continue
        forms = name_variants(row.get("name") or "")
        # The short form a story actually writes, where it is safe.
        known_places = {normalize_city(p) for _, p in places.values()}
        for form in list(forms):
            stem = school_stem(form, known_places)
            if stem and stem.lower() not in {f.lower() for f in forms}:
                forms.append(stem)
        for index, variant in enumerate(forms):
            # The same guard the OSM path applies, so one corpus, one rule.
            if not is_matchable_gazetteer_name(variant):
                continue
            yield {
                "osm_type": source,
                "osm_id": f"{school_id}-{index}",
                "name": variant,
                "name_norm": normalize_name(variant),
                "category": CATEGORY,
                "lat": lat,
                "lon": lon,
                "place_geoid": place_geoid,
                "place_name": place_name,
                "county_geoid": (row.get("county_geoid") or "").strip() or None,
            }


#: Categories where a name is an institution whose location identifies a
#: story. A shop or a bus stop is not, and stemming one yields a surname.
STEMMABLE = ("schools", "religious", "government", "healthcare", "emergency")

_STEM_ROWS = text("""
    SELECT f.name, f.name_norm, f.category, f.place_geoid, f.place_name,
           f.county_geoid, min(f.lat) AS lat, min(f.lon) AS lon
      FROM gazetteer_features f
      JOIN gazetteer_name_places np
        ON np.state = f.state AND np.name_norm = f.name_norm
     WHERE f.state = :state
       AND f.category IN :cats
       AND f.place_geoid IS NOT NULL
       AND np.place_count = 1
     GROUP BY f.name, f.name_norm, f.category, f.place_geoid, f.place_name,
              f.county_geoid
""")


def stem_features(session: Session, state: str, *, dry_run: bool = False) -> dict:
    """Add the short form for every institution in the index, not just NCES.

    `read_schools` stems the federal extract, and universities are not in
    it -- CCD and PSS are K-12. So `Southeast Missouri State University`
    sat in the index from OSM while every story wrote "Southeast Missouri
    State gymnastics", and nothing matched.

    The same safety rule applies: the stem must not be a place, must keep
    two words, and must survive the name guard. Measured over Missouri,
    117 stems reach about 2,200 articles and none of them is a town.
    """
    from datetime import datetime, timezone

    known = {
        row[0]
        for row in session.execute(
            text("SELECT name_norm FROM gazetteer_name_places WHERE state = :s"),
            {"s": state},
        )
    }
    places = {
        normalize_city(row[0])
        for row in session.execute(
            text(
                "SELECT DISTINCT place_name FROM gazetteer_features "
                "WHERE state = :s AND place_name IS NOT NULL"
            ),
            {"s": state},
        )
    }
    rows = (
        session.execute(
            _STEM_ROWS.bindparams(bindparam("cats", expanding=True)),
            {"state": state, "cats": list(STEMMABLE)},
        )
        .mappings()
        .all()
    )

    now = datetime.now(timezone.utc)
    seen: set[str] = set()
    written = 0
    for row in rows:
        stem = school_stem(row["name"], places)
        if not stem:
            continue
        stem_norm = normalize_name(stem)
        if stem_norm in known or stem_norm in seen:
            continue
        seen.add(stem_norm)
        if dry_run:
            written += 1
            continue
        session.execute(
            _INSERT,
            {
                "id": f"{state}:stem:{stem_norm}",
                "state": state,
                "osm_type": "stem",
                "osm_id": stem_norm,
                "name": stem,
                "name_norm": stem_norm,
                "category": row["category"],
                "lat": row["lat"],
                "lon": row["lon"],
                "place_geoid": row["place_geoid"],
                "place_name": row["place_name"],
                "county_geoid": row["county_geoid"],
                "now": now,
                "tags": "{}",
            },
        )
        written += 1
    if not dry_run:
        session.commit()
    return {"candidates": len(rows), "written": written}


_INSERT = text("""
    INSERT INTO gazetteer_features
      (id, state, osm_type, osm_id, name, name_norm, category, lat, lon,
       place_geoid, place_name, county_geoid, geocoded_at, tags)
    VALUES
      (:id, :state, :osm_type, :osm_id, :name, :name_norm, :category,
       :lat, :lon, :place_geoid, :place_name, :county_geoid, :now,
       CAST(:tags AS JSON))
    ON CONFLICT (state, osm_type, osm_id) DO NOTHING
""")


def extract_uri(state: str) -> str:
    return f"gs://{GCS_BUCKET}/{GCS_PREFIX}/schools_{state}.csv"


def places_uri(state: str) -> str:
    return f"gs://{GCS_BUCKET}/{GCS_PREFIX}/census_places_{state}.txt"


def _storage_client():
    """The GCS client, behind a seam -- tests patch THIS, for the reason
    `statewide_gazetteer._storage_client` documents."""
    from google.cloud import storage  # type: ignore[attr-defined]

    return storage.Client()


def _download(path: str, missing: str) -> str:
    client = _storage_client()
    blob = client.bucket(GCS_BUCKET).blob(path)
    if not blob.exists():
        raise FileNotFoundError(missing)
    return blob.download_as_text()


def download_schools(state: str) -> tuple[str, str]:
    """The school extract and the Census places file, from the bucket."""
    schools = _download(
        f"{GCS_PREFIX}/schools_{state}.csv",
        f"{extract_uri(state)} is not in the bucket. Build it with "
        f"scripts/build_school_extract.py {state} and upload it.",
    )
    census = _download(
        f"{GCS_PREFIX}/census_places_{state}.txt",
        f"{places_uri(state)} is not in the bucket. "
        f"scripts/build_school_extract.py {state} writes it too.",
    )
    return schools, census


def load_schools(session: Session, state: str, *, dry_run: bool = False) -> dict:
    """Install a state's schools. Idempotent; existing rows are left alone."""
    from datetime import datetime, timezone
    from io import StringIO

    schools_csv, census_txt = download_schools(state)
    places = read_places(StringIO(census_txt))
    rows = list(read_schools(StringIO(schools_csv), places))
    logger.info(
        "%s: %d school name variants over %d Census places",
        state,
        len(rows),
        len(places),
    )
    if dry_run:
        return {"read": len(rows), "written": 0, "dry_run": 1}

    now = datetime.now(timezone.utc)
    written = 0
    for row in rows:
        session.execute(
            _INSERT,
            {
                **row,
                "id": f"{state}:{row['osm_type']}:{row['osm_id']}",
                "state": state,
                "now": now,
                "tags": "{}",
            },
        )
        written += 1
    session.commit()
    return {"read": len(rows), "written": written, "places": len(places)}
