#!/usr/bin/env python3
"""
Import manually collected articles into the production database.

Input format (TSV - tab-separated):
    URL\tTitle\tPublish_Date\tAuthor\tBody_Text

Example usage:
    # Dry run (validation only)
    python scripts/import_manual_articles.py --file manual_articles.tsv --dry-run

    # Import to production
    kubectl cp scripts/import_manual_articles.py production/<pod>:/app/
    kubectl cp manual_articles.tsv production/<pod>:/app/
    kubectl exec -n production deployment/mizzou-api -- python /app/import_manual_articles.py --file /app/manual_articles.tsv

    # After import, run classification:
    kubectl exec -n production deployment/mizzou-processor -- python -m src.cli.cli_modular analyze --batch-size 50
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from urllib.parse import urlparse

# For local testing
try:
    from src.models.database import DatabaseManager
    from sqlalchemy import text
except ImportError:
    print("Warning: Running outside of production environment")
    DatabaseManager = None


def parse_date(date_str: str) -> datetime | None:
    """Parse various date formats."""
    if not date_str:
        return None
    
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%dT%H:%M:%S",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    
    print(f"Warning: Could not parse date '{date_str}'")
    return None


def extract_hostname(url: str) -> str:
    """Extract clean hostname from URL."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def generate_id(url: str, prefix: str = "") -> str:
    """Generate deterministic ID from URL."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"{prefix}{url_hash}"


def compute_text_hash(text: str) -> str:
    """Compute hash of article text."""
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def parse_tsv_line(line: str) -> dict | None:
    """Parse a single TSV line into article data."""
    # Split by tab
    parts = line.strip().split('\t')
    
    if len(parts) < 5:
        return None
    
    url = parts[0].strip()
    title = parts[1].strip()
    date_str = parts[2].strip()
    author = parts[3].strip()
    # Body is everything after author (in case there are tabs in body)
    body = '\t'.join(parts[4:]).strip()
    
    if not url or not url.startswith('http'):
        return None
    
    return {
        'url': url,
        'title': title,
        'publish_date': parse_date(date_str),
        'author': author,
        'text': body,
        'source': extract_hostname(url),
    }


def import_articles(file_path: str, dry_run: bool = False, batch_size: int = 100):
    """Import articles from TSV file."""
    
    if not DatabaseManager:
        print("ERROR: Must run in production environment with database access")
        sys.exit(1)
    
    # Read and parse all records
    records = []
    errors = []
    
    with open(file_path, encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            
            record = parse_tsv_line(line)
            if record:
                records.append(record)
            else:
                errors.append(f"Line {line_num}: Could not parse")
    
    print(f"Parsed {len(records)} records from {file_path}")
    print(f"Parse errors: {len(errors)}")
    
    if errors[:10]:
        print("First 10 errors:")
        for err in errors[:10]:
            print(f"  {err}")
    
    if dry_run:
        print("\n=== DRY RUN - No changes will be made ===")
        print(f"Would import {len(records)} articles")
        
        # Show sample
        if records:
            print("\nSample record:")
            sample = records[0]
            print(f"  URL: {sample['url']}")
            print(f"  Title: {sample['title'][:80]}...")
            print(f"  Author: {sample['author']}")
            print(f"  Date: {sample['publish_date']}")
            print(f"  Source: {sample['source']}")
            print(f"  Text length: {len(sample['text'])} chars")
        
        # Check for duplicates
        urls = [r['url'] for r in records]
        unique_urls = set(urls)
        if len(urls) != len(unique_urls):
            print(f"\nWarning: {len(urls) - len(unique_urls)} duplicate URLs in input")
        
        return
    
    # Import to database
    db = DatabaseManager()
    now = datetime.utcnow()
    import_metadata = json.dumps({
        "import_source": "manual",
        "import_date": now.isoformat(),
        "import_version": "v1"
    })
    
    imported = 0
    skipped_existing = 0
    
    with db.get_session() as session:
        for record in records:
            url = record['url']
            
            # Check if URL already exists
            exists = session.execute(
                text("SELECT 1 FROM candidate_links WHERE url = :url"),
                {"url": url}
            ).fetchone()
            
            if exists:
                skipped_existing += 1
                continue
            
            # Generate IDs
            cl_id = generate_id(url, "manual_cl_")
            article_id = generate_id(url, "manual_art_")
            text_hash = compute_text_hash(record['text'])
            
            # Insert candidate_link
            session.execute(
                text("""
                    INSERT INTO candidate_links (
                        id, url, source, discovered_at, discovered_by, status, created_at
                    ) VALUES (
                        :id, :url, :source, :discovered_at, :discovered_by, :status, :created_at
                    )
                """),
                {
                    "id": cl_id,
                    "url": url,
                    "source": record['source'],
                    "discovered_at": now,
                    "discovered_by": "manual-import",
                    "status": "extracted",
                    "created_at": now,
                }
            )
            
            # Insert article
            session.execute(
                text("""
                    INSERT INTO articles (
                        id, candidate_link_id, url, title, author, publish_date,
                        text, text_hash, status, metadata, extraction_version,
                        extracted_at, created_at, wire_check_status
                    ) VALUES (
                        :id, :candidate_link_id, :url, :title, :author, :publish_date,
                        :text, :text_hash, :status, :metadata, :extraction_version,
                        :extracted_at, :created_at, :wire_check_status
                    )
                """),
                {
                    "id": article_id,
                    "candidate_link_id": cl_id,
                    "url": url,
                    "title": record['title'],
                    "author": record['author'],
                    "publish_date": record['publish_date'],
                    "text": record['text'],
                    "text_hash": text_hash,
                    "status": "cleaned",  # Ready for ML classification
                    "metadata": import_metadata,
                    "extraction_version": "manual-import-v1",
                    "extracted_at": now,
                    "created_at": now,
                    "wire_check_status": "local",  # Manual imports assumed local
                }
            )
            
            imported += 1
            
            if imported % batch_size == 0:
                session.commit()
                print(f"Imported {imported} articles...")
        
        session.commit()
    
    print(f"\n=== Import Complete ===")
    print(f"Imported: {imported}")
    print(f"Skipped (already exist): {skipped_existing}")
    print(f"Total processed: {imported + skipped_existing}")
    print(f"\nNext steps:")
    print(f"  1. Run ML classification:")
    print(f"     kubectl exec -n production deployment/mizzou-processor -- \\")
    print(f"       python -m src.cli.cli_modular analyze --batch-size 50")
    print(f"  2. Export to BigQuery (automatic via Datastream)")
    print(f"  3. Export to Sheets:")
    print(f"     curl -H 'Authorization: Bearer $(gcloud auth print-identity-token)' \\")
    print(f"       'https://us-central1-mizzou-news-crawler.cloudfunctions.net/daily-sheet-exporter?date=YYYY-MM-DD'")


def main():
    parser = argparse.ArgumentParser(description="Import manual articles to production DB")
    parser.add_argument("--file", required=True, help="Path to TSV file")
    parser.add_argument("--dry-run", action="store_true", help="Validate without importing")
    parser.add_argument("--batch-size", type=int, default=100, help="Commit batch size")
    
    args = parser.parse_args()
    import_articles(args.file, args.dry_run, args.batch_size)


if __name__ == "__main__":
    main()
