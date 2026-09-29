"""Every Missouri news outlet any list knows about, with where it is.

Four lists, one row per outlet:

  ours       the production `sources` table -- CANONICAL for any outlet it
             holds: name, owner, county and state come from here
  MPA        Missouri Press Association directory (datadesk data/sources)
  Blue Book  Secretary of State Official Manual, newspapers 2025-2026
  LNI        Northwestern Local News Initiative, newspapers + digital 2025

The outlet set starts from `src/lookups/mo_all_news_outlets.csv`, the
deduplicated union built on 2026-09-24, which also carries what is known
about outlets we do not crawl (print or replica only, website gone, not
local news). Each list is matched onto it by domain within a city, else by
name within a city; an entry that matches nothing is added as a new outlet.

The address is the MPA's (street, city, zip), else the Blue Book's. LNI
carries no street address.

Output: src/lookups/mo_outlet_registry.csv, one row per outlet, with the
lists it appears in and its March 2026 article count.

IDENTITY. `outlet_id` is the outlet's `sources.id` where we hold it. An
outlet we do not hold is given a new UUID the first time it appears and
keeps it on every rebuild, read back from the previous file; if it is added
to `sources` later, that UUID is the id it takes.

REVIEW IS KEPT, EVIDENCE IS DERIVED. `status`, `merged_into`,
`status_basis`, `reviewed_by` and `reviewed_at` are a person's answer and
are carried across rebuilds untouched. `signals` is recomputed every run:
the evidence that an outlet may have closed, merged or moved -- no recent
articles, retired in our sources, a website shared with other nameplates,
a closure note in the 2025 working sheet. A signal is a question, never a
status. See docs/MO_OUTLET_REGISTRY.md.

LOCATION. `address_basis` says where the street address came from (mpa,
bluebook) or that there is none yet; `lat`/`lon` are the town's centroid
from the Census places file, so every outlet can be mapped while street
addresses are still being filled.

    DATABASE_HOST=127.0.0.1 DATABASE_PORT=5439 DATABASE_NAME=mizzou \\
    DATABASE_USER=mizzou_user PGPASSWORD=... \\
    python scripts/build_mo_outlet_registry.py \\
        --mpa ../../datadesk/data/sources/mopress-2026-08-22.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
LOOKUPS = ROOT / "src" / "lookups"
DATASET = "Mizzou-Missouri-State"
MARCH = ("2026-03-01", "2026-04-01")
#: Where datadesk imports each rebuild from. A rebuild is data: a newly tagged
#: link or a renamed source reaches the map without a pull request. A
#: reviewer's word on an outlet is an outlet event in datadesk, laid over it.
PUBLISH_TO = "gs://mizzou-news-maps-data/registry/mo_outlet_registry.csv"

#: MPA contact types that are publications. 2-4 are people and associations.
MPA_PUBLICATIONS = {1, 5, 6, 7}

#: What the MPA directory writes where it has no owner. 82 of its records say
#: "Independently Owned Newspaper", which is a description, not a name; read
#: as an owner it outranks the Blue Book publisher that does name one.
NOT_AN_OWNER = {"independently owned newspaper", "ownership information not listed"}


def owner_of(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value.lower() in NOT_AN_OWNER else value

_STOP = {"the", "and", "of", "a", "online", "member", "news"}


def host_of(url: str | None) -> str:
    """`http://www.myleaderpaper.com/` -> `myleaderpaper.com`, path kept
    where it names a nameplate (`columbiamissourian.com/boonecountyjournal`)."""
    if not url or url.strip().lower() in {"none", "n/a", ""}:
        return ""
    text = re.sub(r"^[a-z]+://", "", url.strip().lower())
    text = text.split("?")[0].split("#")[0].rstrip("/")
    text = re.sub(r"^www\.", "", text)
    return text


#: Hosts that belong to a platform, not a publisher. Two outlets whose only
#: web presence is a Facebook page do not share a website, and a host like
#: this can never match one outlet to another.
PLATFORM_HOSTS = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "linktr.ee", "sites.google.com", "google.com", "wixsite.com", "blogspot.com",
    "wordpress.com", "pressreader.com", "issuu.com", "iclassifiedsnetwork.com",
    "audacy.com", "mytuner-radio.com", "radiolineup.com", "chambermaster.com",
)


#: Platforms that are social media: an outlet whose only web presence is one
#: of these publishes there rather than on a site we can collect from.
SOCIAL_HOSTS = ("facebook.com", "instagram.com", "twitter.com", "x.com",
                "youtube.com", "linktr.ee")


def is_social(host: str) -> bool:
    domain = (host or "").split("/")[0]
    return any(domain == p or domain.endswith("." + p) for p in SOCIAL_HOSTS)


def is_platform(host: str) -> bool:
    domain = (host or "").split("/")[0]
    return any(domain == p or domain.endswith("." + p) for p in PLATFORM_HOSTS)


def name_key(name: str | None) -> str:
    text = re.sub(r"\bsaint\b", "st", (name or "").lower())
    words = re.sub(r"[^a-z0-9 ]+", " ", text).split()
    return " ".join(w for w in words if w not in _STOP)


def city_key(city: str | None) -> str:
    return re.sub(r"[^a-z]+", "", (city or "").lower().replace("saint", "st"))


def county_key(county: str | None) -> str:
    return re.sub(r"\s+county$", "", (county or "").strip(), flags=re.I)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, name_key(a), name_key(b)).ratio()



#: Statuses that take an outlet off the map: its work is counted elsewhere,
#: it has stopped, or it is not a local newsroom.
OFF_MAP = ("merged", "duplicate", "closed", "not_local_news", "legal", "shopper",
           "business", "magazine")

#: Statuses that map as print, replica or social: a reviewer's word for an
#: outlet whose readers get it on paper, as a page image, or on Facebook.
#: The basis of a status copied from our sources table rather than reviewed.
SOURCES_BASIS = "sources table"

PRINT_LIKE = ("print_only", "print", "replica", "facebook", "social")

#: Reviewer columns: a person's answer, carried across rebuilds untouched.
REVIEW = ["status", "merged_into", "status_basis", "reviewed_by", "reviewed_at", "aka"]

#: Towns the lists name without a county.
TOWN_COUNTY = {"charleston": "Mississippi", "carljunction": "Jasper", "albany": "Gentry"}

#: A 2025 working-sheet note that says an outlet may be gone or print-only.
SHEET_SIGNAL = re.compile(
    r"no longer publish|closed|site not live|no longer active|e-edition only|"
    r"pdf only|print only|no news content|different website",
    re.I,
)


def load_previous(path: Path):
    """The last build's rows, so identity and review survive a rebuild.

    Keyed by what the builder computes, not by what the file shows: a row a
    reviewer renamed ("Newton County News, Neosho" to "Newton County News")
    is written under its corrected name and looked up under the one the
    lists give it. Reading the corrected name back lost the row's UUID and
    its review on the next rebuild."""
    if not path.exists():
        return {}, {}
    was = {}
    over = LOOKUPS / "mo_outlet_overrides.csv"
    if over.exists():
        for o in csv.DictReader(open(over)):
            was.setdefault(o["outlet_id"], {})[o["field"]] = o.get("was", "")
    by_source, by_name = {}, {}
    for r in csv.DictReader(open(path)):
        for field, value in was.get(r["outlet_id"], {}).items():
            if field in ("outlet", "city"):
                r = {**r, field: value}
        if r.get("source_id"):
            by_source[r["source_id"]] = r
        by_name[(name_key(r["outlet"]), city_key(r["city"]), r.get("source_id", ""))] = r
    return by_source, by_name


#: Fields a reviewer may correct on an outlet the builder would otherwise
#: recompute from our sources or the lists. Applied last, so a rebuild keeps
#: them. An outlet we hold is corrected in `sources`, not here.
OVERRIDABLE = ("outlet", "city", "county", "host", "owner", "address")


def load_overrides():
    """{outlet_id: {field: value}} from mo_outlet_overrides.csv."""
    path = LOOKUPS / "mo_outlet_overrides.csv"
    out = {}
    if path.exists():
        for r in csv.DictReader(open(path)):
            if r["field"] in OVERRIDABLE:
                out.setdefault(r["outlet_id"], {})[r["field"]] = r["value"]
    return out


def load_added():
    """Outlets a reviewer added that no list holds: mo_outlets_added.csv.

    Each carries its own outlet_id, minted once, and joins the outlet set
    before the lists are matched, like one of our own."""
    path = LOOKUPS / "mo_outlets_added.csv"
    return list(csv.DictReader(open(path))) if path.exists() else []


def hosts_of_ours(ours):
    """{host: source} for every website a source of ours is known by.

    Its own, and those it moved from: a paper that changes domain is the
    same paper, and the lists still name it at the old one. The Licking
    News moved to thelickingnews.net in 2025 and the lists' .com entry
    came back as a second outlet (2026-09-29). A host a source holds now
    wins over one another source has left.
    """
    found = {}
    for s in ours:
        for old in s.get("previous_hosts") or ():
            found.setdefault(host_of(old), s)
    for s in ours:
        found[host_of(s["host"])] = s
    return found


def standing_status(o):
    """Take the status `sources` gives an outlet we hold, unless reviewed.

    A status copied from `sources` last time is a copy, not a review, so it
    is copied again: the table may have changed since.
    """
    copied = o.get("status_basis", "") in ("", SOURCES_BASIS)
    if o.get("source_status") and (not o.get("status") or copied):
        o["status"] = o["source_status"]
        o["status_basis"] = SOURCES_BASIS
    return o


def attach_added(outlets, added, ours_by_host):
    """Join each reviewer-added outlet to the outlet set.

    An added outlet whose website is now one of our sources is that source,
    not a second outlet beside it: an outlet with a live website is added to
    `sources` for crawling, and the registry then drew it twice (StoneCounty
    .news, 2026-09-28). It joins the source's row instead, which keeps the
    source's id, and hands over the status its reviewer gave it.
    """
    by_source = {o.get("source_id"): o for o in outlets if o.get("source_id")}
    for a in added:
        s = ours_by_host.get(host_of(a["host"])) if a.get("host") else None
        held = by_source.get(s["id"]) if s else None
        if held is not None:
            held["lists"].add("added")
            if a.get("status") and not held.get("_added_status"):
                held["_added_status"] = a["status"]
                held["_added_basis"] = a.get("status_basis", "")
            continue
        outlets.append({
            "outlet": a["outlet"], "city": a["city"], "county": a["county"],
            "host": host_of(a["host"]), "type": a.get("type", ""),
            "owner": a.get("owner", ""), "web_access": a.get("web_access", ""),
            "lists": {"added"}, "_cities": set(), "fips": "",
            "address": a.get("address", ""),
            "_address_from": "added" if a.get("address") else "",
            "_added_id": a["outlet_id"],
            "_added_status": a.get("status", ""),
            "_added_basis": a.get("status_basis", ""),
        })


def load_facilities():
    """{website: primary FCC facility} from mo_broadcast_facilities.csv.

    Where a broadcaster is licensed to transmit -- the FCC's point, not a
    studio and not the licensee's office, which for a group-owned station is
    its headquarters out of state. Kept in columns of its own beside the
    street address and the town."""
    path = LOOKUPS / "mo_broadcast_facilities.csv"
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(path)):
        entry = out.setdefault(r["host"], {"calls": [], "primary": None})
        entry["calls"].append(r["call_sign"])
        if r["primary"] == "yes":
            entry["primary"] = r
    return out


def _address_town(address: str) -> str:
    """The town in a one-line address: the last part, with the state and ZIP off.

    "7777 Bonhomme Ave., Ste. 1205, St. Louis 63105" -> "St. Louis"."""
    if not address:
        return ""
    last = address.split(",")[-1]
    # "PO Box 128 Warsaw 63555" -- a box written into the town's part.
    last = re.sub(r"(?i)\bp\.?\s*o\.?\s*box\s+\d+", "", last)
    last = re.sub(r"\b(MO|Missouri)\b", "", last)
    last = re.sub(r"\d{5}(-\d{4})?", "", last)
    return last.strip(" .")


def load_county_fips():
    """{(state, county name key): 5-digit FIPS}, every state.

    Keyed by state because a county name is not unique: Johnson County is in
    Missouri and in Kansas, and KMBZ is in the Kansas one."""
    out = {}
    for r in csv.DictReader(open(ROOT / "src/enrichment/reference/census_counties.csv")):
        key = "st louis city" if r["GEOID"] == "29510" else _county_key(r["NAME"])
        out[(r["USPS"], key)] = r["GEOID"]
    return out


def _county_key(name: str) -> str:
    name = re.sub(r"(?i)\s+county$", "", (name or "").strip())
    name = re.sub(r"(?i)^saint\b", "St", name)
    return re.sub(r"[^a-z ]", "", name.lower().replace("ste.", "ste ")).strip()


def county_fips(county: str, city: str, fips: dict, state: str = "MO") -> str:
    """A county's FIPS. St. Louis city is its own county-equivalent: an
    outlet in the city whose county reads "St. Louis" is 29510, not the
    county's 29189."""
    # A service area lists several ("Clay County, Ray"): the first is home.
    key = _county_key((county or "").split(",")[0])
    if state == "MO" and (
        key in ("st louis city", "city of st louis")
        or (key == "st louis" and city_key(city) == "stlouis")
    ):
        return fips.get(("MO", "st louis city"), "")
    return fips.get((state, key), "")


