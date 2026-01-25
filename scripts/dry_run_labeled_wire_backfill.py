#!/usr/bin/env python3
"""
Dry-run backfill: Check labeled articles for wire detection and export to CSV.

This script runs entirely in the production pod to check articles with status='labeled'
against the new wire detection logic and exports results to CSV.
"""

import subprocess
import sys


def main():
    # Script to run in production pod
    remote_script = """
import csv
import sys
from datetime import datetime
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_csv = f"/tmp/labeled_articles_wire_check_{timestamp}.csv"

print("=" * 80)
print("Dry-Run: Check Labeled Articles for Wire Detection")
print("=" * 80)
print()

db = DatabaseManager()

with db.get_session() as session:
    detector = ContentTypeDetector(session=session)

    # Get labeled articles
    print("Fetching labeled articles from database...")
    result = session.execute(text('''
        SELECT
            a.id,
            a.url,
            a.title,
            a.text,
            a.author,
            cl.source,
            a.publish_date
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
        AND a.text IS NOT NULL
        AND a.text != ''
        ORDER BY a.publish_date DESC
        LIMIT 10000
    ''')).fetchall()

    articles = result
    print(f"Found {len(articles)} labeled articles to check")
    print()

    # Check each article
    wire_detected = []
    not_wire_count = 0

    print("Checking articles with new wire detection...")
    for i, row in enumerate(articles, 1):
        if i % 500 == 0:
            print(f"  Processed {i}/{len(articles)}... (found {len(wire_detected)} wire so far)")

        article_id = row[0]
        url = row[1]
        title = row[2]
        text = row[3]
        author = row[4]
        source = row[5]
        publish_date = row[6]

        # Run wire detection
        detection = detector._detect_wire_service(
            url=url,
            content=text or '',
            metadata={'author': author}
        )

        if detection and detection.status == 'wire':
            detected_services = detection.evidence.get('detected_services', [])
            detection_tier = detection.evidence.get('detection_tier', 'unknown')

            wire_detected.append({
                'article_id': article_id,
                'url': url,
                'title': (title or '')[:100],
                'author': author or '',
                'source': source,
                'publish_date': str(publish_date) if publish_date else '',
                'confidence': detection.confidence,
                'confidence_score': f"{detection.confidence_score:.3f}",
                'detected_services': ','.join(detected_services),
                'detection_tier': detection_tier,
                'reason': detection.reason,
            })
        else:
            not_wire_count += 1

    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total articles checked: {len(articles)}")
    print(f"Would be detected as wire: {len(wire_detected)} ({100*len(wire_detected)/len(articles) if articles else 0:.1f}%)")
    print(f"Would remain labeled: {not_wire_count} ({100*not_wire_count/len(articles) if articles else 0:.1f}%)")
    print()

    # Export to CSV
    if wire_detected:
        with open(output_csv, 'w', newline='') as f:
            fieldnames = [
                'article_id', 'url', 'title', 'author', 'source', 'publish_date',
                'confidence', 'confidence_score', 'detected_services',
                'detection_tier', 'reason'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(wire_detected)

        print(f"Exported {len(wire_detected)} wire detections to: {output_csv}")
        print()

        # Show breakdown by service
        from collections import Counter
        service_counts = Counter()
        tier_counts = Counter()
        for item in wire_detected:
            services = item['detected_services'].split(',')
            for service in services:
                if service:
                    service_counts[service] += 1
            tier_counts[item['detection_tier']] += 1

        print("Breakdown by wire service:")
        for service, count in service_counts.most_common(20):
            print(f"  {service}: {count}")

        print()
        print("Breakdown by detection tier:")
        for tier, count in tier_counts.most_common():
            print(f"  {tier}: {count}")

        print()
        print("Sample wire detections:")
        for item in wire_detected[:15]:
            print(f"  [{item['source']}] {item['title']}")
            print(f"    Service: {item['detected_services']} | Tier: {item['detection_tier']} | Confidence: {item['confidence']}")
            print()

        print(f"\\nOutput file location: {output_csv}")
        print("To download: kubectl cp production/mizzou-api-<pod-id>:{output_csv} .")
    else:
        print("No wire articles detected.")

print("\\nDRY RUN: No database changes were made")
"""

    print("Running wire detection backfill check in production...")
    print("This may take several minutes for 10,000 articles...")
    print()

    # Execute in production pod
    cmd = [
        "kubectl", "exec", "-n", "production",
        "deployment/mizzou-api", "--",
        "python", "-c", remote_script
    ]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: Command failed with exit code {e.returncode}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
