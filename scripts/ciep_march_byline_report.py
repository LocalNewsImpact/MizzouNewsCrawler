"""
Articles-per-byline report for March, broken down by Primary CIN Label.
Multi-author articles (comma-separated) credit each author individually.
Output: ciep_march_byline_report.csv
"""

import csv
import os
from collections import defaultdict

INPUT = os.path.join(
    os.path.dirname(__file__), "..", "exports", "MO_MARCH_Final_CIN_updated_20260731.csv"
)
OUTPUT = os.path.join(os.path.dirname(__file__), "ciep_march_byline_report.csv")

# CIN label categories to use as columns (exclude empty / data-quality values)
SKIP_LABELS = {"", "labeled"}

# author → {label: count}, author → {host: count}
author_totals = defaultdict(int)
author_labels = defaultdict(lambda: defaultdict(int))
author_hosts = defaultdict(set)
all_labels = set()

with open(INPUT, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        raw_author = row["author"].strip()
        if not raw_author:
            continue

        label = row["Primary Label"].strip()
        host = row["host"].strip()
        if label not in SKIP_LABELS:
            all_labels.add(label)

        # Split comma-separated bylines
        authors = [a.strip() for a in raw_author.split(",") if a.strip()]

        for author in authors:
            author_totals[author] += 1
            if host:
                author_hosts[author].add(host)
            if label not in SKIP_LABELS:
                author_labels[author][label] += 1

# Sort labels alphabetically for consistent column order
sorted_labels = sorted(all_labels)

# Sort authors by total articles descending, then name
sorted_authors = sorted(author_totals.keys(), key=lambda a: (-author_totals[a], a))

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    fieldnames = ["author", "publications", "total_articles"] + sorted_labels
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for author in sorted_authors:
        row = {
            "author": author,
            "publications": "; ".join(sorted(author_hosts[author])),
            "total_articles": author_totals[author],
        }
        for label in sorted_labels:
            row[label] = author_labels[author].get(label, 0)
        writer.writerow(row)

print(f"Authors: {len(sorted_authors)}")
print(f"CIN label columns: {sorted_labels}")
print(f"Saved: {OUTPUT}")
