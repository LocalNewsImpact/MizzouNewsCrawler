#!/usr/bin/env python3
"""Scan production articles for wire content using updated detector."""

import csv
from sqlalchemy import text
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector


def main():
    db = DatabaseManager()
    detector = ContentTypeDetector()
    
    print(f"Detector version: {detector.VERSION}")
    
    with db.get_session() as session:
        # Query non-wire articles with content
        query = text("""
            SELECT id, url, title, content, author, status
            FROM articles
            WHERE status != 'wire'
            AND content IS NOT NULL
            AND content != ''
            ORDER BY publish_date DESC
        """)
        
        result = session.execute(query)
        rows = list(result)
        print(f"Found {len(rows)} non-wire articles to check\n")
        
        detected = []
        for i, (article_id, url, title, content, author, status) in enumerate(rows):
            if (i + 1) % 250 == 0:
                print(f"Processed {i + 1}/{len(rows)}...")
            
            metadata = {"byline": author} if author else None
            detection = detector.detect(
                url=url or "",
                title=title,
                metadata=metadata,
                content=content or '',
            )
            
            if detection and detection.status == 'wire':
                ev = detection.evidence or {}
                service = "Unknown"
                if "detected_services" in ev and ev["detected_services"]:
                    service = ev["detected_services"][0]
                
                detected.append({
                    "id": article_id,
                    "url": url,
                    "title": title[:80] if title else "",
                    "author": author or "",
                    "current_status": status,
                    "wire_service": service,
                    "confidence": detection.confidence,
                    "evidence": str(ev.get("url", [])) if "url" in ev else "",
                })
        
        print(f"\nDetected {len(detected)}/{len(rows)} articles as wire")
        if len(rows) > 0:
            print(f"Detection rate: {len(detected)/len(rows)*100:.1f}%")
        
        # Write to CSV
        if detected:
            output = "/tmp/production_wire_scan.csv"
            with open(output, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    "id", "url", "title", "author", "current_status",
                    "wire_service", "confidence", "evidence"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(detected)
            print(f"\nCSV written to: {output}")
            
            # Show summary by service
            from collections import Counter
            service_counts = Counter(d["wire_service"] for d in detected)
            print("\nDetections by service:")
            for service, count in service_counts.most_common():
                print(f"  {service}: {count}")
        else:
            print("\nNo wire articles detected")
        
        return 0


if __name__ == "__main__":
    exit(main())
