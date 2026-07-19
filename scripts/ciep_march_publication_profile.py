"""Build publication profile report for March CIEP data.

Output columns:
- host
- articles
- unique_bylines
- newsroom_type
- frequency

Data sources:
- scripts/ciep_march_pub_byline_counts.csv
- sources/mizzou_all_sources_export.csv
- /tmp/source_type_freq.tsv (optional production fallback: host\ttype\tfrequency)
"""

import csv
import os
from urllib.parse import urlparse

COUNTS_CSV = os.path.join(os.path.dirname(__file__), "ciep_march_pub_byline_counts.csv")
SOURCES_CSV = os.path.join(os.path.dirname(__file__), "../sources/mizzou_all_sources_export.csv")
PROD_TSV = "/tmp/source_type_freq.tsv"
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "ciep_march_publication_profile.csv")


def normalize_host(value: str) -> str:
    host = (value or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split("/")[0]


def host_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = parsed.netloc or raw
    return normalize_host(host)


# Metadata from local sources export
local_meta = {}
with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        host = host_from_url(row.get("url_news", ""))
        if not host:
            continue
        local_meta[host] = {
            "newsroom_type": (row.get("media_type", "") or "").strip(),
            "frequency": (row.get("frequency", "") or "").strip(),
        }

# Optional metadata fallback from production dump
prod_meta = {}
if os.path.exists(PROD_TSV):
    with open(PROD_TSV, newline="", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if not parts:
                continue
            host = normalize_host(parts[0])
            if not host:
                continue
            newsroom_type = parts[1].strip() if len(parts) > 1 else ""
            frequency = parts[2].strip() if len(parts) > 2 else ""
            prod_meta[host] = {
                "newsroom_type": newsroom_type,
                "frequency": frequency,
            }

rows = []
missing_type = []
missing_frequency = []

with open(COUNTS_CSV, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        host = (row.get("publication", "") or "").strip()
        norm = normalize_host(host)

        local = local_meta.get(norm, {})
        prod = prod_meta.get(norm, {})

        newsroom_type = local.get("newsroom_type") or prod.get("newsroom_type") or ""
        frequency = local.get("frequency") or prod.get("frequency") or ""

        if not newsroom_type:
            missing_type.append(host)
        if not frequency:
            missing_frequency.append(host)

        rows.append(
            {
                "host": host,
                "articles": row.get("total_articles", "0"),
                "unique_bylines": row.get("unique_bylines", "0"),
                "newsroom_type": newsroom_type,
                "frequency": frequency,
            }
        )

rows.sort(key=lambda r: (-int(r["articles"]), r["host"]))

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["host", "articles", "unique_bylines", "newsroom_type", "frequency"],
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Saved: {OUTPUT_CSV}")
print(f"Rows: {len(rows)}")
print(f"Missing newsroom_type: {len(missing_type)}")
print(f"Missing frequency: {len(missing_frequency)}")
if missing_type:
    print("Sample missing newsroom_type:", ", ".join(missing_type[:10]))
if missing_frequency:
    print("Sample missing frequency:", ", ".join(missing_frequency[:10]))
