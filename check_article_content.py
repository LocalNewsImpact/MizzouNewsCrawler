#!/usr/bin/env python3
"""Check if world/national articles have copyright statements."""
import re
from src.models.database import DatabaseManager
from src.models import Article

db = DatabaseManager()
session = db.session

# Get one /world/ article
article = session.query(Article).filter(
    Article.url.like('%semissourian.com/world/ukraine%')
).first()

if article and article.content:
    print("URL:", article.url)
    print("Status:", article.status)
    print("Author:", article.author or "No author")
    print("\nFirst 200 chars:")
    print(article.content[:200])
    print("\nLast 300 chars:")
    print(article.content[-300:])
    
    # Check for copyright
    closing = article.content[-150:]
    copyright_patterns = [
        r"©\s*\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
        r"Copyright\s+\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
    ]
    
    print("\n" + "="*80)
    print("DETECTION CHECK:")
    for pattern in copyright_patterns:
        match = re.search(pattern, closing, re.I)
        if match:
            print(f"✓ COPYRIGHT FOUND: {match.group(0)}")
            break
    else:
        print("✗ No copyright found in last 150 chars")
