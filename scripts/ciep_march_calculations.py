"""
CIEP March 2026 data calculations.
Input:  MO MARCH Final 51826.csv
Output: ciep_march_results.csv  (saved next to this script)
"""

import csv
import os
from collections import defaultdict, Counter
from datetime import datetime, date

# ── Paths ────────────────────────────────────────────────────────────────────
INPUT = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Mizzou/CIEP/"
    "MO MARCH Final 51826.csv"
)
OUTPUT = os.path.join(os.path.dirname(__file__), "ciep_march_results.csv")

# ── Constructed-week dates ────────────────────────────────────────────────────
CONSTRUCTED_WEEK = {
    date(2026, 3,  1),   # SUN
    date(2026, 3,  9),   # MON
    date(2026, 3, 18),   # WED
    date(2026, 3, 20),   # FRI
    date(2026, 3, 26),   # THU
    date(2026, 3, 28),   # SAT
    date(2026, 3, 31),   # TUE
}

DOW_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
# Python weekday(): Mon=0 … Sun=6  →  map to Sunday-first
def dow_name(d: date) -> str:
    return DOW_NAMES[d.isoweekday() % 7]   # isoweekday: Mon=1…Sun=7; %7 → Sun=0

# ── Load data ────────────────────────────────────────────────────────────────
rows_month = []
rows_cweek = []

with open(INPUT, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        raw_date = row["publish_date"].strip()
        if not raw_date:
            continue
        try:
            d = datetime.strptime(raw_date, "%m/%d/%y").date()
        except ValueError:
            try:
                d = datetime.strptime(raw_date, "%m/%d/%Y").date()
            except ValueError:
                continue
        row["_date"] = d
        row["_dow"]  = dow_name(d)
        rows_month.append(row)
        if d in CONSTRUCTED_WEEK:
            rows_cweek.append(row)

# ── Summary metrics ──────────────────────────────────────────────────────────
total_sources  = len({r["host"].strip() for r in rows_month if r["host"].strip()})
total_articles = len(rows_month)

all_bylines = [r["author"].strip() for r in rows_month if r["author"].strip()]
unique_bylines = len(set(all_bylines))

month_byline_counts = Counter(all_bylines)
cweek_bylines = [r["author"].strip() for r in rows_cweek if r["author"].strip()]
cweek_byline_counts = Counter(cweek_bylines)

def appearing_n_plus(counter, n):
    return sum(1 for v in counter.values() if v >= n)

# ── Per-DoW article counts ────────────────────────────────────────────────────
# Count articles per date, then group by DoW
date_counts_month = Counter(r["_date"] for r in rows_month)
date_counts_cweek = Counter(r["_date"] for r in rows_cweek)

# For month: for each DoW collect the per-date counts across every occurrence
dow_date_counts_month = defaultdict(list)
for d, cnt in date_counts_month.items():
    dow_date_counts_month[dow_name(d)].append(cnt)

dow_date_counts_cweek = defaultdict(list)
for d, cnt in date_counts_cweek.items():
    dow_date_counts_cweek[dow_name(d)].append(cnt)

# ── Build output rows ─────────────────────────────────────────────────────────
results = []

def add(label, value, note=""):
    results.append({"Metric": label, "Value": value, "Note": note})

add("Total Sources",   total_sources)
add("Total Articles",  total_articles)
add("Unique Bylines",  unique_bylines)
add("", "")

add("Month: Bylines appearing 2+", appearing_n_plus(month_byline_counts, 2))
add("Month: Bylines appearing 3+", appearing_n_plus(month_byline_counts, 3))
add("Month: Bylines appearing 4+", appearing_n_plus(month_byline_counts, 4))
add("", "")

add("Constructed Week: Bylines appearing 2+", appearing_n_plus(cweek_byline_counts, 2))
add("Constructed Week: Bylines appearing 3+", appearing_n_plus(cweek_byline_counts, 3))
add("Constructed Week: Bylines appearing 4+", appearing_n_plus(cweek_byline_counts, 4))
add("", "")

add("--- Average articles per DoW (Month) ---", "")
for dow in DOW_NAMES:
    counts = dow_date_counts_month.get(dow, [])
    if counts:
        avg = round(sum(counts) / len(counts), 2)
        add(f"  Month Avg {dow}", avg, f"across {len(counts)} date(s)")
    else:
        add(f"  Month Avg {dow}", 0, "no data")

add("", "")
add("--- Average articles per DoW (Constructed Week) ---", "")
for dow in DOW_NAMES:
    counts = dow_date_counts_cweek.get(dow, [])
    if counts:
        avg = round(sum(counts) / len(counts), 2)
        add(f"  CWeek Avg {dow}", avg, f"across {len(counts)} date(s)")
    else:
        add(f"  CWeek Avg {dow}", 0, "not in constructed week")

add("", "")
add("--- Total articles per DoW (Month) ---", "")
for dow in DOW_NAMES:
    counts = dow_date_counts_month.get(dow, [])
    add(f"  Month Total {dow}", sum(counts))

add("", "")
add("--- Total articles per DoW (Constructed Week) ---", "")
for dow in DOW_NAMES:
    counts = dow_date_counts_cweek.get(dow, [])
    add(f"  CWeek Total {dow}", sum(counts))

# ── Write output ──────────────────────────────────────────────────────────────
with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["Metric", "Value", "Note"])
    writer.writeheader()
    writer.writerows(results)

print(f"Results written to: {OUTPUT}")

# ── Print to console too ──────────────────────────────────────────────────────
print()
for r in results:
    if r["Metric"] and not r["Metric"].startswith("---"):
        note = f"  ({r['Note']})" if r["Note"] else ""
        print(f"  {r['Metric']:<50} {r['Value']}{note}")
    elif r["Metric"].startswith("---"):
        print(f"\n{r['Metric']}")
