"""
List all publications (hosts) collected for March and for the constructed week,
with article counts. Outputs two CSVs.
"""

import csv
import os
from collections import Counter
from datetime import datetime, date

INPUT = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Mizzou/CIEP/"
    "MO MARCH Final 51826.csv"
)
OUT_MONTH = os.path.join(os.path.dirname(__file__), "ciep_march_publications_month.csv")
OUT_CWEEK = os.path.join(os.path.dirname(__file__), "ciep_march_publications_cweek.csv")

CONSTRUCTED_WEEK = {
    date(2026, 3,  1),
    date(2026, 3,  9),
    date(2026, 3, 18),
    date(2026, 3, 20),
    date(2026, 3, 26),
    date(2026, 3, 28),
    date(2026, 3, 31),
}

month_counts = Counter()
cweek_counts = Counter()

with open(INPUT, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        host = row["host"].strip()
        if not host:
            continue
        raw = row["publish_date"].strip()
        try:
            d = datetime.strptime(raw, "%m/%d/%y").date()
        except ValueError:
            try:
                d = datetime.strptime(raw, "%m/%d/%Y").date()
            except ValueError:
                continue
        month_counts[host] += 1
        if d in CONSTRUCTED_WEEK:
            cweek_counts[host] += 1

def write_csv(path, counter):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["publication", "article_count"])
        for host, cnt in sorted(counter.items(), key=lambda x: (-x[1], x[0])):
            w.writerow([host, cnt])

write_csv(OUT_MONTH, month_counts)
write_csv(OUT_CWEEK, cweek_counts)

print(f"Month: {len(month_counts)} publications → {OUT_MONTH}")
print(f"Constructed week: {len(cweek_counts)} publications → {OUT_CWEEK}")
