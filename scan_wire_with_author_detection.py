#!/usr/bin/env python3
"""Scan production for AFP/wire articles using updated ContentTypeDetector.

Run this in the production API pod to generate CSV of articles to update.
"""
import csv
import sys
from backend.app.lifecycle import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text as sql_text


def main():
    db = DatabaseManager(database_url=None)  # Uses production DATABASE_URL
    detector = ContentTypeDetector()
    
    print(f"ContentTypeDetector version: {detector.VERSION}")
    print("=" * 80)
    
    with db.get_session() as session:
        # Get all labeled articles with potential wire author patterns
        result = session.execute(sql_text("""
            SELECT id, url, author, title, content, text
            FROM articles
            WHERE status = 'labeled'
            AND (
                author ILIKE '%afp%'
                OR author ILIKE '%associated press%'
                OR author ILIKE 'ap staff%'
                OR author ILIKE 'by ap%'
                OR author ILIKE 'reuters%'
                OR author ILIKE 'cnn wire%'
                OR author ILIKE 'cnn staff%'
            )
        """))
        
        articles = list(result)
        print(f"Found {len(articles)} articles with wire author patterns")
        print("Testing with new detector...\n")
        
        results = []
        detected_count = 0
        
        for i, row in enumerate(articles, 1):
            if i % 50 == 0:
                print(f"Progress: {i}/{len(articles)}")
            
            article_id, url, author, title, content, text_col = row
            
            # Build metadata with byline
            metadata = {"byline": author} if author else None
            
            # Test detection
            detection_result = detector.detect(
                url=url or "",
                title=title,
                metadata=metadata,
                content=content or text_col or "",
            )
            
            if detection_result and detection_result.status == "wire":
                detected_count += 1
                
                # Extract service name from evidence
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
                    elif "CNN" in evidence_str:
                        service = "CNN"
                
                results.append({
                    "id": str(article_id),
                    "url": url or "",
                    "author": author or "",
                    "title": (title[:100] if title else "")[:100],
                    "current_status": "labeled",
                    "detected_status": "wire",
                    "wire_service": service,
                    "confidence": detection_result.confidence,
                    "reason": detection_result.reason,
                })
        
        print(f"\n{'=' * 80}")
        print(f"Detection complete: {detected_count}/{len(articles)} detected as wire")
        print(f"{'=' * 80}\n")
        
        # Write CSV
        csv_filename = "/tmp/wire_articles_to_update.csv"
        with open(csv_filename, "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "id", "url", "author", "title", "current_status",
                "detected_status", "wire_service", "confidence", "reason"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"CSV written to: {csv_filename}")
        
        # Summary by service
        service_counts = {}
        for row in results:
            service = row["wire_service"]
            service_counts[service] = service_counts.get(service, 0) + 1
        
        print("\nBreakdown by wire service:")
        for service, count in sorted(
            service_counts.items(), key=lambda x: x[1], reverse=True
        ):
            print(f"  {service}: {count}")
        
        return 0


if __name__ == "__main__":
    sys.exit(main())
