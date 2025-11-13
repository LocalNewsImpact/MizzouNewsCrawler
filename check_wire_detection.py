#!/usr/bin/env python3
"""Query production database for articles that would be newly detected as WIRE."""
import re
import csv
import sys
from src.models.database import DatabaseManager
from src.models import Article, CandidateLink

# Detection logic - matches updated content_type_detector.py
WEAK_URL_PATTERNS = ["/ap-", "/cnn-", "/reuters-", "/wire/", "/world/", "/national/"]
COPYRIGHT_PATTERNS = [
    r"©\s*\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
    r"Copyright\s+\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
]
WIRE_BYLINE_PATTERNS = [
    (r"^[A-Z][A-Z\s,]+\(AP\)\s*[—–-]", "AP"),
    (r"^[A-Z][A-Z\s,]+\(Reuters\)\s*[—–-]", "Reuters"),
    (r"^By (AP|Associated Press|A\.P\.)", "AP"),
    (r"^By (Reuters)", "Reuters"),
    (r"^By (CNN)", "CNN"),
    (r"^By (NPR)", "NPR"),
]
OWN_DOMAINS = ["cnn.com", "apnews.com", "reuters.com", "npr.org"]


def check_wire(url, content):
    """Check if article would be detected as wire with updated logic."""
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
    byline_found = any(re.search(p[0], opening, re.I | re.M) for p in WIRE_BYLINE_PATTERNS)
    
    # Decision logic
    if byline_found:
        return "wire_byline"
    elif copyright_found:
        return "copyright"
    elif weak_url and copyright_found:
        return "weak_url_plus_copyright"
    return None


def main():
    db = DatabaseManager()
    session = db.session
    
    print("Querying articles...", file=sys.stderr)
    
    # Query ALL articles that are NOT marked as wire
    # Remove limit to get complete list
    print("Querying ALL non-wire articles from production...", file=sys.stderr)
    articles = (
        session.query(Article)
        .join(CandidateLink)
        .filter(Article.status.notin_(['wire', 'wire_service']))
        .filter(Article.content.isnot(None))
        .filter(Article.content != '')
        .order_by(Article.extracted_at.desc())
        .all()
    )
    
    print(f"Analyzing {len(articles)} articles...", file=sys.stderr)
    
    results = []
    for a in articles:
        reason = check_wire(a.url, a.content)
        if reason:
            results.append({
                'id': a.id,
                'url': a.url,
                'title': (a.title or '')[:80],
                'author': a.author or '',
                'source': a.candidate_link.source_name if a.candidate_link else '',
                'status': a.status,
                'reason': reason,
            })
    
    print(f"\nFound {len(results)} articles that would be newly detected as WIRE\n", file=sys.stderr)
    
    # Output CSV to stdout with more detail
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            'id',
            'url',
            'title',
            'author',
            'source',
            'status',
            'reason',
        ],
    )
    writer.writeheader()
    writer.writerows(results)
    
    # Print summary to stderr
    print(f"\n{'='*80}", file=sys.stderr)
    print("DETECTION SUMMARY:", file=sys.stderr)
    print(f"Total articles checked: {len(articles)}", file=sys.stderr)
    print(f"Articles to mark as WIRE: {len(results)}", file=sys.stderr)
    
    # Breakdown by reason
    reason_counts = {}
    for r in results:
        reason_counts[r['reason']] = reason_counts.get(r['reason'], 0) + 1
    
    print("\nBy detection reason:", file=sys.stderr)
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)


if __name__ == "__main__":
    main()