def load_places():
    """Missouri town centroids, keyed by town."""
    places = {}
    for r in csv.DictReader(open(ROOT / "src/enrichment/reference/census_places.csv")):
        town = re.sub(r"\s+(city|town|village|CDP)$", "", r["NAME"], flags=re.I)
        places.setdefault((r["USPS"], city_key(town)), (r["INTPTLAT"], r["INTPTLONG"]))
    return places


def load_sheet_notes(path: Path | None):
    """{host or name key: note} from the 2025 working sheet's notes."""
    notes = {}
    if not path or not path.exists():
        return notes
    for r in csv.DictReader(open(path)):
        note = " ".join(
            r.get(k) or "" for k in ("working", "developer_notes", "journalism_notes")
        ).strip()
        if not SHEET_SIGNAL.search(note):
            continue
        if r.get("host"):
            notes[host_of(r["host"])] = note
        notes[name_key(r["name"])] = note
    return notes


def load_ours(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.id, s.host, s.canonical_name, s.city, s.county,
               coalesce(nullif(trim(s.operator), ''), s.owner) AS owner,
               s.status, s.metadata::jsonb ->> 'state',
               count(a.id) FILTER (
                   WHERE a.publish_date >= %s AND a.publish_date < %s
               ) AS march,
               max(a.publish_date)::date AS newest,
               s.metadata::jsonb AS meta
          FROM sources s
          JOIN dataset_sources ds ON ds.source_id = s.id
          JOIN datasets d ON d.id = ds.dataset_id AND d.slug = %s
          LEFT JOIN candidate_links cl ON cl.source_id = s.id
               AND cl.dataset_id = d.id
          LEFT JOIN articles a ON a.candidate_link_id = cl.id
         GROUP BY s.id
        """,
        (MARCH[0], MARCH[1], DATASET),
    )
    cols = ["id", "host", "name", "city", "county", "owner", "status", "state",
            "march", "newest", "meta"]
    rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    for r in rows:
        meta = r.pop("meta") or {}
        r["address"] = _stored_address(meta, r["city"])
        r["previous_hosts"] = list(meta.get("previous_hosts") or [])
    return rows


def _stored_address(meta, city):
    """The street address our sources table already holds, as one line.

    TRUSTED OVER EVERY LIST. Two spellings are in use: `address1`/`address2`
    with `zip`, and a single `address` with `zip_code`."""
    street = ", ".join(
        p.strip()
        for p in (meta.get("address1"), meta.get("address2"), meta.get("address"))
        if p and str(p).strip()
    )
    if not street:
        return ""
    zipcode = (meta.get("zip") or meta.get("zip_code") or "").strip()
    # The source's own town field first: metadata can hold an older one
    # (KMBZ's said Kansas City; its street is in Mission).
    place = (city or meta.get("city") or "").strip()
    state = (meta.get("state") or "MO").strip()
    return ", ".join(p for p in (street, place, f"{state} {zipcode}".strip()) if p)


def load_lists(mpa_path: Path):
    lists = []
    mpa = json.load(open(mpa_path))["records"]
    for r in mpa:
        if r.get("contact_type") not in MPA_PUBLICATIONS:
            continue
        if r["name"].strip().lower() == "test organization":
            continue
        lists.append({
            "list": "mpa", "name": re.sub(r"\s*\(Online Member\)", "", r["name"]),
            "city": r.get("city"), "county": county_key(r.get("county")),
            "host": host_of(r.get("website")), "owner": owner_of(r.get("owner")),
            # A record with no street and no town has no address: "MO" alone
            # is not one, and it blocked the Blue Book's from filling the gap.
            "address": ", ".join(
                p for p in (r.get("address"), r.get("city"),
                            f"MO {r.get('zip') or ''}".strip()) if p)
            if (r.get("address") or r.get("city")) else "",
        })
    for r in csv.DictReader(open(LOOKUPS / "mo_bluebook_newspapers_2025_2026.csv")):
        lists.append({
            "list": "bluebook", "name": r["name"].title(), "city": r["city"],
            "county": "", "host": host_of(r["host"] or r["url"]),
            "owner": r.get("publisher") or "", "address": r.get("address") or "",
        })
    for r in csv.DictReader(open(LOOKUPS / "mo_lni_newspapers_2025.csv")):
        lists.append({
            "list": "lni", "name": r["newspaperName"], "city": r["city"],
            "county": county_key(r["county"]), "host": "",
            "owner": r.get("ownerName") or "", "address": "",
            "fips": r.get("fips") or "",
        })
    for r in csv.DictReader(open(LOOKUPS / "mo_lni_digital_sites_2025.csv")):
        lists.append({
            "list": "lni", "name": r["organization"], "city": r["city"],
            "county": county_key(r["county"]), "host": host_of(r["website"]),
            "owner": r.get("publisher") or "", "address": "",
            "fips": r.get("fips") or "",
        })
    return lists


def _tokens(name, *cities):
    """Name words without the town's own: "Greenfield Vedette" is "vedette"."""
    drop = set()
    for city in cities:
        drop.update(re.sub(r"[^a-z0-9 ]+", " ", (city or "").lower()).split())
    return [w for w in name_key(name).split() if w not in drop]


def _same_city(a, b):
    a, b = city_key(a), city_key(b)
    return bool(a and b) and (a == b or SequenceMatcher(None, a, b).ratio() >= 0.85)


def match(entry, outlets, unique_hosts):
    """The outlet a list entry names, or None.

    In order of confidence: a website no other outlet shares; the same name
    in the same town, where one name may add or drop the town ("Vedette",
    "Greenfield Vedette") or be contained in the other; a close name in the
    same town; the same distinctive name with the list's office town named
    inside it ("Marble Hill Banner Press", listed at Cape Girardeau).
    """
    best, score = None, 0.0
    for o in outlets:
        cities = [entry["city"], o["city"]]
        mine, theirs = _tokens(entry["name"], *cities), _tokens(o["outlet"], *cities)
        same_city = _same_city(entry["city"], o["city"]) or any(
            _same_city(entry["city"], c) for c in o["_cities"]
        )
        names_town = city_key(o["city"]) and city_key(o["city"]) in city_key(
            entry["name"]
        )
        # A name the outlet is also known as -- recorded on its own row, so a
        # list using an old name ("Moberly Monitor-Index") finds the paper
        # rather than making a second row for it.
        if any(similar(entry["name"], a) >= 0.85 for a in o.get("_aka", ())):
            if 0.96 > score:
                best, score = o, 0.96
            continue
        s = 0.0
        # A shared website is not a shared newsroom: Cole Camp Courier and
        # Lincoln New Era are two nameplates on one publisher's site, and
        # matching on the site alone folded both into the paper beside
        # them. The site counts with the town or a similar name.
        if (
            entry["host"]
            and entry["host"] == o["host"]
            and entry["host"] in unique_hosts
            and (
                same_city
                or SequenceMatcher(None, " ".join(mine), " ".join(theirs)).ratio()
                >= 0.6
            )
        ):
            s = 0.97
        elif (same_city or names_town) and mine and theirs and (
            set(mine) <= set(theirs) or set(theirs) <= set(mine)
        ):
            s = 0.9
        elif same_city:
            r = SequenceMatcher(None, " ".join(mine), " ".join(theirs)).ratio()
            s = r if r >= 0.75 else 0.0
        if (
            entry["host"]
            and not is_platform(entry["host"])
            and entry["host"] == o["host"]
            and same_city
        ):
            s = max(s, 0.95)
        # The same website and one name inside the other is one paper, whatever
        # town each list files it under: the Blue Book's "Lake Sun" at
        # Camdenton is our "Lake Sun Leader/Lake News Online" at Osage Beach,
        # both on lakenewsonline.com.
        if (
            entry["host"]
            and not is_platform(entry["host"])
            and entry["host"] == o["host"]
            and mine
            and theirs
            and (set(mine) <= set(theirs) or set(theirs) <= set(mine))
        ):
            s = max(s, 0.93)
        # The same distinctive name in two towns is one paper listed at its
        # office in one list and its town in another: Morgan County Statesman
        # at Versailles and at Stover.
        if len(mine) >= 2 and mine == theirs:
            s = max(s, 0.85)
        if s > score:
            best, score = o, s
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mpa", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=LOOKUPS / "mo_outlet_registry.csv")
    ap.add_argument(
        "--sheet-2025",
        type=Path,
        default=LOOKUPS / "mo_working_urls_2025.csv",
        help="the 2025 working sheet's Working URLs tab, for closure notes",
    )
    ap.add_argument(
        "--publish",
        action="store_true",
        help=f"upload the registry to {PUBLISH_TO} for datadesk to import",
    )
    args = ap.parse_args()

    conn = psycopg2.connect(
        host=os.environ.get("DATABASE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATABASE_PORT", "5439")),
        dbname=os.environ.get("DATABASE_NAME", "mizzou"),
        user=os.environ.get("DATABASE_USER", "mizzou_user"),
        password=os.environ["PGPASSWORD"],
    )
    ours = load_ours(conn)
    # Exact host strings, platforms included: our own rows carry these, and
    # "audacy.com" against "audacy.com/971talk" is already two stations.
    ours_by_host = hosts_of_ours(ours)

    outlets = []
    for r in csv.DictReader(open(LOOKUPS / "mo_all_news_outlets.csv")):
        o = {
            "outlet": r["outlet"], "city": r["city"], "county": r["county"],
            "host": host_of(r["host"]), "type": r["type"], "owner": r["owner"],
            "web_access": r["web_access"], "lists": set(),
            "_cities": set(), "address": "", "fips": "",
        }
        outlets.append(o)

    # OURS IS CANONICAL for an outlet it holds: name, owner, county, status.
    matched_ours = set()
    for o in outlets:
        s = ours_by_host.get(o["host"]) if o["host"] else None
        o["in_sources"] = bool(s)
        o["source_id"] = (s or {}).get("id") or ""
        o["_source_name"] = (s or {}).get("name") or ""
        o["source_status"] = (s or {}).get("status") or ""
        o["march_articles"] = int((s or {}).get("march") or 0)
        o["newest"] = (s or {}).get("newest") or ""
        if s:
            matched_ours.add(s["id"])
            o["owner"] = s["owner"] or o["owner"]
            o["state"] = (s.get("state") or "MO").strip() or "MO"
            o["county"] = s["county"] or o["county"]
            o["_source_city"] = s["city"] or ""
            o["_source_host"] = host_of(s["host"])
            o["lists"].add("ours")
            if s["address"]:
                o["address"], o["_address_from"] = s["address"], "sources"
    for s in ours:
        if s["id"] in matched_ours:
            continue
        outlets.append({
            "outlet": s["name"], "city": s["city"], "county": s["county"],
            "host": host_of(s["host"]), "type": "", "owner": s["owner"] or "",
            "web_access": "collected" if s["march"] else "never collected",
            "lists": {"ours"}, "_cities": set(), "fips": "",
            "in_sources": True, "source_status": s["status"] or "",
            "march_articles": int(s["march"] or 0),
            "source_id": s["id"], "newest": s.get("newest") or "",
            "state": (s.get("state") or "MO").strip() or "MO",
            "_source_name": s["name"] or "",
            "address": s["address"],
            "_address_from": "sources" if s["address"] else "",
        })

    attach_added(outlets, load_added(), ours_by_host)

    # Aliases a reviewer recorded, attached before any list is matched.
    early_by_source, early_by_name = load_previous(args.out)
    for o in outlets:
        before = early_by_source.get(o.get("source_id") or "") or early_by_name.get(
            (name_key(o["outlet"]), city_key(o["city"]), o.get("source_id") or "")
        )
        o["_aka"] = [a.strip() for a in ((before or {}).get("aka") or "").split(";") if a.strip()]

    hosts = [o["host"] for o in outlets if o["host"] and not is_platform(o["host"])]
    unique_hosts = {h for h in hosts if hosts.count(h) == 1}
    unmatched = []
    for entry in load_lists(args.mpa):
        o = match(entry, outlets, unique_hosts)
        if o is None:
            o = {
                "outlet": entry["name"], "city": entry["city"],
                "county": entry["county"], "host": entry["host"], "type": "",
                "owner": entry["owner"], "web_access": "not yet reviewed",
                "lists": set(), "_cities": set(), "address": "", "fips": "",
            }
            outlets.append(o)
            unmatched.append(entry)
        o["lists"].add(entry["list"])
        o["_cities"].add(city_key(entry["city"]))
        # Our table's address is never replaced; the lists fill a gap only.
        if o.get("_address_from") == "sources":
            pass
        elif entry["list"] == "mpa" and entry["address"]:
            o["address"] = entry["address"]
            o["_address_from"] = "mpa"
        elif not o["address"] and entry["address"]:
            o["address"] = entry["address"]
            o["_address_from"] = entry["list"]
        o["county"] = o["county"] or entry["county"]
        o["fips"] = o["fips"] or entry.get("fips", "")
        o["host"] = o["host"] or entry["host"]
        o["owner"] = o["owner"] or entry["owner"]

    # Blue Book-only outlets have no county: take it from any list that
    # placed the same city.
    city_county = {}
    for o in outlets:
        if o["county"]:
            city_county.setdefault(city_key(o["city"]), county_key(o["county"]))
    for o in outlets:
        o["county"] = county_key(o["county"]) or city_county.get(city_key(o["city"]), "")

    import uuid

    previous_by_source, previous_by_name = load_previous(args.out)
    places = load_places()
    fips_of = load_county_fips()
    facilities = load_facilities()
    sheet = load_sheet_notes(args.sheet_2025)
    host_count = {}
    for o in outlets:
        if o["host"] and not is_platform(o["host"]):
            host_count[o["host"]] = host_count.get(o["host"], 0) + 1
    same_name = {}
    for o in outlets:
        key = (name_key(o["outlet"]), city_key(o["city"]))
        same_name[key] = same_name.get(key, 0) + 1
    today = str(__import__("datetime").date.today())
    stale_before = str(
        __import__("datetime").date.today() - __import__("datetime").timedelta(days=90)
    )
    # ONE ROW PER UUID. Several nameplates can share one of our sources --
    # one website, several papers -- and each carries that source as
    # `source_id`. The source's own UUID goes to the nameplate its name
    # matches best; the rest are outlets of their own and get their own.
    holder = {}
    for o in outlets:
        # An outlet first seen in a list holds none of our fields.
        o.setdefault("source_id", "")
        o.setdefault("newest", "")
        o.setdefault("in_sources", False)
        o.setdefault("source_status", "")
        o.setdefault("march_articles", 0)
        sid = o["source_id"]
        if not sid:
            continue
        score = similar(o["outlet"], o.get("_source_name", ""))
        if sid not in holder or score > holder[sid][0]:
            holder[sid] = (score, id(o))
    for o in outlets:
        holds = o["source_id"] and holder[o["source_id"]][1] == id(o)
        # THE PRODUCTION RECORD NAMES AND PLACES THE OUTLET IT IS. The list
        # this starts from is a snapshot, and a correction made in `sources`
        # never reached a row it seeded: the Wayne County Journal-Banner kept
        # "WayNe" and a town in Reynolds County, so its dot sat in the wrong
        # county (2026-09-28). Only for the nameplate holding the source: the
        # others sharing its website keep their own names and towns.
        if holds:
            o["outlet"] = o.get("_source_name") or o["outlet"]
            o["city"] = o.get("_source_city") or o["city"]
            # And its website: a list may still name a domain it has left.
            o["host"] = o.get("_source_host") or o["host"]
        before = previous_by_name.get(
            (name_key(o["outlet"]), city_key(o["city"]), o["source_id"])
        )
        if holds:
            before = previous_by_source.get(o["source_id"]) or before
        o["outlet_id"] = (
            o["source_id"]
            if holds
            else o.get("_added_id") or (before or {}).get("outlet_id") or str(uuid.uuid4())
        )
        if (before or {}).get("outlet_id") == o["source_id"] and not holds:
            o["outlet_id"] = str(uuid.uuid4())
        for k in REVIEW:
            o[k] = (before or {}).get(k, "")
        # An added outlet starts with the status it was added under.
        if not o["status"] and o.get("_added_status"):
            o["status"], o["status_basis"] = o["_added_status"], o.get("_added_basis", "")
        # Where we hold the outlet, our table's status is the standing answer
        # until somebody reviews it -- and it stays the answer: a status the
        # last build copied from `sources` follows `sources`, not the last
        # build. Carried forward as if a reviewer had said it, five radio
        # stations ruled "not local news" in `sources` stayed "retired" here
        # (2026-09-29). A reviewer's status has a basis of its own and wins.
        standing_status(o)
        if o["county"]:
            o["county_basis"] = "listed"
        elif city_key(o["city"]) in TOWN_COUNTY:
            o["county"], o["county_basis"] = TOWN_COUNTY[city_key(o["city"])], "town"
        elif (town := _address_town(o["address"])) and city_county.get(city_key(town)):
            # The office's town, from the street address: "107 E. Main St.,
            # PO Box 128, Warsaw 65355" is Benton County. The office is the
            # publisher's, not always in the paper's own town.
            o["county"], o["county_basis"] = city_county[city_key(town)], "address"
        else:
            o["county_basis"] = "missing"
        o["address_basis"] = o.pop("_address_from", "") or ("missing" if not o["address"] else "list")
        lat, lon = places.get((o.get("state") or "MO", city_key(o["city"])), ("", ""))
        o["lat"], o["lon"] = lat, lon
        o["county_fips"] = county_fips(o["county"], o["city"], fips_of, o.get("state") or "MO")
        o["location_basis"] = "town centroid" if lat else "missing"
        fac = facilities.get(o["host"]) or {}
        primary = fac.get("primary") or {}
        o["fcc_call_signs"] = ";".join(fac.get("calls") or [])
        o["fcc_facility_id"] = primary.get("facility_id", "")
        o["fcc_community"] = (
            f"{primary.get('community', '')}, {primary.get('state', '')}" if primary else ""
        )
        o["tx_lat"] = primary.get("tx_lat", "")
        o["tx_lon"] = primary.get("tx_lon", "")
        signals = []
        if o["in_sources"] and o["source_status"] == "active" and not o["newest"]:
            signals.append("active but never collected")
        elif o["in_sources"] and o["newest"] and str(o["newest"]) < stale_before:
            signals.append(f"no articles since {o['newest']}")
        if o["source_status"] in ("retired", "paused"):
            signals.append(f"{o['source_status']} in sources")
        twins = same_name.get((name_key(o["outlet"]), city_key(o["city"])), 0)
        if twins > 1:
            signals.append(f"possible duplicate: {twins} rows with this name here")
        if o["host"] and host_count.get(o["host"], 0) > 1:
            signals.append(f"website shared with {host_count[o['host']] - 1} other outlet(s)")
        note = sheet.get(o["host"]) or sheet.get(name_key(o["outlet"]))
        if note:
            signals.append(f"2025 sheet: {note[:120]}")
        if o["web_access"] in ("website gone", "print or replica only", "no web edition"):
            signals.append(o["web_access"])
        o["signals"] = "; ".join(signals)
        # WHAT A MAP DRAWS. One point per surviving outlet: a merged or
        # duplicate row's work is counted at the outlet it points to, a
        # closed one is gone, and not-local-news is not a newsroom. An
        # also-known-as name is already the same row.
        # A legal-notice publication is its own category, and never mapped:
        # the Daily Records, the Countians, a legal ledger carry notices,
        # not local reporting.
        status = (o["status"] or "").strip().lower()
        # A reviewer's status wins over the 2026-09-24 web-access note.
        off = status in OFF_MAP or (not status and o["web_access"] == "not local news")
        o["map"] = "no" if off else "yes"
        # FIVE POINT COLOURS. A reviewer's word first -- print, replica,
        # social -- then what we collected, then what the lists say.
        if status in ("legal", "shopper", "business", "magazine"):
            o["map_category"] = status
        elif off:
            o["map_category"] = ""
        elif status in ("print", "print_only"):
            o["map_category"] = "print"
        elif status == "replica":
            o["map_category"] = "replica"
        elif status in ("facebook", "social") or (
            not o["march_articles"] and is_social(o["host"])
        ):
            o["map_category"] = "social"
        elif o["march_articles"]:
            o["map_category"] = "collected"
        elif o["web_access"] in ("print or replica only", "no web edition"):
            o["map_category"] = "print"
        else:
            o["map_category"] = "not collected"
    del today

    overrides = load_overrides()
    for o in outlets:
        for field, value in overrides.get(o["outlet_id"], {}).items():
            o[field] = value
            if field == "address":
                o["address_basis"] = "reviewer"
            if field == "county":
                o["county_basis"] = "reviewer"
            if field == "city":
                # The town's point follows a corrected town.
                lat, lon = places.get((o.get("state") or "MO", city_key(value)), ("", ""))
                o["lat"], o["lon"] = lat, lon
                o["location_basis"] = "town centroid" if lat else "missing"

    for o in outlets:
        # An override can move an outlet's county; its FIPS follows.
        o["county_fips"] = county_fips(o["county"], o["city"], fips_of, o.get("state") or "MO")

    for o in outlets:
        o["state"] = o.get("state") or "MO"

    fields = ["outlet_id", "source_id", "outlet", "state", "city", "county", "county_basis",
              "fips", "address", "address_basis", "lat", "lon", "location_basis",
              "fcc_call_signs", "fcc_facility_id", "fcc_community", "tx_lat", "tx_lon",
              "host", "type", "owner", "in_sources", "source_status",
              "march_articles", "collected_in_march", "newest", "web_access",
              "in_mpa", "in_bluebook", "in_lni", "lists", "signals", *REVIEW,
              "map", "map_category", "county_fips"]
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for o in sorted(outlets, key=lambda o: (o["county"] or "~", o["outlet"])):
            w.writerow({
                **{k: o.get(k, "") for k in fields},
                "in_sources": "yes" if o["in_sources"] else "no",
                "collected_in_march": "yes" if o["march_articles"] else "no",
                "in_mpa": "yes" if "mpa" in o["lists"] else "no",
                "in_bluebook": "yes" if "bluebook" in o["lists"] else "no",
                "in_lni": "yes" if "lni" in o["lists"] else "no",
                "lists": ";".join(sorted(o["lists"])),
            })
    print(f"outlets {len(outlets)}  new from the lists {len(unmatched)}  -> {args.out}")
    if args.publish:
        print(f"published -> {publish(args.out)}")


def publish(path, to=PUBLISH_TO):
    """Upload the registry where datadesk's import reads it. Returns `to`."""
    from google.cloud import storage

    bucket, _, blob = to[5:].partition("/")
    storage.Client().bucket(bucket).blob(blob).upload_from_filename(
        str(path), content_type="text/csv"
    )
    return to


if __name__ == "__main__":
    main()
