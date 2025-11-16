#!/usr/bin/env python3
"""Test wire reporter detection on KRCU articles."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Article, get_engine
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import select
from sqlalchemy.orm import Session

def main():
    """Test wire reporter detection on KRCU articles."""
    # Connect to production DB (via kubectl port-forward or exec)
    engine = get_engine()
    detector = ContentTypeDetector()
    
    print("Testing wire reporter detection on KRCU.org articles...")
    print("=" * 80)
    
    with Session(engine) as session:
        # Get non-wire KRCU articles with bylines
        stmt = (
            select(Article)
            .where(Article.url.like("%krcu.org%"))
            .where(Article.status != "wire")
            .where(Article.author.isnot(None))
            .limit(50)
        )
        
        articles = session.scalars(stmt).all()
        print(f"\nFound {len(articles)} KRCU articles to test\n")
        
        detected_count = 0
        for article in articles:
            result = detector.detect(
                url=article.url,
                title=article.title,
                metadata={"byline": article.author} if article.author else None,
                content=article.content[:500] if article.content else None
            )
            
            if result and result.status == "wire":
                detected_count += 1
                print(f"✓ DETECTED: {article.author}")
                print(f"  Evidence: {result.evidence}")
                print()
        
        print("=" * 80)
        print(f"Detection rate: {detected_count}/{len(articles)} ({detected_count/len(articles)*100:.1f}%)")

if __name__ == "__main__":
    main()
