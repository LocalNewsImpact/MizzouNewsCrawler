"""
Articles-per-publication report for March, broken down by Primary CIN Label.
Output: ciep_march_publication_report.csv
"""

import csv
import os
from collections import defaultdict

INPUT = os.path.join(
    os.path.dirname(__file__), "..", "exports", "MO_MARCH_Final_CIN_updated_20260731.csv"
)
OUTPUT = os.path.join(os.path.dirname(__file__), "ciep_march_publication_report.csv")

SKIP_LABELS = {"", "labeled"}

pub_totals = defaultdict(int)
pub_labels = defaultdict(lambda: defaultdict(int))
all_labels = set()

with open(INPUT, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        host = row["host"].strip()
        if not host:
            continue

        label = row["Primary Label"].strip()
        if label not in SKIP_LABELS:
            all_labels.add(label)

        pub_totals[host] += 1
        if label not in SKIP_LABELS:
            pub_labels[host][label] += 1

sorted_labels = sorted(all_labels)
sorted_pubs = sorted(pub_totals.keys(), key=lambda h: (-pub_totals[h], h))

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    fieldnames = ["publication", "total_articles"] + sorted_labels
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for pub in sorted_pubs:
        row = {"publication": pub, "total_articles": pub_totals[pub]}
        for label in sorted_labels:
            row[label] = pub_labels[pub].get(label, 0)
        writer.writerow(row)

print(f"Publications: {len(sorted_pubs)}")
print(f"Saved: {OUTPUT}")
