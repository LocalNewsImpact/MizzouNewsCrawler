#!/usr/bin/env python3
"""
Test the integrated byline cleaning in the extraction pipeline.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.utils.byline_cleaner import BylineCleaner


def test_integration():
    """Test how byline cleaning will work in the extraction pipeline."""

    # Simulate extraction data with raw author fields
    extraction_results = [
        {
            "title": "Local News Story",
            "author": "JOHN SMITH, Staff Reporter",
            "content": "Story content...",
            "url": "https://example.com/story1",
        },
        {
            "title": "Sports Update",
            "author": "Sarah Johnson and Mike Wilson, Sports Editors",
            "content": "Sports content...",
            "url": "https://example.com/story2",
        },
        {
            "title": "Wire Story",
            "author": "Associated Press",
            "content": "Wire content...",
            "url": "https://example.com/story3",
        },
        {
            "title": "Complex Byline",
            "author": "JANE DOE, JANE.DOE@NEWS.COM, Senior Political Editor",
            "content": "Political content...",
            "url": "https://example.com/story4",
        },
    ]

    # Initialize cleaner
    cleaner = BylineCleaner()

    print("Testing Integrated Byline Cleaning")
    print("=" * 50)

    for i, article in enumerate(extraction_results, 1):
        print(f"\nArticle {i}: {article['title']}")
        print(f"URL: {article['url']}")

        # This is what happens in the extraction pipeline
        raw_author = article.get("author")
        cleaned_author = None

        if raw_author:
            cleaned_author = cleaner.clean_byline(raw_author)
            print(f"Raw Author:     '{raw_author}'")
            print(f"Cleaned Author: '{cleaned_author}'")

            # This is what gets saved to the database
            article["author"] = cleaned_author

            # Show wire service preservation
            if cleaned_author == raw_author:
                print("✓ Wire service preserved unchanged")
            else:
                print("✓ Author field cleaned")
        else:
            print("No author field")

    print("\n" + "=" * 50)
    print("Integration test complete!")
    print("\nThis demonstrates how the byline cleaner will automatically")
    print("clean author fields as articles are extracted and saved.")


if __name__ == "__main__":
    test_integration()
