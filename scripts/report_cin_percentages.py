#!/usr/bin/env python3
"""Generate Critical Information Needs category percentages by county."""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

# Resolve paths relative to repository root
ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "reports" / "cin_labels_with_sources.csv"
OUTPUT_PATH = ROOT / "reports" / "cin_category_percentages_by_county.csv"

SPLIT_PATTERN = re.compile(r"\s*(?:and|/|,|&|\+|;)\s*", re.IGNORECASE)


def _split_counties(raw: str | None) -> list[str]:
    """Split the publication_county field into individual county names."""
    if not raw:
        return ["Unknown"]

    parts = SPLIT_PATTERN.split(raw.strip())
    cleaned = [part.strip() for part in parts if part.strip()]
    return cleaned or ["Unknown"]


def _sanitize_category(category: str) -> str:
    """Convert category name into a safe column slug."""
    return re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")


def main() -> None:
    if not SOURCE_PATH.exists():
        message = (
            "Source CSV not found at "
            f"{SOURCE_PATH}. Run CIN labeling export first."
        )
        raise FileNotFoundError(message)

    county_totals: dict[str, int] = defaultdict(int)
    county_category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    categories: set[str] = set()

    with SOURCE_PATH.open(newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames or []
        missing_columns = {
            name for name in ("primary_label", "publication_county")
            if name not in fieldnames
        }
        if missing_columns:
            raise ValueError(
                "Source CSV is missing required columns: "
                + ", ".join(sorted(missing_columns))
            )

        for row in reader:
            raw_category = row.get("primary_label", "") or ""
            category = raw_category.strip() or "Unlabeled"
            if not category:
                category = "Unlabeled"
            categories.add(category)

            counties = _split_counties(row.get("publication_county"))
            for county in counties:
                county_totals[county] += 1
                county_category_counts[county][category] += 1

    if not categories:
        raise ValueError("No categories found in source data.")

    sorted_categories = sorted(categories)
    column_suffix_map = {
        cat: _sanitize_category(cat) for cat in sorted_categories
    }

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as outfile:
        fieldnames = ["county", "total_articles"]
        for category in sorted_categories:
            slug = column_suffix_map[category]
            fieldnames.append(f"{slug}_percent")
            fieldnames.append(f"{slug}_count")

        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for county in sorted(county_totals):
            total = county_totals[county]
            row = {"county": county, "total_articles": total}

            for category in sorted_categories:
                count = county_category_counts[county].get(category, 0)
                percent = (count / total * 100) if total else 0.0
                slug = column_suffix_map[category]
                row[f"{slug}_percent"] = f"{percent:.2f}"
                row[f"{slug}_count"] = count

            writer.writerow(row)

    print(f"Wrote CIN category breakdown to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
