#!/usr/bin/env python3

from src.utils.byline_cleaner import BylineCleaner

def debug_cleaning():
    cleaner = BylineCleaner()
    
    # Test the specific problematic case
    test_byline = "Sarah Johnson and Mike Wilson, News Editors"
    
    print(f"Original: {test_byline}")
    print("\n--- Step by step extraction debugging ---")
    
    # Follow the exact extraction path
    text = test_byline
    
    # Step 1: Pattern matching (first 4 patterns for extraction)
    extracted_text = None
    for i, pattern in enumerate(cleaner.compiled_patterns[:4]):
        match = pattern.search(text.lower())
        if match:
            if match.groups():
                extracted_text = match.group(1).strip()
            else:
                extracted_text = match.group(0).strip()
            print(f"Pattern {i} matched, extracted: '{extracted_text}'")
            break
    
    if not extracted_text:
        extracted_text = text
        print(f"No pattern matched, using full text: '{extracted_text}'")
    
    # Step 2: Remove patterns
    cleaned_text = cleaner._remove_patterns(extracted_text)
    print(f"After removing patterns: '{cleaned_text}'")
    
    # Step 3: Extract authors
    authors = cleaner._extract_authors(cleaned_text)
    print(f"Extracted authors: {authors}")
    
    # Step 4: Clean individual authors
    cleaned_authors = [cleaner._clean_author_name(author) for author in authors]
    print(f"Cleaned authors: {cleaned_authors}")
    
    # Step 5: Final filtering
    final_authors = [author for author in cleaned_authors if author.strip()]
    print(f"Final authors: {final_authors}")

if __name__ == "__main__":
    debug_cleaning()