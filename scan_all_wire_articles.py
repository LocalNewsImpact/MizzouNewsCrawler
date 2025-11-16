#!/usr/bin/env python3
"""Find all articles that should be marked as wire using ContentTypeDetector."""
import csv
import sys
from src.models.database import DatabaseManager
from src.models import Article, CandidateLink
from src.utils.content_type_detector import ContentTypeDetector


def check_wire_with_detector(detector, article):
    """Check if article would be detected as wire using ContentTypeDetector."""
    if not article.url:
        return None
    
    # Build metadata with byline
    metadata = {"byline": article.author} if article.author else None
    
    # Test detection
    detection_result = detector.detect(
        url=article.url,
        title=article.title,
        metadata=metadata,
        content=article.content or article.text or "",
    )
    
    if detection_result and detection_result.status == "wire":
        # Extract service name and reason
        service = "Unknown"
        if "author" in detection_result.evidence:
            evidence_str = str(detection_result.evidence["author"])
            if "AFP" in evidence_str:
                service = "AFP"
            elif "Associated Press" in evidence_str:
                service = "AP"
            elif "Reuters" in evidence_str:
                service = "Reuters"
            elif "CNN" in evidence_str:
                service = "CNN"
        elif "content" in detection_result.evidence:
            evidence_str = str(detection_result.evidence["content"])
            if "AFP" in evidence_str:
                service = "AFP"
            elif "Associated Press" in evidence_str or "AP" in evidence_str:
                service = "AP"
            elif "Reuters" in evidence_str:
                service = "Reuters"
        
        return {
            "reason": detection_result.reason,
            "service": service,
            "confidence": detection_result.confidence,
        }
    
    return None


def main():
    db = DatabaseManager()
    session = db.session
    detector = ContentTypeDetector()
    
    print(f"Using ContentTypeDetector version: {detector.VERSION}", file=sys.stderr)
    print("Counting articles...", file=sys.stderr)
    total = (
        session.query(Article)
        .join(CandidateLink)
        .filter(Article.status.notin_(['wire', 'wire_service']))
        .filter(Article.content.isnot(None))
        .filter(Article.content != '')
        .count()
    )
    print(f"Found {total} non-wire articles to check", file=sys.stderr)
    
    # Process in batches
    batch_size = 500
    offset = 0
    
    # Output CSV header
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            'id', 'url', 'title', 'author', 'source',
            'status', 'reason', 'wire_service', 'confidence'
        ],
    )
    writer.writeheader()
    
    total_found = 0
    
    while offset < total:
        print(f"Processing batch {offset}-{offset+batch_size}...", file=sys.stderr)
        
        articles = (
            session.query(Article)
            .join(CandidateLink)
            .filter(Article.status.notin_(['wire', 'wire_service']))
            .filter(Article.content.isnot(None))
            .filter(Article.content != '')
            .order_by(Article.id)
            .limit(batch_size)
            .offset(offset)
            .all()
        )
        
        if not articles:
            break
        
        for a in articles:
            result = check_wire_with_detector(detector, a)
            if result:
                writer.writerow({
                    'id': a.id,
                    'url': a.url,
                    'title': (a.title or '')[:80],
                    'author': a.author or '',
                    'source': a.candidate_link.source_name if a.candidate_link else '',
                    'status': a.status,
                    'reason': result['reason'],
                    'wire_service': result['service'],
                    'confidence': result['confidence'],
                })
                total_found += 1
        
        offset += batch_size
        session.expunge_all()  # Clear session to free memory
    
    print("\n=== COMPLETE ===", file=sys.stderr)
    print(f"Total articles scanned: {total}", file=sys.stderr)
    print(f"Articles to mark as WIRE: {total_found}", file=sys.stderr)


if __name__ == "__main__":
    main()
