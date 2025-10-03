#!/usr/bin/env python3
"""Generate CIN coverage reports for Boone, Audrain, and Osage counties."""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

SPLIT_PATTERN = re.compile(r"\s*(?:and|/|,|&|\+|;)\s*", re.IGNORECASE)
COUNTIES = ["Boone", "Audrain", "Osage"]
SOURCE_PATH = Path("reports/cin_labels_with_sources.csv")
OUTPUT_PATH = Path("reports/cin_county_summary.md")
CSV_OUTPUT_PATH = Path("reports/cin_county_summary.csv")


def _split_counties(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in SPLIT_PATTERN.split(raw) if part.strip()]


def _summarize() -> tuple[
    dict[str, dict[str, dict[str, int]]],
    dict[str, dict[str, int]],
]:
    summary: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    publication_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    with SOURCE_PATH.open(newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            counties = _split_counties(row.get("publication_county"))
            if not counties:
                continue

            publication = row.get("publication_name", "Unknown Publication")
            label = (row.get("primary_label") or "Unlabeled").strip() or "Unlabeled"

            for raw_county in counties:
                normalized = raw_county.title()
                if normalized in COUNTIES:
                    summary[normalized][publication][label] += 1
                    publication_totals[normalized][publication] += 1

    return summary, publication_totals


def _render_markdown(
    summary: dict[str, dict[str, dict[str, int]]],
    publication_totals: dict[str, dict[str, int]],
) -> str:
    lines: list[str] = []
    lines.append("# Critical Information Needs Coverage\n")
    lines.append(f"Generated on {date.today():%B %d, %Y}.\n")
    lines.append(
        "This report summarizes publications, story counts, and Critical "
        "Information Needs (CIN) distribution for Boone, Audrain, and Osage "
        "counties based on `reports/cin_labels_with_sources.csv`.\n"
    )

    for county in COUNTIES:
        lines.append(f"\n## {county} County\n")
        publications = publication_totals.get(county, {})
        if not publications:
            lines.append("No stories collected for this county.\n")
            continue

        lines.append("| Publication | Stories | Critical Information Needs Mix |\n")
        lines.append("| --- | ---: | --- |\n")

        for publication in sorted(publications):
            total = publications[publication]
            label_counts = summary[county][publication]
            parts: list[str] = []
            for label, count in sorted(
                label_counts.items(), key=lambda item: (-item[1], item[0])
            ):
                percent = (count / total * 100) if total else 0.0
                parts.append(f"{label} {count} ({percent:.1f}%)")
            mix = "<br>".join(parts)
            lines.append(f"| {publication} | {total} | {mix} |\n")

    return "".join(lines)


def _write_csv(
    summary: dict[str, dict[str, dict[str, int]]],
    publication_totals: dict[str, dict[str, int]],
    output_path: Path,
) -> None:
    fieldnames = [
        "county",
        "publication",
        "total_stories",
        "label",
        "label_story_count",
        "label_story_percent",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for county in COUNTIES:
            publications = publication_totals.get(county, {})
            if not publications:
                continue

            for publication in sorted(publications):
                total = publications[publication]
                if not total:
                    continue

                label_counts = summary[county][publication]
                for label, count in sorted(
                    label_counts.items(), key=lambda item: (-item[1], item[0])
                ):
                    percent = (count / total * 100) if total else 0.0
                    writer.writerow(
                        {
                            "county": county,
                            "publication": publication,
                            "total_stories": total,
                            "label": label,
                            "label_story_count": count,
                            "label_story_percent": f"{percent:.1f}",
                        }
                    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate CIN coverage summaries for selected counties."
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["markdown", "csv", "both"],
        default="markdown",
        help="Which output to produce (default: markdown).",
    )
    parser.add_argument(
        "--markdown-path",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Path for markdown output (default: {OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=CSV_OUTPUT_PATH,
        help=f"Path for CSV output (default: {CSV_OUTPUT_PATH}).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary, publication_totals = _summarize()
    if args.format in {"markdown", "both"}:
        args.markdown_path.write_text(
            _render_markdown(summary, publication_totals),
            encoding="utf-8",
        )
        print(f"Wrote {args.markdown_path}")

    if args.format in {"csv", "both"}:
        _write_csv(summary, publication_totals, args.csv_path)
        print(f"Wrote {args.csv_path}")


if __name__ == "__main__":
    main()
