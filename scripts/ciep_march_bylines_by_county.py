"""Count bylines per Missouri county for the March CIEP export.

Inputs:
- ~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Mizzou/CIEP/MO MARCH Final 51826.csv
- /tmp/source_counties.tsv (host\tcounty\tcity from production sources table)

Outputs:
- scripts/ciep_march_bylines_by_county.csv

Columns:
- county
- publications
- articles
- unique_bylines
- byline_mentions
"""

import csv
import os
import re
from collections import defaultdict

MARCH_CSV = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Mizzou/CIEP/"
    "MO MARCH Final 51826.csv"
)
COUNTY_TSV = "/tmp/source_counties.tsv"
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "ciep_march_bylines_by_county.csv")


def normalize_host(host: str) -> str:
    host = (host or "").strip().lower()
    host = re.sub(r"^www\.", "", host)
    return host.split("/")[0]


# host -> county from production
host_to_county: dict[str, str] = {}
with open(COUNTY_TSV, newline="", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if not parts:
            continue
        host = normalize_host(parts[0])
        county = parts[1].strip() if len(parts) > 1 else ""
        if host:
            host_to_county[host] = county

# county aggregations
county_publications: dict[str, set[str]] = defaultdict(set)
county_articles: dict[str, int] = defaultdict(int)
county_unique_bylines: dict[str, set[str]] = defaultdict(set)
county_byline_mentions: dict[str, int] = defaultdict(int)

with open(MARCH_CSV, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        host_raw = (row.get("host") or "").strip()
        host = normalize_host(host_raw)
        county = host_to_county.get(host, "Unknown") or "Unknown"

        county_publications[county].add(host_raw)
        county_articles[county] += 1

        author_field = (row.get("author") or "").strip()
        if not author_field:
            continue

        # Match existing byline report behavior: comma-separated bylines are split
        bylines = [b.strip() for b in author_field.split(",") if b.strip()]
        county_byline_mentions[county] += len(bylines)
        for byline in bylines:
            county_unique_bylines[county].add(byline)

rows = []
for county in set(county_articles) | set(county_publications):
    rows.append(
        {
            "county": county,
            "publications": len(county_publications[county]),
            "articles": county_articles[county],
            "unique_bylines": len(county_unique_bylines[county]),
            "byline_mentions": county_byline_mentions[county],
        }
    )

rows.sort(key=lambda r: (-r["articles"], r["county"].lower()))

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "county",
            "publications",
            "articles",
            "unique_bylines",
            "byline_mentions",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Saved: {OUTPUT_CSV}")
print(f"County rows: {len(rows)}")
print("Top 15 by articles:")
for row in rows[:15]:
    print(
        f"{row['county']:<20} pubs={row['publications']:<3} "
        f"articles={row['articles']:<4} "
        f"unique_bylines={row['unique_bylines']:<4} "
        f"mentions={row['byline_mentions']}"
    )
