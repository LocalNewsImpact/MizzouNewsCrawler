#!/usr/bin/env python3
"""Scan production for articles that would be detected as wire with new logic.

This script runs IN THE PRODUCTION POD via kubectl exec.
It uses the updated ContentTypeDetector with author field detection.
"""
import csv
import os

from backend.app.lifecycle import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text as sql_text


def main():
    """Scan all labeled articles and find those that would be detected as wire."""
    db = DatabaseManager(database_url=os.getenv('DATABASE_URL'))
    detector = ContentTypeDetector()

    print("Scanning production database for articles to reclassify as wire...")
    print(f"Using detector version: {detector.VERSION}")
    print()

    with db.get_session() as session:
        # Get all labeled articles that might be wire
        # Focus on articles with wire service patterns
        query = sql_text("""
            SELECT 
                id,
                url,
                title,
                author,
                text,
                content,
                published_date,
                source
            FROM articles
            WHERE status = 'labeled'
            AND (
                author ILIKE '%afp%'
                OR author ILIKE '%reuters%'
                OR author ILIKE '%ap %'
                OR author ILIKE 'ap %'
                OR author ILIKE '% ap'
                OR url ILIKE '%/national/%'
                OR url ILIKE '%/world/%'
                OR text ILIKE '%told AFP%'
                OR text ILIKE '%told Reuters%'
            )
            ORDER BY published_date DESC
        """)
        
        result = session.execute(query)
        articles = list(result)
        
        print(f"Found {len(articles)} candidate articles to check")
        print("Testing with ContentTypeDetector...")
        print()
        
        # Test each article
        wire_articles = []
        for i, row in enumerate(articles, 1):
            article_id, url, title, author, article_text, content, pub_date, source = row
            
            if i % 100 == 0:
                print(f"Processed {i}/{len(articles)} articles...")
            
            # Build metadata
            metadata = {}
            if author:
                metadata["byline"] = author
            
            # Test detection
            detection_result = detector.detect(
                url=url or "",
                title=title,
                metadata=metadata,
                content=content or "",
            )
            
            # If detected as wire, add to results
            if detection_result and detection_result.status == "wire":
                wire_articles.append({
                    "id": str(article_id),
                    "url": url,
                    "title": title or "",
                    "author": author or "",
                    "source": source or "",
                    "published_date": str(pub_date) if pub_date else "",
                    "detection_reason": detection_result.reason or "",
                    "detection_evidence": str(detection_result.evidence),
                    "confidence": detection_result.confidence or "",
                    "text_preview": (article_text[:200] if article_text else "")[:200],
                })
        
        print(f"\nFound {len(wire_articles)} articles to reclassify as wire")
        
        # Write to CSV
        if wire_articles:
            output_file = "/tmp/wire_articles_to_update.csv"
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "id", "url", "title", "author", "source", "published_date",
                    "detection_reason", "detection_evidence", "confidence",
                    "text_preview"
                ])
                writer.writeheader()
                writer.writerows(wire_articles)

            print(f"\nWrote results to {output_file}")
            print("\nSummary by detection reason:")
            reason_counts = {}
            for article in wire_articles:
                reason = article["detection_reason"]
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            for reason, count in sorted(reason_counts.items()):
                print(f"  {reason}: {count}")

            return output_file
        else:
            print("No articles found to reclassify")
            return None


if __name__ == "__main__":
    output = main()
    if output:
        print(f"\n✅ CSV file created: {output}")
        print(
            "Copy with: "
            "kubectl cp production/POD_NAME:/tmp/wire_articles_to_update.csv ./"
        )
    else:
        print("\n❌ No articles to update")
