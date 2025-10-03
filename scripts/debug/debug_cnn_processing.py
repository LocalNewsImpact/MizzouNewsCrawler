#!/usr/bin/env python3
"""
Debug test for CNN byline processing.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils.byline_cleaner import BylineCleaner


def debug_cnn_processing():
    """Debug CNN byline processing step by step."""

    print("=== Debug CNN Processing ===\n")

    cleaner = BylineCleaner(enable_telemetry=False)

    byline = "By Tom Reporter, CNN"
    source_name = "CNN"

    print(f"Testing: '{byline}' with source '{source_name}'")
    print()

    # Test step by step
    print("1. Wire service detection:")
    is_wire = cleaner._is_wire_service(byline)
    print(f"   Is wire service: {is_wire}")
    print(f"   Detected services: {cleaner._detected_wire_services}")

    if is_wire:
        detected_service = (
            cleaner._detected_wire_services[-1]
            if cleaner._detected_wire_services
            else None
        )
        print(f"   Detected service: '{detected_service}'")

        is_own_source = cleaner._is_wire_service_from_own_source(
            detected_service, source_name
        )
        print(f"   Is own source: {is_own_source}")

    print()
    print("2. Full cleaning process:")
    result = cleaner.clean_byline(
        byline=byline, return_json=True, source_canonical_name=source_name
    )

    print(f"   Final authors: {result['authors']}")
    print(f"   Wire services: {result['wire_services']}")
    print(f"   Is wire content: {result['is_wire_content']}")

    print()
    print("3. Manual source removal test:")
    cleaned = cleaner._remove_source_name(byline, source_name)
    print(f"   After source removal: '{cleaned}'")

    # Test pattern extraction
    print()
    print("4. Pattern extraction test:")
    test_text = "tom reporter"
    authors = cleaner._extract_authors(test_text)
    print(f"   Extract authors from '{test_text}': {authors}")


if __name__ == "__main__":
    debug_cnn_processing()
