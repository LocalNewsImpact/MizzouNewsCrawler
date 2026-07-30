#!/usr/bin/env python3
"""Make a CSV export safe to open in Excel and readable line-by-line.

Three problems, all seen on real exports from this repo:

1. **No BOM.** The file is valid UTF-8, but Excel assumes cp1252 when there is
   no byte-order mark, so every smart quote renders as ``â€™``, every em dash
   as ``â€”``. One export carried 5,308 such characters across 25 distinct
   code points -- the whole file looks corrupted while being perfectly valid.
   Writing utf-8-sig fixes it without changing a single character of content.

2. **Embedded newlines.** Article bodies keep their paragraph breaks, which is
   correct RFC 4180 (quoted fields may span lines) and unreadable in any
   line-numbered viewer: one 216-row export spanned 10,473 physical lines, so
   "row 32" in an editor was really the middle of row 2. Collapsed to spaces
   so one logical row is always one physical line.

3. **Control characters.** NULs, form feeds and stray C0/C1 bytes that survive
   extraction break Excel's parser outright. Stripped, except tab/newline
   (and newline is already handled by 2).

Content is otherwise untouched: no transliteration, no quote "normalisation".
Curly quotes stay curly -- with the BOM they display correctly, and rewriting
a publisher's punctuation would corrupt the text we are trying to preserve.

Usage:
    python tools/clean_csv_export.py path/to/export.csv [more.csv ...]

Rewrites each file in place and prints what changed.
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from pathlib import Path

# Collapse a run of whitespace containing a newline down to one space.
_NEWLINE_RUN = re.compile(r"\s*\n\s*")


def _strip_control_chars(value: str) -> str:
    """Remove characters Excel cannot parse, keeping tab (newlines are already
    collapsed before this runs)."""
    return "".join(
        ch
        for ch in value
        if ch == "\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co")
    )


def clean_cell(value: str) -> str:
    if not value:
        return value
    return _strip_control_chars(_NEWLINE_RUN.sub(" ", value)).strip()


def clean_csv(path: Path) -> dict:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return {"rows": 0, "cells_changed": 0, "cols": 0}

    changed = 0
    cleaned: list[list[str]] = []
    for row in rows:
        new_row = []
        for cell in row:
            new = clean_cell(cell)
            if new != cell:
                changed += 1
            new_row.append(new)
        cleaned.append(new_row)

    # utf-8-sig writes the BOM Excel needs to recognise UTF-8.
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(cleaned)

    return {"rows": len(cleaned) - 1, "cells_changed": changed, "cols": len(rows[0])}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"  MISSING  {path}")
            continue
        stats = clean_csv(path)
        # Verify the property that actually matters: one logical row per line.
        physical = sum(1 for _ in path.open(encoding="utf-8-sig"))
        logical = stats["rows"] + 1
        ok = "OK" if physical == logical else f"MISMATCH {physical} vs {logical}"
        print(
            f"  {path.name}: {stats['rows']} rows x {stats['cols']} cols, "
            f"{stats['cells_changed']} cells cleaned, BOM added, lines={ok}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
