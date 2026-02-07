#!/usr/bin/env python3
"""
Read and display the contents of wire_errors.xlsx
"""

import pandas as pd
import sys

try:
    # Read the Excel file
    df = pd.read_excel('wire_errors.xlsx')
    print("Excel file contents:")
    print("=" * 50)
    print(df.to_string(index=False))
    print("=" * 50)
    print(f"Total rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")

except Exception as e:
    print(f"Error reading Excel file: {e}")
    sys.exit(1)