#!/bin/bash
# Run wire detection scan in production Kubernetes pod

set -e

echo "Finding production processor pod..."
POD=$(kubectl get pods -n production -l app=mizzou-processor -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD" ]; then
    echo "Error: No processor pod found in production namespace"
    exit 1
fi

echo "Using pod: $POD"
echo ""
echo "Running wire detection scan..."

# Copy the detector to the pod (in case it's not up to date)
kubectl cp src/utils/content_type_detector.py production/$POD:/tmp/content_type_detector.py

# Run the scan script
kubectl exec -n production $POD -- python3 << 'EOFPYTHON'
import csv
import sys
from pathlib import Path
from sqlalchemy import text

# Use the updated detector
sys.path.insert(0, '/tmp')
from content_type_detector import ContentTypeDetector

from src.models.database import DatabaseManager

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
            LIMIT 2000
        """)
        
        result = session.execute(query)
        rows = list(result)
        print(f"Found {len(rows)} non-wire articles to check")
        
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
                    "title": title[:80],
                    "author": author or "",
                    "current_status": status,
                    "wire_service": service,
                    "confidence": detection.confidence,
                    "evidence": str(ev.get("url", [])) if "url" in ev else "",
                })
        
        print(f"\nDetected {len(detected)}/{len(rows)} articles as wire ({len(detected)/len(rows)*100:.1f}%)")
        
        # Write to CSV
        if detected:
            output = "/tmp/production_wire_scan.csv"
            with open(output, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ["id", "url", "title", "author", "current_status", 
                             "wire_service", "confidence", "evidence"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(detected)
            print(f"CSV written to: {output}")
            
            # Show summary by service
            from collections import Counter
            service_counts = Counter(d["wire_service"] for d in detected)
            print("\nDetections by service:")
            for service, count in service_counts.most_common():
                print(f"  {service}: {count}")
        
        return 0

if __name__ == "__main__":
    sys.exit(main())
EOFPYTHON

# Copy the results back
echo ""
echo "Copying results from pod..."
kubectl cp production/$POD:/tmp/production_wire_scan.csv /tmp/production_wire_scan.csv

echo ""
echo "Results saved to: /tmp/production_wire_scan.csv"
