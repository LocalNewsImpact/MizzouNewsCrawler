#!/usr/bin/env python3
"""Find all AFP/wire articles using updated ContentTypeDetector v2025-11-12a."""
import csv
import sys
from src.models.database import DatabaseManager
from src.models import Article, CandidateLink
from src.utils.content_type_detector import ContentTypeDetector


def main():
    db = DatabaseManager()
    session = db.session
    detector = ContentTypeDetector()
    
    print(f"ContentTypeDetector version: {detector.VERSION}", file=sys.stderr)
    print("Counting articles...", file=sys.stderr)
    
    total = (
        session.query(Article)
        .join(CandidateLink)
        .filter(Article.status.notin_(['wire', 'wire_service']))
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
        print(
            f"Processing batch {offset}-{offset+batch_size}...",
            file=sys.stderr
        )
        
        articles = (
            session.query(Article)
            .join(CandidateLink)
            .filter(Article.status.notin_(['wire', 'wire_service']))
            .order_by(Article.id)
            .limit(batch_size)
            .offset(offset)
            .all()
        )
        
        if not articles:
            break
        
        for a in articles:
            # Build metadata with author
            metadata = {"byline": a.author} if a.author else None
            
            # Run detection
            result = detector.detect(
                url=a.url or "",
                title=a.title,
                metadata=metadata,
                content=a.content or a.text or "",
            )
            
            if result and result.status == "wire":
                # Extract service name
                service = "Unknown"
                if "author" in result.evidence:
                    ev = str(result.evidence["author"])
                    if "AFP" in ev:
                        service = "AFP"
                    elif "Associated Press" in ev:
                        service = "AP"
                    elif "Reuters" in ev:
                        service = "Reuters"
                    elif "CNN" in ev:
                        service = "CNN"
                elif "content" in result.evidence:
                    ev = str(result.evidence["content"])
                    if "AFP" in ev:
                        service = "AFP"
                    elif "Associated Press" in ev or "AP" in ev:
                        service = "AP"
                    elif "Reuters" in ev:
                        service = "Reuters"
                
                writer.writerow({
                    'id': a.id,
                    'url': a.url,
                    'title': (a.title or '')[:80],
                    'author': a.author or '',
                    'source': (
                        a.candidate_link.source_name
                        if a.candidate_link else ''
                    ),
                    'status': a.status,
                    'reason': result.reason,
                    'wire_service': service,
                    'confidence': result.confidence,
                })
                total_found += 1
        
        offset += batch_size
        session.expunge_all()
    
    print("\n=== COMPLETE ===", file=sys.stderr)
    print(f"Total articles scanned: {total}", file=sys.stderr)
    print(f"Articles to mark as WIRE: {total_found}", file=sys.stderr)


if __name__ == "__main__":
    main()
