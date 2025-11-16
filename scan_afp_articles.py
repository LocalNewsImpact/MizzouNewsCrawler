#!/usr/bin/env python3
"""Scan production for articles that would be detected as wire with new author detection.

This script uses the updated ContentTypeDetector (v2025-11-12a) which now checks
the author/byline field for wire service patterns like "Afp Afp", "AP Staff", etc.
"""
import csv
import sys
from src.models.database import DatabaseManager
from src.models import Article
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import or_


def main():
    """Scan all labeled articles for wire detection using new author patterns."""
    db = DatabaseManager()
    detector = ContentTypeDetector()
    
    print(f"ContentTypeDetector version: {detector.VERSION}")
    print("Scanning production database for articles with wire author patterns...")
    print("=" * 80)
    
    with db.get_session() as session:
        # Query articles that:
        # 1. Current status = labeled (not already marked wire)
        # 2. Have author field matching wire patterns
        query = (
            session.query(Article)
            .filter(Article.status == "labeled")
            .filter(
                or_(
                    # AFP patterns
                    Article.author.ilike("%afp%"),
                    # AP patterns
                    Article.author.ilike("%associated press%"),
                    Article.author.ilike("ap staff%"),
                    Article.author.ilike("by ap%"),
                    # Reuters patterns
                    Article.author.ilike("reuters%"),
                    # CNN patterns  
                    Article.author.ilike("cnn wire%"),
                    Article.author.ilike("cnn staff%"),
                )
            )
        )
        
        total = query.count()
        print(f"Found {total} articles with potential wire author patterns\n")
        print("Testing with new detector...\n")
        
        results = []
        detected_count = 0
        
        for i, article in enumerate(query.all(), 1):
            if i % 50 == 0:
                print(f"Progress: {i}/{total} articles processed...")
            
            # Build metadata with byline
            metadata = {"byline": article.author} if article.author else None
            
            # Test with new detector
            detection_result = detector.detect(
                url=article.url or "",
                title=article.title,
                metadata=metadata,
                content=article.content or article.text or "",
            )
            
            if detection_result and detection_result.status == "wire":
                detected_count += 1
                
                # Extract service name from evidence
                service = "Unknown"
                if "author" in detection_result.evidence:
                    for evidence_str in detection_result.evidence["author"]:
                        if "AFP" in evidence_str:
                            service = "AFP"
                        elif "Associated Press" in evidence_str:
                            service = "AP"
                        elif "Reuters" in evidence_str:
                            service = "Reuters"
                        elif "CNN" in evidence_str:
                            service = "CNN"
                        break
                elif "content" in detection_result.evidence:
                    # Check content evidence for service name
                    for evidence_str in detection_result.evidence["content"]:
                        if "AFP" in evidence_str:
                            service = "AFP"
                        elif "Associated Press" in evidence_str or "AP" in evidence_str:
                            service = "AP"
                        elif "Reuters" in evidence_str:
                            service = "Reuters"
                        elif "CNN" in evidence_str:
                            service = "CNN"
                        break
                
                results.append({
                    "id": str(article.id),
                    "url": article.url,
                    "author": article.author,
                    "title": article.title[:100] if article.title else "",
                    "current_status": article.status,
                    "detected_status": detection_result.status,
                    "wire_service": service,
                    "confidence": detection_result.confidence,
                    "reason": detection_result.reason,
                    "evidence": str(detection_result.evidence),
                })
        
        print("\n" + ('=' * 80))
        print("Detection complete!")
        print(f"Total articles scanned: {total}")
        print(f"Articles detected as wire: {detected_count}")
        print(f"{('=' * 80)}\n")
        
        if not results:
            print("No articles detected as wire. Nothing to export.")
            return 0
        
        # Write results to CSV
        csv_filename = "afp_wire_articles_to_update.csv"
        with open(csv_filename, "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "id",
                "url", 
                "author",
                "title",
                "current_status",
                "detected_status",
                "wire_service",
                "confidence",
                "reason",
                "evidence",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"Results exported to: {csv_filename}")
        
        # Print summary by wire service
        service_counts = {}
        for row in results:
            service = row["wire_service"]
            service_counts[service] = service_counts.get(service, 0) + 1
        
        print("\nBreakdown by wire service:")
        for service, count in sorted(service_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {service}: {count}")
        
        return 0


if __name__ == "__main__":
    sys.exit(main())
