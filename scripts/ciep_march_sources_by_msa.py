"""
Map the 176 collected sources to their MSA using production DB county data.
Source data: /tmp/source_counties.tsv (pulled from production via kubectl exec)
  Columns: host TAB county TAB city
Output: ciep_march_sources_by_msa.csv
"""

import csv
import os
import re
from collections import defaultdict
from urllib.parse import urlparse

MARCH_CSV = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Mizzou/CIEP/"
    "MO MARCH Final 51826.csv"
)
PROD_TSV = "/tmp/source_counties.tsv"
OUTPUT = os.path.join(os.path.dirname(__file__), "ciep_march_sources_by_msa.csv")

# ── MSA → county mapping ─────────────────────────────────────────────────────
MSA_MAP = {
    "St. Louis MSA": [
        "St. Louis County", "St. Charles County", "St. Louis City",
        "Jefferson County", "Franklin County", "Lincoln County", "Warren County",
    ],
    "Kansas City MSA": [
        "Jackson County", "Johnson County", "Clay County", "Platte County",
        "Cass County", "Miami County", "Lafayette County", "Ray County",
        "Clinton County", "Bates County", "Caldwell County",
        # Wyandotte County KS is the Kansas City, KS side of the metro
        "Wyandotte County",
    ],
    "Springfield MSA": [
        "Greene County", "Christian County", "Webster County",
        "Polk County", "Dallas County",
    ],
    "Columbia MSA": [
        "Boone County", "Cooper County", "Howard County",
    ],
    "Jefferson City MSA": [
        "Cole County", "Callaway County", "Moniteau County", "Osage County",
    ],
    "Joplin MSA": [
        "Jasper County", "Newton County",
    ],
}

# Cities in Johnson County, Kansas (disambiguate from Johnson County, MO)
JOHNSON_COUNTY_KS_CITIES = {
    "mission", "overland park", "olathe", "lenexa", "shawnee",
    "prairie village", "merriam", "gardner", "de soto", "leawood",
    "spring hill", "edgerton", "stilwell",
}

# Build reverse lookup: normalized county → MSA (periods stripped for flexible matching)
county_to_msa = {}
for msa, counties in MSA_MAP.items():
    for c in counties:
        norm = c.lower().replace(".", "")
        county_to_msa[norm] = msa
        county_to_msa[norm.replace(" county", "").strip()] = msa


def normalize_host(h):
    """Strip www., URL path, and lowercase for consistent matching."""
    h = h.strip().lower()
    h = re.sub(r"^www\.", "", h)
    h = h.split("/")[0]  # strip any path component
    return h


def host_from_url(url):
    """Extract bare hostname (no www.) from a URL."""
    try:
        h = urlparse(url.strip()).netloc or url.strip()
        return re.sub(r"^www\.", "", h).lower()
    except Exception:
        return url.strip().lower()


# ── Load production sources TSV: host → (county, city) ───────────────────────
source_lookup = {}  # normalized host → {county, city}
with open(PROD_TSV, newline="", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            continue
        raw_host = parts[0].strip()
        county = parts[1].strip() if len(parts) > 1 else ""
        city = parts[2].strip() if len(parts) > 2 else ""
        norm = normalize_host(raw_host)
        if norm:
            source_lookup[norm] = {"county": county, "city": city}

# ── Get 176 hosts and their article counts from March data ───────────────────
from collections import Counter
host_counts = Counter()
with open(MARCH_CSV, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        h = row["host"].strip()
        if h:
            host_counts[h] += 1

# ── Build output rows ─────────────────────────────────────────────────────────
rows = []
unmatched = []

for host, count in sorted(host_counts.items(), key=lambda x: (-x[1], x[0])):
    norm = normalize_host(host)
    info = source_lookup.get(norm, {})
    county_raw = info.get("county", "")
    city = info.get("city", "")

    # Determine MSA — handle multi-county entries like "Jasper and Newton"
    msa = None
    county_parts = re.split(r"\s+and\s+|/", county_raw, flags=re.IGNORECASE)
    for part in county_parts:
        c = part.strip().lower().replace(".", "")  # normalize "St Louis" == "St. Louis"
        if not c.endswith(" county"):
            c += " county"
        msa = county_to_msa.get(c) or county_to_msa.get(c.replace(" county", "").strip())
        if msa:
            break

    # Johnson County disambiguation: county appears in both KS (KC MSA) and MO (Non-MSA)
    # Use city to determine which state
    if msa == "Kansas City MSA" and county_raw.strip().lower() in ("johnson", "johnson county"):
        if city.lower() not in JOHNSON_COUNTY_KS_CITIES:
            msa = None  # Johnson County MO → not KC MSA

    if not msa:
        msa = "Non-MSA / Unknown"
        if not info:
            unmatched.append(host)

    rows.append({
        "host": host,
        "county": county_raw,
        "city": city,
        "msa": msa,
        "article_count": count,
    })

# Sort by MSA, then county, then host
rows.sort(key=lambda r: (r["msa"], r["county"], r["host"]))

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["msa", "host", "county", "city", "article_count"])
    writer.writeheader()
    writer.writerows(rows)

print(f"Saved: {OUTPUT}")
print(f"Total sources: {len(rows)}")
print()

# Print by MSA
by_msa = defaultdict(list)
for r in rows:
    by_msa[r["msa"]].append(r)

for msa in list(MSA_MAP.keys()) + ["Non-MSA / Unknown"]:
    grp = by_msa.get(msa, [])
    if grp:
        print(f"\n{msa} ({len(grp)} sources, {sum(r['article_count'] for r in grp)} articles):")
        for r in grp:
            print(f"  {r['host']:<40} {r['county']:<20} {r['article_count']} articles")

if unmatched:
    print(f"\nNot found in sources export ({len(unmatched)}):")
    for h in unmatched:
        print(f"  {h}")
