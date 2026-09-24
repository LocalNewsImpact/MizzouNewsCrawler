"""County-by-county, what each of the four lists says belongs in Missouri.

The four disagree on the unit, the spelling and the county itself, so the
comparison is only honest once each is put on the same axis:

  LNI          carries `county` and a FIPS already.
  MPA          carries a county, but for 11 entries it is a SERVICE AREA --
               "Holt County, Nodaway County, Worth County" -- which is where a
               paper circulates, not where it is. Those are counted in the
               FIRST county named and the full list is kept in a note, because
               dropping them loses the paper and splitting them counts it
               three times.
  Blue Book    carries NO county at all. Every one of its 199 addresses was
               geocoded to a county (Census, Public_AR_Current); where the
               street address would not match, the town centre was used.
  ours         carries a county, and one row is in KANSAS -- Dos Mundos, a
               Kansas City bilingual paper filed in Wyandotte County. It is
               kept, in a row of its own, rather than silently dropped.

A county's four counts are NOT expected to agree. The lists are compiled
differently: the Blue Book counts mastheads, MPA counts member publications,
LNI counts newspapers by its own definition, and ours counts crawlable
domains. The point of the file is the disagreement.
"""

import csv
import json
import os
import re
import sys

#: Where the two documents that are not in this repository are read from.
#: `mopress-*.json` is fetched by datadesk's `fetch_mopress` command and kept
#: in THAT repository under data/sources, which is gitignored on purpose -- it
#: is someone else's data. `book_with_county.json` is this repo's Blue Book
#: extract with a county geocoded onto every address.
S = os.environ.get("MO_SOURCE_DOCS", "./")
REF = "src/enrichment/reference/census_counties.csv"


def norm(county):
    """One spelling of a county name across four lists that punctuate it four ways."""
    c = re.sub(r"\s+County$", "", (county or "").strip(), flags=re.I)
    c = c.replace("St ", "St. ").replace("Ste ", "Ste. ")
    return re.sub(r"\s+", " ", c).strip()


COUNTIES = {}
for row in csv.DictReader(open(REF)):
    if row["USPS"] == "MO":
        name = norm(row["NAME"])
        COUNTIES[name.lower()] = (name, row["GEOID"])


def resolve(county):
    """(name, fips) for a county, taking the first where a service area is listed."""
    first = (county or "").split(",")[0]
    return COUNTIES.get(norm(first).lower(), ("", ""))


def clean(value):
    """One logical row is one physical line: no embedded newline survives."""
    return " ".join(str(value or "").split())


rows = {name: {"county": name, "fips": g} for name, g in COUNTIES.values()}
for r in rows.values():
    r.update({k: [] for k in ("lni", "mpa", "book", "ours")})

# --- Local News Initiative, State of Local News 2025 ------------------------
for r in csv.DictReader(open("src/lookups/mo_lni_newspapers_2025.csv")):
    name, _ = resolve(r["county"])
    if name:
        rows[name]["lni"].append(clean(r["newspaperName"]))
for r in csv.DictReader(open("src/lookups/mo_lni_digital_sites_2025.csv")):
    name, _ = resolve(r["county"])
    if name:
        rows[name]["lni"].append(clean(r["organization"]) + " (digital)")

# --- Missouri Press Association public directory ----------------------------
service_areas = {}
for r in [
    x
    for x in json.load(open(S + "mopress-2026-08-22.json"))["records"]
    if x.get("contact_type") == 1
]:
    name, _ = resolve(r.get("county"))
    if not name:
        continue
    rows[name]["mpa"].append(clean(r["name"]))
    if "," in (r.get("county") or ""):
        service_areas.setdefault(name, []).append(
            f"{clean(r['name'])} [{clean(r['county'])}]"
        )

# --- Missouri Blue Book 2025-2026, geocoded --------------------------------
for r in json.load(open(S + "book_with_county.json")):
    name, _ = resolve(r.get("county"))
    if name:
        rows[name]["book"].append(clean(r["name"]).title())

# --- our production sources table ------------------------------------------
outside = []
for row in csv.reader(open(S + "mizzou_sources.tsv"), delimiter="\t"):
    if len(row) < 9:
        continue
    host, _, cname, city, county, _, _, status, articles = row[:9]
    label = f"{clean(cname) or host}" + ("" if status == "active" else f" [{status}]")
    name, _ = resolve(county)
    if name:
        rows[name]["ours"].append(label)
    else:
        outside.append((county, city, label, host))

out = []
for r in sorted(rows.values(), key=lambda r: r["county"]):
    counts = {k: len(r[k]) for k in ("lni", "mpa", "book", "ours")}
    out.append(
        {
            "county": r["county"],
            "fips": r["fips"],
            "lni_count": counts["lni"],
            "mpa_count": counts["mpa"],
            "bluebook_count": counts["book"],
            "our_count": counts["ours"],
            "max_minus_ours": max(counts.values()) - counts["ours"],
            "all_four_agree": "yes" if len(set(counts.values())) == 1 else "no",
            "lni_newsrooms": "; ".join(sorted(r["lni"])),
            "mpa_newsrooms": "; ".join(sorted(r["mpa"])),
            "bluebook_newsrooms": "; ".join(sorted(r["book"])),
            "our_newsrooms": "; ".join(sorted(r["ours"])),
            "mpa_service_area_note": "; ".join(service_areas.get(r["county"], [])),
        }
    )

path = sys.argv[1]
cols = list(out[0])
with open(path, "w", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
    writer.writeheader()
    writer.writerows(out)

print(f"{len(out)} counties -> {path}")
for k in ("lni", "mpa", "book", "ours"):
    print(f"  {k:<6}{sum(len(r[k]) for r in rows.values()):>5} placed")
if outside:
    print("\noutside Missouri, not in any county row:")
    for county, city, label, host in outside:
        print(f"  {label} ({host}) -- {city}, {county} County")
