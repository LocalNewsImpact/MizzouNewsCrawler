#!/usr/bin/env python3
"""Scan audit URLs against production to see what the new detector finds.

This script takes the more_wire_stories.csv audit file and checks each URL
against production database to see if the new detector would mark it as wire.
"""

import csv
import sys
from pathlib import Path

from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text


def main():
    audit_file = Path("more_wire_stories.csv")
    output_file = Path("/tmp/audit_detection_results.csv")
    
    if not audit_file.exists():
        print(f"Error: {audit_file} not found")
        return 1
    
    # Load audit URLs (format: title, url, author, empty)
    audit_urls = []
    with open(audit_file, encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                audit_urls.append(row[1])  # URL is second column
    
    print(f"Loaded {len(audit_urls)} URLs from audit file")
    
    # Connect to database
    db = DatabaseManager()
    detector = ContentTypeDetector()
    print(f"Using detector version: {detector.VERSION}")
    
    # Scan articles
    results = []
    found_count = 0
    detected_count = 0
    
    with db.get_session() as session:
        for i, url in enumerate(audit_urls):
            if (i + 1) % 100 == 0:
                print(f"Processed {i + 1}/{len(audit_urls)} URLs...")
            
            # Find article in database
            query = text(
                "SELECT id, url, title, content, author, status "
                "FROM articles WHERE url = :url LIMIT 1"
            )
            result = session.execute(query, {"url": url})
            row = result.fetchone()
            
            if not row:
                continue
                
            found_count += 1
            article_id, db_url, title, content, author, status = row
            
            # Test detection
            metadata = {"byline": author} if author else None
            detection = detector.detect(
                url=db_url or "",
                title=title,
                metadata=metadata,
                content=content or '',
            )
            
            is_detected = detection and detection.status == 'wire'
            if is_detected:
                detected_count += 1
            
            # Extract service
            service = "None"
            if detection and detection.status == 'wire':
                ev = detection.evidence or {}
                if "detected_services" in ev and ev["detected_services"]:
                    service = ev["detected_services"][0]
            
            results.append({
                "id": article_id,
                "url": db_url or "",
                "title": title or "",
                "author": author or "",
                "current_status": status,
                "detected": "YES" if is_detected else "NO",
                "wire_service": service,
                "confidence": detection.confidence if detection else "",
                "evidence": str(detection.evidence) if detection else "",
            })
    
    # Write results
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = [
            "id", "url", "title", "author", "current_status",
            "detected", "wire_service", "confidence", "evidence"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print("\nResults:")
    print(f"  Audit URLs: {len(audit_urls)}")
    print(f"  Found in database: {found_count}")
    print(f"  Detected as wire: {detected_count}")
    if found_count > 0:
        rate = detected_count / found_count * 100
        print(f"  Detection rate: {rate:.1f}%")
    else:
        print("  Detection rate: N/A")
    print(f"\nCSV written to: {output_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
