#!/usr/bin/env python3
"""Check specific article that should be wire."""
import re
from src.models.database import DatabaseManager
from src.models import Article

db = DatabaseManager()
session = db.session

# Get the COVID vaccines article
article = session.query(Article).filter(
    Article.url.like('%standard-democrat.com/world/covid-19-vaccines%')
).first()

if article:
    print("=" * 80)
    print(f"URL: {article.url}")
    print(f"Status: {article.status}")
    print(f"Author: {article.author or 'No author'}")
    print(f"Title: {article.title}")
    print("=" * 80)
    
    if article.content:
        print("\nFIRST 300 CHARS:")
        print(article.content[:300])
        print("\nLAST 300 CHARS:")
        print(article.content[-300:])
        
        # Check URL pattern
        print("\n" + "=" * 80)
        print("DETECTION CHECKS:")
        print(f"Has /world/ in URL: {'/world/' in article.url.lower()}")
        
        # Check copyright
        closing = article.content[-150:]
        copyright_patterns = [
            r"©\s*\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
            r"Copyright\s+\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
        ]
        
        found = False
        for pattern in copyright_patterns:
            match = re.search(pattern, closing, re.I)
            if match:
                print(f"✓ COPYRIGHT FOUND: '{match.group(0)}'")
                found = True
                break
        if not found:
            print("✗ No copyright in last 150 chars")
        
        # Check byline and dateline
        opening = article.content[:150]
        byline_patterns = [
            (r"^[A-Z][A-Z\s,]+\(AP\)\s*[—–-]", "AP dateline"),
            (r"^[A-Z][A-Z\s,]+\(Reuters\)\s*[—–-]", "Reuters dateline"),
            (r"^By (AP|Associated Press)", "AP byline"),
            (r"^(AP|Associated Press)\s*[—–-]", "AP byline"),
        ]
        for pattern, desc in byline_patterns:
            match = re.search(pattern, opening, re.I | re.M)
            if match:
                print(f"✓ {desc.upper()} FOUND: '{match.group(0)}'")
                found = True
                break
        
        print(f"\nWOULD BE DETECTED: {found}")
