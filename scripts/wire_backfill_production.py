#!/usr/bin/env python3
"""
Production wire detection backfill - runs via kubectl exec.
Processes articles in batches to avoid memory issues.
"""

import subprocess
from datetime import datetime

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv = f"labeled_to_wire_candidates_{timestamp}.csv"

    print(f"Starting production wire detection dry-run backfill")
    print(f"Output: {output_csv}")
    print()

    # Run detection in production pod
    script = """
import csv
import sys
from sqlalchemy import text as sql_text
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector

db = DatabaseManager()
total_checked = 0
total_wire = 0
batch_size = 500

with db.get_session() as session:
    detector = ContentTypeDetector(session=session)

    # Get total count
    total = session.execute(sql_text('''
        SELECT COUNT(*)
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
        AND a.text IS NOT NULL
        AND a.text != ''
    ''')).scalar()

    print(f'Total articles to check: {total:,}', file=sys.stderr)

    # Write CSV header
    print('article_id,url,title,author,source,detected_service,confidence,detection_tier,reason')

    offset = 0
    while offset < total:
        results = session.execute(sql_text('''
            SELECT
                a.id,
                a.url,
                a.title,
                a.author,
                a.text,
                cl.source
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
            AND a.text IS NOT NULL
            AND a.text != ''
            ORDER BY a.id
            LIMIT :batch_size OFFSET :offset
        '''), {'batch_size': batch_size, 'offset': offset}).fetchall()

        if not results:
            break

        for row in results:
            total_checked += 1
            article_id, url, title, author, text_content, source = row

            # Run detection
            result = detector._detect_wire_service(
                url=url,
                content=text_content or title or '',
                metadata={'author': author}
            )

            if result and result.status == 'wire':
                total_wire += 1

                services = result.evidence.get('detected_services', [])
                service = services[0] if services else 'Unknown'
                tier = result.evidence.get('detection_tier', 'unknown')

                # Clean fields for CSV
                title_clean = (title or '').replace(',', ' ').replace('\\n', ' ')[:100]
                author_clean = (author or '').replace(',', ' ')
                reason_clean = (result.reason or '').replace(',', ' ').replace('\\n', ' ')[:200]

                print(f'{article_id},{url},{title_clean},{author_clean},{source},{service},{result.confidence},{tier},{reason_clean}')

            if total_checked % 100 == 0:
                print(f'Checked {total_checked:,}/{total:,} - Wire: {total_wire:,}', file=sys.stderr)

        offset += batch_size

print(f'\\nArticles checked: {total_checked:,}', file=sys.stderr)
print(f'Wire detected: {total_wire:,}', file=sys.stderr)
if total_checked > 0:
    print(f'Percentage: {100.0 * total_wire / total_checked:.2f}%', file=sys.stderr)
"""

    # Get processor pod
    get_pod = subprocess.run(
        ["kubectl", "get", "pods", "-n", "production", "-l", "app=mizzou-processor",
         "-o", "jsonpath='{.items[0].metadata.name}'"],
        capture_output=True,
        text=True
    )
    pod_name = get_pod.stdout.strip().strip("'")

    if not pod_name:
        print("ERROR: Could not find processor pod")
        return 1

    print(f"Using pod: {pod_name}")
    print()

    # Run script in pod
    result = subprocess.run(
        ["kubectl", "exec", "-n", "production", pod_name, "--",
         "python", "-c", script],
        capture_output=True,
        text=True
    )

    # Write stdout (CSV data) to file
    with open(output_csv, 'w') as f:
        f.write(result.stdout)

    # Print stderr (progress/summary)
    print(result.stderr)

    if result.returncode == 0:
        print()
        print("=" * 80)
        print("BACKFILL DRY-RUN COMPLETE")
        print("=" * 80)
        print(f"Output: {output_csv}")

        # Count lines in output
        with open(output_csv) as f:
            line_count = sum(1 for line in f) - 1  # Subtract header
        print(f"Wire articles found: {line_count:,}")
    else:
        print(f"ERROR: Script failed with return code {result.returncode}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
