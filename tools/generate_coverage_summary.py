#!/usr/bin/env python3
"""Generate a Markdown coverage summary from coverage.xml."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "xml_path",
        type=Path,
        help="Path to coverage XML file",
    )
    parser.add_argument(
        "output_path",
        type=Path,
        help="Location to write the Markdown summary",
    )
    parser.add_argument(
        "--root",
        type=str,
        default="src/",
        help="Only include files beginning with this prefix (default: src/)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=50,
        help="Maximum number of rows to include (lowest coverage first)",
    )
    return parser.parse_args()


def build_module_stats(
    xml_path: Path, root_prefix: str
) -> list[tuple[str, int, int]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"statements": 0, "covered": 0}
    )

    for class_el in root.findall(".//class"):
        filename = class_el.get("filename") or ""
        if root_prefix and not filename.startswith(root_prefix):
            continue

        lines_parent = class_el.find("lines")
        if lines_parent is None:
            continue

        for line in lines_parent.findall("line"):
            stats[filename]["statements"] += 1
            hits = int(line.get("hits", "0"))
            if hits > 0:
                stats[filename]["covered"] += 1

    rows = []
    for filename, data in stats.items():
        statements = data["statements"]
        covered = data["covered"]
        if statements == 0:
            continue
        rows.append((filename, statements, covered))

    return rows


def format_markdown(rows: list[tuple[str, int, int]], max_rows: int) -> str:
    header = [
        "# Coverage Summary",
        "",
        "| Module | Statements | Miss | Coverage |",
        "| --- | ---: | ---: | ---: |",
    ]
    body = []

    sorted_rows = sorted(
        rows,
        key=lambda item: item[2] / item[1] if item[1] else 0,
    )

    for filename, statements, covered in sorted_rows[:max_rows]:
        miss = statements - covered
        coverage_pct = (covered / statements) * 100 if statements else 0.0
        body.append(
            f"| `{filename}` | {statements} | {miss} | {coverage_pct:.1f}% |"
        )

    if not body:
        body.append("| *(no files matched)* | 0 | 0 | 0.0% |")

    return "\n".join(header + body) + "\n"


def main() -> None:
    args = parse_arguments()

    if not args.xml_path.exists():
        raise FileNotFoundError(f"coverage XML not found: {args.xml_path}")

    rows = build_module_stats(args.xml_path, args.root)
    markdown = format_markdown(rows, args.max_rows)

    args.output_path.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
