#!/usr/bin/env python3

from src.utils.byline_cleaner import BylineCleaner


def test_edge_cases():
    """Test the specific edge cases we found."""

    cleaner = BylineCleaner()

    test_cases = [
        "News Team",
        "Staff | News Department",
        "- Reporter Name",
        "The Associated Press",
        "Team",
        "Department",
        "Name",
    ]

    print("Testing improved edge case handling:")
    print("=" * 40)

    for test_case in test_cases:
        result = cleaner.clean_byline(test_case, return_json=True)
        authors = result["authors"]

        print(f"'{test_case}' → {authors}")
        if not authors:
            print("  ✅ Correctly filtered out")
        elif len(authors) == 1 and len(authors[0].split()) >= 2:
            print("  ✅ Good - proper name(s) extracted")
        else:
            # Check if any remaining terms are journalism nouns
            has_journalism_terms = any(
                word.lower() in cleaner.JOURNALISM_NOUNS
                for author in authors
                for word in author.split()
            )
            if has_journalism_terms:
                print("  ⚠️  Still contains journalism terms")
            else:
                print("  ✅ Cleaned successfully")


if __name__ == "__main__":
    test_edge_cases()
