#!/usr/bin/env python3
"""Build cross-domain byline frequency database."""

import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Article, get_engine
from sqlalchemy import select
from sqlalchemy.orm import Session


def extract_domain(url: str) -> str:
    """Extract base domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or ""
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()
    except Exception:
        return ""


def main():
    """Build byline→domain frequency mapping."""
    print("Building cross-domain byline frequency database...")
    print("=" * 80)
    
    engine = get_engine()
    
    # Map: author_name → set of domains
    author_domains = defaultdict(set)
    
    with Session(engine) as session:
        # Get all articles with authors
        stmt = select(Article.author, Article.url).where(
            Article.author.isnot(None),
            Article.content.isnot(None)
        )
        
        print("Scanning articles...")
        count = 0
        for author, url in session.execute(stmt):
            domain = extract_domain(url)
            if domain:
                # Split multi-author bylines
                authors = author.replace(" and ", ", ").split(",")
                for a in authors:
                    a = a.strip()
                    if a:
                        author_domains[a.lower()].add(domain)
            
            count += 1
            if count % 10000 == 0:
                print(f"  Processed {count:,} articles...")
    
    print(f"✓ Processed {count:,} total articles")
    print(f"✓ Found {len(author_domains):,} unique author names")
    
    # Find authors appearing on multiple domains
    multi_domain_authors = {
        author: list(domains)
        for author, domains in author_domains.items()
        if len(domains) >= 3  # Appears on 3+ different sites
    }
    
    print(f"✓ Found {len(multi_domain_authors):,} authors on 3+ domains")
    
    # Show top cross-domain authors
    print("\nTop 20 cross-domain authors:")
    print("-" * 80)
    sorted_authors = sorted(
        multi_domain_authors.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )
    for author, domains in sorted_authors[:20]:
        print(f"{author:40s} ({len(domains):3d} domains)")
    
    # Save to file
    output_file = "/tmp/cross_domain_bylines.json"
    with open(output_file, "w") as f:
        json.dump(multi_domain_authors, f, indent=2)
    
    print("\n" + "=" * 80)
    print(f"✓ Saved cross-domain byline database to {output_file}")
    print(f"  Total multi-domain authors: {len(multi_domain_authors):,}")


if __name__ == "__main__":
    main()
