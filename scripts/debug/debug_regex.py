#!/usr/bin/env python3
"""Debug the regex patterns for Special to constructions."""

import re

# Test the specific patterns
patterns = [
    # "By Author Name" patterns
    r'^by\s+(.+)$',
    r'^written\s+by\s+(.+)$',
    r'^story\s+by\s+(.+)$',
    r'^report\s+by\s+(.+)$',

    # "Special to" patterns (extract name before "Special")
    r'^(.+?)\s+special\s+to?t?\s*(the|he)?\s*(.+)$',
    r'^(.+?)\s+special\s+correspondent.*$',
    r'^(.+?)\s+special\s+contributor.*$',
]

test_byline = "By DORIAN DUCRE Special tot he Courier-Post"

print(f"Testing byline: {test_byline}")
print(f"Lowercase: {test_byline.lower()}")

for i, pattern in enumerate(patterns):
    compiled_pattern = re.compile(pattern, re.IGNORECASE)
    match = compiled_pattern.search(test_byline.lower())

    print(f"\nPattern {i}: {pattern}")
    if match:
        print(f"  ✅ MATCH: {match.groups()}")
        if match.groups():
            print(f"  Extracted: '{match.group(1).strip()}'")
    else:
        print("  ❌ NO MATCH")

# Test a simpler approach
print("\n" + "="*50)
print("Testing simpler approach:")

# Remove "by" prefix first
test_without_by = re.sub(r'^by\s+', '', test_byline.lower().strip())
print(f"After removing 'by': {test_without_by}")

# Look for "special to" pattern
special_pattern = r'^(.+?)\s+special\s+(?:to|tot|teh)\s*(?:the|he)?\s*(.+)$'
match = re.match(special_pattern, test_without_by)

if match:
    name_part = match.group(1).strip()
    print(f"Extracted name: '{name_part}'")
else:
    print("No match for special pattern")
