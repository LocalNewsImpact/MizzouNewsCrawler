#!/usr/bin/env python3
"""
Test different output formats for multiple authors.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from src.utils.byline_cleaner import BylineCleaner


def test_output_formats():
    """Test both string and JSON output formats."""

    cleaner = BylineCleaner()

    test_case = "Mike Chen, Lisa Park"

    print("Testing Output Formats")
    print("=" * 50)
    print(f"Input: '{test_case}'")
    print()

    # Test string format (default)
    string_result = cleaner.clean_byline(test_case, return_json=False)
    print(f"String format (return_json=False): '{string_result}'")
    print(f"Type: {type(string_result)}")
    print()

    # Test JSON format
    json_result = cleaner.clean_byline(test_case, return_json=True)
    print(f"JSON format (return_json=True): {json_result}")
    print(f"Type: {type(json_result)}")
    print(f"Authors array: {json_result.get('authors', [])}")
    print(f"Number of authors: {json_result.get('count', 0)}")


if __name__ == "__main__":
    test_output_formats()
