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

#: MPA contact types that are publications. 2-4 are people and associations.
MPA_PUBLICATIONS = {1, 5, 6, 7}

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


def load_ours(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.id, s.host, s.canonical_name, s.city, s.county,
               coalesce(nullif(trim(s.operator), ''), s.owner) AS owner,
               s.status, s.metadata::jsonb ->> 'state',
               count(a.id) FILTER (
                   WHERE a.publish_date >= %s AND a.publish_date < %s
               ) AS march
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
            "march"]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


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
            "host": host_of(r.get("website")), "owner": r.get("owner") or "",
            "address": ", ".join(
                p for p in (r.get("address"), r.get("city"),
                            f"MO {r.get('zip') or ''}".strip()) if p),
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
        s = 0.0
        if entry["host"] and entry["host"] == o["host"] and entry["host"] in unique_hosts:
            s = 0.97
        elif (same_city or names_town) and mine and theirs and (
            set(mine) <= set(theirs) or set(theirs) <= set(mine)
        ):
            s = 0.9
        elif same_city:
            r = SequenceMatcher(None, " ".join(mine), " ".join(theirs)).ratio()
            s = r if r >= 0.75 else 0.0
        if entry["host"] and entry["host"] == o["host"] and same_city:
            s = max(s, 0.95)
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
    args = ap.parse_args()

    conn = psycopg2.connect(
        host=os.environ.get("DATABASE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATABASE_PORT", "5439")),
        dbname=os.environ.get("DATABASE_NAME", "mizzou"),
        user=os.environ.get("DATABASE_USER", "mizzou_user"),
        password=os.environ["PGPASSWORD"],
    )
    ours = load_ours(conn)
    ours_by_host = {host_of(s["host"]): s for s in ours}

    outlets = []
    for r in csv.DictReader(open(LOOKUPS / "mo_all_news_outlets.csv")):
        o = {
            "outlet": r["outlet"], "city": r["city"], "county": r["county"],
            "host": host_of(r["host"]), "type": r["type"], "owner": r["owner"],
            "web_access": r["web_access"], "lists": set(),
            "_cities": set(), "address": "", "fips": "",
        }
        outlets.append(o)

    hosts = [o["host"] for o in outlets if o["host"]]
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
        if entry["list"] == "mpa" and entry["address"]:
            o["address"] = entry["address"]
        elif not o["address"] and entry["address"]:
            o["address"] = entry["address"]
        o["county"] = o["county"] or entry["county"]
        o["fips"] = o["fips"] or entry.get("fips", "")
        o["host"] = o["host"] or entry["host"]
        o["owner"] = o["owner"] or entry["owner"]

    # OURS IS CANONICAL for an outlet it holds: name, owner, county, status.
    matched_ours = set()
    for o in outlets:
        s = ours_by_host.get(o["host"]) if o["host"] else None
        o["in_sources"] = bool(s)
        o["source_status"] = (s or {}).get("status") or ""
        o["march_articles"] = int((s or {}).get("march") or 0)
        if s:
            matched_ours.add(s["id"])
            o["owner"] = s["owner"] or o["owner"]
            o["county"] = s["county"] or o["county"]
            o["lists"].add("ours")
    for s in ours:
        if s["id"] in matched_ours:
            continue
        outlets.append({
            "outlet": s["name"], "city": s["city"], "county": s["county"],
            "host": host_of(s["host"]), "type": "", "owner": s["owner"] or "",
            "web_access": "collected" if s["march"] else "never collected",
            "lists": {"ours"}, "_cities": set(), "address": "", "fips": "",
            "in_sources": True, "source_status": s["status"] or "",
            "march_articles": int(s["march"] or 0),
        })

    # Blue Book-only outlets have no county: take it from any list that
    # placed the same city.
    city_county = {}
    for o in outlets:
        if o["county"]:
            city_county.setdefault(city_key(o["city"]), county_key(o["county"]))
    for o in outlets:
        o["county"] = county_key(o["county"]) or city_county.get(city_key(o["city"]), "")

    fields = ["outlet", "city", "county", "fips", "address", "host", "type",
              "owner", "in_sources", "source_status", "march_articles",
              "collected_in_march", "web_access", "in_mpa", "in_bluebook",
              "in_lni", "lists"]
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


if __name__ == "__main__":
    main()
