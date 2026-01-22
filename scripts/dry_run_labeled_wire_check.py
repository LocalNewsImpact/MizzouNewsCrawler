#!/usr/bin/env python3
"""
Dry-run check for labeled articles that would now be detected as wire.

This script queries production via kubectl to check articles with status='labeled'
and identifies which ones would be detected as wire using the new detection logic.
Results are exported to CSV.
"""

import csv
import subprocess
import json
from datetime import datetime


def run_kubectl_query(sql_query: str) -> list:
    """Execute SQL query in production via kubectl."""
    cmd = [
        "kubectl", "exec", "-n", "production",
        "deployment/mizzou-api", "--",
        "python", "-c",
        f"""
from src.models.database import DatabaseManager
from sqlalchemy import text
import json

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''{sql_query}''')).fetchall()
    for row in result:
        print(json.dumps(dict(row._mapping)))
"""
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    # Parse JSON lines
    rows = []
    for line in result.stdout.strip().split('\n'):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return rows


def check_wire_detection(article_id: int, url: str, title: str, text: str, author: str) -> dict:
    """Check if article would be detected as wire using new detection."""
    cmd = [
        "kubectl", "exec", "-n", "production",
        "deployment/mizzou-api", "--",
        "python", "-c",
        f"""
from src.utils.content_type_detector import ContentTypeDetector
from src.models.database import DatabaseManager
import json

db = DatabaseManager()
with db.get_session() as session:
    detector = ContentTypeDetector(session=session)

    result = detector._detect_wire_service(
        url={json.dumps(url)},
        content={json.dumps(text or '')},
        metadata={{'author': {json.dumps(author)}}}
    )

    if result and result.status == 'wire':
        print(json.dumps({{
            'is_wire': True,
            'confidence': result.confidence,
            'confidence_score': result.confidence_score,
            'reason': result.reason,
            'detected_services': result.evidence.get('detected_services', []),
            'detection_tier': result.evidence.get('detection_tier', 'unknown'),
        }}))
    else:
        print(json.dumps({{'is_wire': False}}))
"""
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        return json.loads(result.stdout.strip())
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Error checking article {article_id}: {e}")
        return {'is_wire': False}


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv = f"labeled_articles_wire_check_{timestamp}.csv"

    print("=" * 80)
    print("Dry-Run: Check Labeled Articles for Wire Detection")
    print("=" * 80)
    print()

    # Get labeled articles from production
    print("Fetching labeled articles from production...")
    sql = """
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
        LIMIT 5000
    """

    articles = run_kubectl_query(sql)
    print(f"Found {len(articles)} labeled articles to check")
    print()

    # Check each article
    wire_detected = []
    not_wire = []

    print("Checking articles with new wire detection...")
    for i, article in enumerate(articles, 1):
        if i % 100 == 0:
            print(f"  Processed {i}/{len(articles)}...")

        detection = check_wire_detection(
            article['id'],
            article['url'],
            article['title'],
            article['text'],
            article['author']
        )

        if detection['is_wire']:
            wire_detected.append({
                'article_id': article['id'],
                'url': article['url'],
                'title': article['title'][:100],
                'author': article['author'],
                'source': article['source'],
                'publish_date': article['publish_date'],
                'confidence': detection.get('confidence', ''),
                'confidence_score': detection.get('confidence_score', ''),
                'detected_services': ','.join(detection.get('detected_services', [])),
                'detection_tier': detection.get('detection_tier', ''),
                'reason': detection.get('reason', ''),
            })
        else:
            not_wire.append(article['id'])

    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total articles checked: {len(articles)}")
    print(f"Would be detected as wire: {len(wire_detected)} ({100*len(wire_detected)/len(articles):.1f}%)")
    print(f"Would remain labeled: {len(not_wire)} ({100*len(not_wire)/len(articles):.1f}%)")
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

        # Show sample
        print("Sample wire detections:")
        for item in wire_detected[:10]:
            print(f"  [{item['source']}] {item['title']}")
            print(f"    Service: {item['detected_services']} | Tier: {item['detection_tier']} | Confidence: {item['confidence']}")
            print()
    else:
        print("No wire articles detected.")


if __name__ == "__main__":
    main()
