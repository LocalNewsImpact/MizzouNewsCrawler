#!/usr/bin/env python3
"""
Alternative Extraction Analysis Tool

Analyzes the telemetry database to find cases where later extraction methods
found alternative values for fields that were already populated by earlier methods.
This helps identify:
1. Which methods provide different/better versions of the same field
2. Whether later methods consistently find different content
3. Potential improvements to extraction quality
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path


def analyze_alternative_extractions():
    """Analyze alternative extractions from telemetry data."""

    db_path = Path("./data/mizzou.db")
    if not db_path.exists():
        print("Database not found!")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=== ALTERNATIVE EXTRACTION ANALYSIS ===\n")

    # Get entries with alternative extractions
    cursor.execute("""
        SELECT id, url, final_field_attribution, alternative_extractions
        FROM extraction_telemetry_v2 
        WHERE alternative_extractions IS NOT NULL 
        AND alternative_extractions != 'null'
        AND alternative_extractions != '{}'
    """)

    entries = cursor.fetchall()
    print(f"Found {len(entries)} entries with alternative extractions\n")

    if len(entries) == 0:
        print("No alternative extractions found yet.")
        print("This feature tracks alternatives from new extractions going forward.")
        return

    # Analyze patterns
    method_field_alternatives = defaultdict(lambda: defaultdict(int))
    value_differences = defaultdict(list)

    for entry_id, url, attribution_json, alternatives_json in entries:
        attribution = json.loads(attribution_json)
        alternatives = json.loads(alternatives_json)

        print(f"Entry {entry_id}: {url[:60]}...")
        print(f"  Final attribution: {attribution}")

        for method, fields in alternatives.items():
            print(f"  {method} alternatives:")
            for field, data in fields.items():
                method_field_alternatives[method][field] += 1

                current = data["current_value"]
                alternative = data["alternative_value"]
                differs = data["values_differ"]

                print(f"    {field}: {'DIFFERENT' if differs else 'SAME'}")
                print(f"      Current:     {current[:50]}...")
                print(f"      Alternative: {alternative[:50]}...")

                if differs:
                    value_differences[f"{method}_{field}"].append(
                        {"url": url, "current": current, "alternative": alternative}
                    )
        print()

    # Summary statistics
    print("=== SUMMARY STATISTICS ===")
    for method, fields in method_field_alternatives.items():
        print(f"\n{method.upper()} alternatives:")
        for field, count in fields.items():
            print(f"  {field}: {count} cases")

            # Show examples of differences
            diff_key = f"{method}_{field}"
            if diff_key in value_differences:
                diffs = value_differences[diff_key]
                print(f"    {len(diffs)} had different values")

                if len(diffs) > 0:
                    print("    Example differences:")
                    for i, diff in enumerate(diffs[:2]):  # Show first 2 examples
                        print(f"      #{i + 1}: Current='{diff['current'][:30]}...'")
                        print(f"          Alternative='{diff['alternative'][:30]}...'")

    print("\n💡 INSIGHTS:")
    print("• Alternative tracking helps identify extraction quality differences")
    print("• Later methods might find better formatted content")
    print("• Differences can indicate which method is more reliable")
    print("• This data helps optimize extraction method priorities")

    conn.close()


if __name__ == "__main__":
    analyze_alternative_extractions()
