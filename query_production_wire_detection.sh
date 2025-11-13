#!/bin/bash
# Query production database to find articles that would be newly detected as WIRE

kubectl exec -n production deployment/mizzou-api -- python3 << 'PYTHON_EOF'
import re
import json
from datetime import datetime
from src.models.database import DatabaseManager
from src.models import Article, CandidateLink

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


def check_wire_detection(url, content):
    """Check if article would be detected as wire with updated logic."""
    if not url or not content:
        return {"is_wire": False, "reason": "missing_data"}
    
    url_lower = url.lower()
    
    # Check if from wire service's own domain
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
    }


# Connect to production database
db = DatabaseManager()
session = db.session

print("Connected to production database")

# Query articles that are NOT wire
articles = (
    session.query(Article)
    .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
    .filter(Article.status.notin_(['wire', 'wire_service']))
    .filter(Article.content.isnot(None))
    .filter(Article.content != '')
    .order_by(Article.extracted_at.desc())
    .limit(500)
    .all()
)

print(f"Found {len(articles)} non-wire articles")

# Analyze
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
            "publish_date": str(article.publish_date) if article.publish_date else None,
            "source_name": source_name,
            "current_status": article.status,
            "detection_reason": detection["reason"],
            "evidence": detection["evidence"],
        })

print(f"\nFound {len(newly_detected)} articles that would be newly detected as WIRE")

# Print as JSON
print("\n" + json.dumps(newly_detected, indent=2, default=str))

PYTHON_EOF
