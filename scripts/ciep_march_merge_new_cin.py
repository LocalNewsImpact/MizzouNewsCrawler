"""Overlay the 2026-07-30 CIN reclassification onto the March ground truth.

Takes the rot47-fixed ground truth (correct text, but still the OLD
Primary/Secondary labels) and overlays new_primary_label / new_primary_confidence
/ new_secondary_label / new_secondary_confidence from the reclassification run
onto the Primary Label / Primary Confidence / Secondary Label / Secondary
Confidence columns, matched by `id`.

Rows in the ground truth with no match in the reclassification file (72, as of
2026-07-30 -- rows dropped earlier in the BigQuery/comparison join) keep their
OLD label and are stamped reclassified=0 so they're identifiable in output
rather than silently mixed in with the new labels.

Column order and names are otherwise unchanged from the ground truth, so
downstream scripts that key off "Primary Label" etc. only need their INPUT
path repointed at this file -- no other code changes.

Input:  ~/Library/Mobile Documents/.../Mizzou/LNIC/MO MARCH Final 51826 - rot47 decoded.csv
        exports/march_cin_reclassification_20260730.csv
Output: exports/MO_MARCH_Final_CIN_updated_20260731.csv
"""

import csv
import os

GROUND_TRUTH = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Mizzou/LNIC/"
    "MO MARCH Final 51826 - rot47 decoded.csv"
)
NEW_CIN = os.path.join(os.path.dirname(__file__), "..", "exports", "march_cin_reclassification_20260730.csv")
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "exports", "MO_MARCH_Final_CIN_updated_20260731.csv")

with open(NEW_CIN, encoding="utf-8-sig", newline="") as f:
    new_labels = {row["id"]: row for row in csv.DictReader(f)}

matched = 0
unmatched = 0

with open(GROUND_TRUTH, encoding="utf-8", newline="") as f_in:
    reader = csv.DictReader(f_in)
    fieldnames = [*reader.fieldnames, "reclassified"]

    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            new_row = new_labels.get(row["id"])
            if new_row:
                row["Primary Label"] = new_row["new_primary_label"]
                row["Primary Confidence"] = new_row["new_primary_confidence"]
                row["Secondary Label"] = new_row["new_secondary_label"]
                row["Secondary Confidence"] = new_row["new_secondary_confidence"]
                row["reclassified"] = "1"
                matched += 1
            else:
                row["reclassified"] = "0"
                unmatched += 1
            writer.writerow(row)

print(f"matched (new CIN applied): {matched:,}")
print(f"unmatched (kept OLD label, reclassified=0): {unmatched:,}")
print(f"wrote: {OUTPUT}")
