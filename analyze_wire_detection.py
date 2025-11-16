"""
Analyze articles in the database to find which would be newly detected as WIRE
with the updated detection logic.
"""
import re
import csv
from datetime import datetime
from sqlalchemy import text
from src.models.database import DatabaseManager

# Updated detection logic
WEAK_URL_PATTERNS = ["/ap-", "/cnn-", "/reuters-", "/wire/", "/world/", "/national/"]

COPYRIGHT_PATTERNS = [
    r"©\s*\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
    r"Copyright\s+\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR)",
    r"All rights reserved\.?\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|NPR)",
]

WIRE_BYLINE_PATTERNS = [
    (r"^By (AP|Associated Press|A\.P\.)", "Associated Press"),
    (r"^(AP|Associated Press|A\.P\.)\s*[—–-]", "Associated Press"),
    (r"^By (Reuters)", "Reuters"),
    (r"^(Reuters)\s*[—–-]", "Reuters"),
    (r"^By (CNN)", "CNN"),
    (r"^(CNN)\s*[—–-]", "CNN"),
    (r"^By (Bloomberg)", "Bloomberg"),
    (r"^(Bloomberg)\s*[—–-]", "Bloomberg"),
    (r"^By (NPR|National Public Radio)", "NPR"),
    (r"^(NPR)\s*[—–-]", "NPR"),
]

OWN_SOURCE_DOMAINS = {
    "cnn.com": "CNN",
    "apnews.com": "Associated Press",
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "npr.org": "NPR",
    "pbs.org": "PBS",
}


def check_wire_detection(url: str, content: str) -> dict:
    """Check if article would be detected as wire with updated logic."""
    if not url or not content:
        return {"is_wire": False, "reason": "missing_data"}
    
    url_lower = url.lower()
    
    # Check if from wire service's own domain (not syndicated)
    for domain in OWN_SOURCE_DOMAINS.keys():
        if domain in url_lower:
            return {"is_wire": False, "reason": "own_source_domain"}
    
    # Check weak URL patterns
    weak_url_match = False
    url_patterns_found = []
    for pattern in WEAK_URL_PATTERNS:
        if pattern in url_lower:
            weak_url_match = True
            url_patterns_found.append(pattern)
    
    # Check for copyright in closing
    closing = content[-150:] if len(content) > 150 else content
    copyright_found = False
    copyright_text = None
    for pattern in COPYRIGHT_PATTERNS:
        match = re.search(pattern, closing, re.IGNORECASE)
        if match:
            copyright_found = True
            copyright_text = match.group(0)
            break
    
    # Check for wire byline in opening
    opening = content[:150] if len(content) > 150 else content
    wire_byline_found = False
    byline_text = None
    for pattern, service_name in WIRE_BYLINE_PATTERNS:
        match = re.search(pattern, opening, re.MULTILINE | re.IGNORECASE)
        if match:
            wire_byline_found = True
            byline_text = match.group(0)
            break
    
    # Apply conservative decision logic
    has_strong_evidence = wire_byline_found or copyright_found
    
    # Determine if would be detected
    is_wire = False
    reason = None
    evidence = []
    
    if wire_byline_found:
        is_wire = True
        reason = "wire_byline"
        evidence.append(f"byline: {byline_text}")
    elif copyright_found:
        is_wire = True
        reason = "copyright"
        evidence.append(f"copyright: {copyright_text}")
    elif weak_url_match and has_strong_evidence:
        is_wire = True
        reason = "weak_url_plus_content"
        evidence.extend([f"url: {p}" for p in url_patterns_found])
    
    return {
        "is_wire": is_wire,
        "reason": reason,
        "evidence": "; ".join(evidence) if evidence else None,
        "url_patterns": url_patterns_found,
        "copyright": copyright_text,
        "byline": byline_text,
    }


def main():
    # Connect to database using DatabaseManager
    try:
        db_manager = DatabaseManager()
        session = db_manager.session
        print("Connected to database successfully")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return
    
    # Import models
    from src.models import Article, CandidateLink
    
    # Query articles that are NOT currently marked as wire
    # Check recent articles (last 90 days)
    articles = (
        session.query(Article)
        .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
        .filter(Article.status.notin_(['wire', 'wire_service']))
        .filter(Article.content.isnot(None))
        .filter(Article.content != '')
        .filter(
            Article.extracted_at >= text("NOW() - INTERVAL '90 days'")
        )
        .order_by(Article.extracted_at.desc())
        .limit(1000)
        .all()
    )
    
    print(f"Found {len(articles)} non-wire articles from last 90 days\n")
    
    # Analyze each article
    newly_detected = []
    
    for article in articles:
        detection = check_wire_detection(article.url, article.content)
        
        if detection["is_wire"]:
            candidate = article.candidate_link
            source_name = candidate.source_name if candidate else "Unknown"
            
            newly_detected.append({
                "article_id": article.id,
                "url": article.url,
                "title": article.title,
                "author": article.author,
                "publish_date": article.publish_date,
                "source_name": source_name,
                "current_status": article.status,
                "detection_reason": detection["reason"],
                "evidence": detection["evidence"],
            })
    
    print(
        f"Found {len(newly_detected)} articles that would be newly "
        "detected as WIRE\n"
    )
    
    # Export to CSV
    if newly_detected:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"newly_detected_wire_articles_{timestamp}.csv"
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'article_id', 'url', 'title', 'author', 'publish_date',
                'source_name', 'current_status', 'detection_reason',
                'evidence',
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(newly_detected)
        
        print(f"Exported to: {output_file}")
        
        # Print summary
        print("\n=== SUMMARY ===")
        print(f"Total articles analyzed: {len(articles)}")
        print(f"Newly detected as WIRE: {len(newly_detected)}")
        print("\nDetection reasons:")
        reason_counts = {}
        for article in newly_detected:
            reason = article['detection_reason']
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        for reason, count in sorted(
            reason_counts.items(), key=lambda x: -x[1]
        ):
            print(f"  {reason}: {count}")
        
        # Print first 10 examples
        print("\n=== FIRST 10 EXAMPLES ===")
        for i, article in enumerate(newly_detected[:10], 1):
            print(f"\n{i}. {article['title'][:80]}...")
            print(f"   URL: {article['url']}")
            print(f"   Source: {article['source_name']}")
            print(f"   Reason: {article['detection_reason']}")
            print(f"   Evidence: {article['evidence'][:100]}...")
    else:
        print("No articles would be newly detected as WIRE.")


if __name__ == "__main__":
    main()
