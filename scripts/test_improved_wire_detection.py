#!/usr/bin/env python3
"""Test improved wire detection on KRCU and small-town papers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Article, get_engine
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import select, or_
from sqlalchemy.orm import Session


def test_krcu_articles():
    """Test KRCU articles with NPR bylines."""
    engine = get_engine()
    detector = ContentTypeDetector()
    
    print("Testing KRCU articles (NPR affiliate)...")
    print("=" * 80)
    
    with Session(engine) as session:
        stmt = (
            select(Article)
            .where(Article.url.like("%krcu.org%"))
            .where(Article.status != "wire")
            .where(Article.content.isnot(None))
            .limit(30)
        )
        
        articles = session.scalars(stmt).all()
        print(f"\nTesting {len(articles)} KRCU articles\n")
        
        detected = 0
        for article in articles:
            result = detector.detect(
                url=article.url,
                title=article.title,
                metadata={"byline": article.author} if article.author else None,
                content=article.content,
            )
            
            if result and result.status == "wire":
                detected += 1
                print(f"✓ DETECTED: {article.title[:70]}")
                print(f"  URL: {article.url}")
                print(f"  Author: {article.author}")
                print(f"  Evidence: {result.evidence}")
                print()
        
        print("=" * 80)
        print(f"KRCU Detection: {detected}/{len(articles)} ({detected/len(articles)*100:.1f}%)\n")


def test_small_town_afp():
    """Test small-town papers with AFP content and /nation/ URLs."""
    engine = get_engine()
    detector = ContentTypeDetector()
    
    print("Testing small-town papers with /nation/ URLs...")
    print("=" * 80)
    
    with Session(engine) as session:
        # Test griffonnews, bransontrilakesnews, webstercountycitizen
        stmt = (
            select(Article)
            .where(
                or_(
                    Article.url.like("%griffonnews.com%"),
                    Article.url.like("%bransontrilakesnews.com%"),
                    Article.url.like("%webstercountycitizen.com%"),
                )
            )
            .where(Article.url.like("%/nation%"))
            .where(Article.status != "wire")
            .where(Article.content.isnot(None))
            .limit(20)
        )
        
        articles = session.scalars(stmt).all()
        print(f"\nTesting {len(articles)} small-town articles with /nation/ URLs\n")
        
        detected = 0
        for article in articles:
            result = detector.detect(
                url=article.url,
                title=article.title,
                metadata={"byline": article.author} if article.author else None,
                content=article.content,
            )
            
            if result and result.status == "wire":
                detected += 1
                print(f"✓ DETECTED: {article.title[:70]}")
                print(f"  URL: {article.url}")
                print(f"  Author: {article.author}")
                print(f"  Evidence: {result.evidence}")
                print()
        
        print("=" * 80)
        print(f"Small-town Detection: {detected}/{len(articles)} ({detected/len(articles)*100:.1f}%)\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("TESTING IMPROVED WIRE DETECTION")
    print("=" * 80 + "\n")
    
    test_krcu_articles()
    print("\n")
    test_small_town_afp()
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
