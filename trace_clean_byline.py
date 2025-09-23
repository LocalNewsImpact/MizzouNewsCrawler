#!/usr/bin/env python3

"""Trace through the clean_byline method step by step."""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner

def trace_clean_byline():
    """Trace through clean_byline for failing cases."""
    
    cleaner = BylineCleaner(enable_telemetry=False)
    
    failing_cases = ["McDonald's", "Prince"]
    
    for case in failing_cases:
        print(f"Tracing clean_byline for: '{case}'")
        print("-" * 40)
        
        # Manually trace through the logic
        
        # Step 1: Basic checks
        print(f"Input: '{case}'")
        if not case or not case.strip():
            print("EARLY EXIT: Empty input")
            continue
            
        # Step 2: Source name removal (not applicable here)
        cleaned_byline = case
        print(f"After source removal: '{cleaned_byline}'")
        
        # Step 3: Dynamic publication name filtering
        is_pub = cleaner._is_publication_name(cleaned_byline)
        print(f"Is publication name: {is_pub}")
        if is_pub:
            print("EARLY EXIT: Publication name")
            continue
            
        # Step 4: Wire service detection  
        is_wire = cleaner._is_wire_service(cleaned_byline)
        print(f"Is wire service: {is_wire}")
        if is_wire:
            print("EARLY EXIT: Wire service")
            continue
            
        # Step 5: Pattern extraction
        text = cleaned_byline.lower().strip()
        extracted_text = None
        
        for i, pattern in enumerate(cleaner.compiled_patterns[:4]):
            match = pattern.search(text)
            if match:
                if match.groups():
                    extracted_text = match.group(1).strip()
                else:
                    extracted_text = match.group(0).strip()
                print(f"Pattern {i} matched: '{extracted_text}'")
                break
                
        if not extracted_text:
            extracted_text = cleaned_byline.strip()
            print(f"No pattern matched, using full text: '{extracted_text}'")
            
        # Step 6: Remove patterns
        cleaned_text = cleaner._remove_patterns(extracted_text)
        print(f"After pattern removal: '{cleaned_text}'")
        
        # Step 7: Extract authors
        authors = cleaner._extract_authors(cleaned_text)
        print(f"After author extraction: {authors}")
        
        # Step 8: Smart processing check
        if (isinstance(authors, list) and len(authors) >= 1 and 
            authors[0] == "__SMART_PROCESSED__"):
            print("Smart processing detected")
            smart_names = authors[1:]
            cleaned_names = []
            
            for name in smart_names:
                cleaned_name = cleaner._clean_author_name(name)
                if cleaned_name.strip():
                    cleaned_names.append(cleaned_name.strip())
                    
            final_authors = cleaner._deduplicate_authors(cleaned_names)
            print(f"After smart processing: {final_authors}")
        else:
            # Step 9: Clean individual names
            cleaned_authors = [cleaner._clean_author_name(author) for author in authors]
            cleaned_authors = [author for author in cleaned_authors if author.strip()]
            print(f"After individual cleaning: {cleaned_authors}")
            
            # Step 10: Remove duplicates
            final_authors = cleaner._deduplicate_authors(cleaned_authors)
            print(f"After deduplication: {final_authors}")
            
        # Step 11: Validation
        valid_authors = cleaner._validate_authors(final_authors)
        print(f"After validation: {valid_authors}")
        
        print("\n" + "=" * 50 + "\n")

if __name__ == "__main__":
    trace_clean_byline()