#!/usr/bin/env python3
"""
Full scan of production database to find ALL articles that should be marked as WIRE.
Exports complete CSV with all details for review before making changes.
"""
import re
import csv
import sys
from src.models.database import DatabaseManager
from src.models import Article, CandidateLink

# Updated detection logic matching content_type_detector.py
WEAK_URL_PATTERNS = ["/ap-", "/cnn-", "/reuters-", "/wire/", "/world/", "/national/"]

COPYRIGHT_PATTERNS = [
    r"©\s*\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
    r"Copyright\s+\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
]

WIRE_BYLINE_PATTERNS = [
    # Datelines (STRONG)
    (r"^[A-Z][A-Z\s,]+\(AP\)\s*[—–-]", "AP dateline"),
    (r"^[A-Z][A-Z\s,]+\(Reuters\)\s*[—–-]", "Reuters dateline"),
    # Standard bylines
    (r"^By (AP|Associated Press|A\.P\.)", "AP byline"),
    (r"^By (Reuters)", "Reuters byline"),
    (r"^By (CNN)", "CNN byline"),
    (r"^By (NPR)", "NPR byline"),
]

OWN_DOMAINS = ["cnn.com", "apnews.com", "reuters.com", "npr.org"]


def check_wire(url, content):
    """Check if article should be marked as wire."""
    if not url or not content:
        return None
    
    url_lower = url.lower()
    
    # Skip if from wire service's own domain
    if any(d in url_lower for d in OWN_DOMAINS):
        return None
    
    # Check patterns
    weak_url = any(p in url_lower for p in WEAK_URL_PATTERNS)
    
    closing = content[-150:]
    copyright_found = any(re.search(p, closing, re.I) for p in COPYRIGHT_PATTERNS)
    
    opening = content[:150]
    byline_found = False
    byline_type = None
    for pattern, desc in WIRE_BYLINE_PATTERNS:
        if re.search(pattern, opening, re.I | re.M):
            byline_found = True
            byline_type = desc
            break
    
    # Decision logic
    if byline_found:
        return f"wire_byline ({byline_type})"
    elif copyright_found:
        return "copyright"
    elif weak_url and copyright_found:
        return "weak_url_plus_copyright"
    return None


def main():
    db = DatabaseManager()
    session = db.session
    
    print("Starting full scan of production database...", file=sys.stderr)
    print("This will check ALL articles not currently marked as wire.", file=sys.stderr)
    
    # Get total count first
    total_count = (
        session.query(Article)
        .filter(Article.status.notin_(['wire', 'wire_service']))
        .filter(Article.content.isnot(None))
        .filter(Article.content != '')
        .count()
    )
    
    print(f"Total articles to scan: {total_count}", file=sys.stderr)
    print("Scanning in batches...", file=sys.stderr)
    
    results = []
    batch_size = 1000
    processed = 0
    
    # Process in batches to avoid memory issues
    for offset in range(0, total_count, batch_size):
        articles = (
            session.query(Article)
            .join(CandidateLink)
            .filter(Article.status.notin_(['wire', 'wire_service']))
            .filter(Article.content.isnot(None))
            .filter(Article.content != '')
            .order_by(Article.extracted_at.desc())
            .limit(batch_size)
            .offset(offset)
            .all()
        )
        
        for a in articles:
            processed += 1
            if processed % 500 == 0:
                print(f"Progress: {processed}/{total_count} articles scanned...", file=sys.stderr)
            
            reason = check_wire(a.url, a.content)
            if reason:
                candidate = a.candidate_link
                results.append({
                    'id': a.id,
                    'url': a.url,
                    'title': (a.title or '')[:100],
                    'author': a.author or '',
                    'source': candidate.source_name if candidate else '',
                    'current_status': a.status,
                    'detection_reason': reason,
                    'extracted_at': str(a.extracted_at) if a.extracted_at else '',
                })
    
    print("\nScan complete!", file=sys.stderr)
    print(f"Total articles scanned: {processed}", file=sys.stderr)
    print(f"Articles to be changed to WIRE: {len(results)}", file=sys.stderr)
    
    # Output CSV to stdout
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=['id', 'url', 'title', 'author', 'source', 'current_status', 'detection_reason', 'extracted_at'],
    )
    writer.writeheader()
    writer.writerows(results)
    
    print(f"\n✓ Exported {len(results)} articles to CSV", file=sys.stderr)


if __name__ == "__main__":
    main()
