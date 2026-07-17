#!/usr/bin/env python3
"""Import articles from WARC archives into Minnesota dataset.

This script processes WARC files and imports article content directly into the
database, bypassing the discovery phase. Features:
- Batch commits (configurable interval)
- Failure rate monitoring (stops if threshold exceeded)
- Progress tracking with resumption capability
- Error logging for debugging
- Dry-run mode for validation
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import hashlib

from warcio.archiveiterator import ArchiveIterator

from src.models.database import DatabaseManager
from src.models import CandidateLink, Article
from src.crawler import ContentExtractor
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class WARCImporter:
    """Import articles from WARC archives with progress tracking and failure monitoring."""
    
    def __init__(
        self,
        dataset_id: str,
        batch_size: int = 250,
        commit_interval: int = 10,
        failure_threshold: float = 5.0,
        progress_file: Path = Path("warc_import_progress.json"),
        error_file: Path = Path("warc_import_errors.jsonl")
    ):
        """Initialize WARC importer.
        
        Args:
            dataset_id: UUID of the Minnesota dataset
            batch_size: Number of articles in monitoring window for failure rate
            commit_interval: Number of articles to accumulate before commit
            failure_threshold: Maximum failure rate percentage (stops if exceeded)
            progress_file: Path to JSON file tracking import progress
            error_file: Path to JSONL file logging errors
        """
        self.dataset_id = dataset_id
        self.batch_size = batch_size
        self.commit_interval = commit_interval
        self.failure_threshold = failure_threshold
        self.progress_file = progress_file
        self.error_file = error_file
        
        self.total_imported = 0
        self.total_failures = 0
        self.batch_number = 0
        self.batch_failures = 0
        self.batch_articles = 0
        
        self.pending_commits: list[tuple[CandidateLink, Article]] = []
        self.extractor = ContentExtractor()
        self.db = DatabaseManager()
        
    def load_progress(self) -> dict:
        """Load progress from JSON file for resumption.
        
        Returns:
            Dictionary with progress state or empty dict if no progress file
        """
        if self.progress_file.exists():
            with open(self.progress_file) as f:
                return json.load(f)
        return {}
    
    def save_progress(self, warc_file: str, record_id: str):
        """Save progress after each commit batch.
        
        Args:
            warc_file: Current WARC filename being processed
            record_id: Last successfully processed WARC-Record-ID
        """
        progress = {
            "current_warc_file": warc_file,
            "last_warc_record_id": record_id,
            "total_articles_imported": self.total_imported,
            "total_failures": self.total_failures,
            "batch_number": self.batch_number,
            "timestamp": datetime.utcnow().isoformat()
        }
        with open(self.progress_file, 'w') as f:
            json.dump(progress, f, indent=2)
        logger.info(f"Progress saved: {self.total_imported} articles, {self.total_failures} failures")
    
    def log_error(
        self,
        warc_file: str,
        record_id: str,
        url: str,
        error_type: str,
        error_msg: str
    ):
        """Log parsing error to JSONL file.
        
        Args:
            warc_file: WARC filename where error occurred
            record_id: WARC-Record-ID of the failed record
            url: URL of the article that failed
            error_type: Type of error (ParseError, ExtractionError, etc.)
            error_msg: Detailed error message
        """
        error_entry = {
            "warc_filename": warc_file,
            "warc_record_id": record_id,
            "url": url,
            "error_type": error_type,
            "error_message": str(error_msg),
            "timestamp": datetime.utcnow().isoformat()
        }
        with open(self.error_file, 'a') as f:
            json.dump(error_entry, f)
            f.write('\n')
    
    def check_failure_rate(self) -> bool:
        """Check if batch failure rate exceeds threshold.
        
        Returns:
            True if failure rate exceeds threshold, False otherwise
        """
        if self.batch_articles == 0:
            return False
        failure_rate = (self.batch_failures / self.batch_articles) * 100
        if failure_rate > self.failure_threshold:
            logger.error(
                f"Failure rate {failure_rate:.2f}% exceeds threshold {self.failure_threshold}% "
                f"({self.batch_failures}/{self.batch_articles} in batch {self.batch_number})"
            )
            return True
        return False
    
    def commit_batch(self, session, warc_file: str, last_record_id: str):
        """Commit accumulated articles to database.
        
        Args:
            session: Database session
            warc_file: Current WARC filename
            last_record_id: Last WARC-Record-ID in this batch
        """
        if not self.pending_commits:
            return
        
        try:
            for candidate_link, article in self.pending_commits:
                session.add(candidate_link)
                session.flush()  # Get candidate_link.id
                article.candidate_link_id = candidate_link.id
                session.add(article)
            
            session.commit()
            self.total_imported += len(self.pending_commits)
            logger.info(f"Committed {len(self.pending_commits)} articles (total: {self.total_imported})")
            
            # Save progress after successful commit
            self.save_progress(warc_file, last_record_id)
            self.pending_commits = []
            
        except Exception as e:
            logger.error(f"Commit failed: {e}")
            session.rollback()
            # Log all articles in failed batch
            for candidate_link, article in self.pending_commits:
                self.log_error(
                    warc_file,
                    "batch-commit",
                    candidate_link.url,
                    "CommitError",
                    str(e)
                )
                self.total_failures += 1
            self.pending_commits = []
    
    def extract_warc_date(self, record) -> Optional[datetime]:
        """Extract and parse WARC-Date header.
        
        Args:
            record: WARC record
            
        Returns:
            datetime object or None if parsing fails
        """
        try:
            warc_date_str = record.rec_headers.get_header('WARC-Date')
            if warc_date_str:
                # WARC-Date format: 2024-01-15T14:32:10Z
                return datetime.fromisoformat(warc_date_str.replace('Z', '+00:00'))
        except Exception as e:
            logger.warning(f"Failed to parse WARC-Date: {e}")
        return None
    
    def process_warc(
        self,
        warc_path: Path,
        resume_from: Optional[str] = None,
        dry_run: bool = False
    ) -> bool:
        """Process WARC file and import articles.
        
        Args:
            warc_path: Path to WARC file
            resume_from: WARC-Record-ID to resume from (skip records before this)
            dry_run: If True, parse and validate but don't write to database
            
        Returns:
            True if processing succeeded, False if failure threshold exceeded
        """
        logger.info(f"Processing WARC file: {warc_path}")
        warc_filename = warc_path.name
        skipping = resume_from is not None
        last_record_id = None
        
        with open(warc_path, 'rb') as stream:
            for record in ArchiveIterator(stream):
                # Only process response records
                if record.rec_type != 'response':
                    continue
                
                # Extract WARC-Record-ID
                record_id = record.rec_headers.get_header('WARC-Record-ID')
                if not record_id:
                    logger.warning("Record missing WARC-Record-ID, skipping")
                    continue
                
                last_record_id = record_id
                
                # Skip until we reach resume point
                if skipping:
                    if record_id == resume_from:
                        skipping = False
                        logger.info(f"Resumed from WARC-Record-ID: {record_id}")
                    continue
                
                # Extract URL
                url = record.rec_headers.get_header('WARC-Target-URI')
                if not url:
                    logger.warning(f"Record {record_id} missing URL, skipping")
                    continue
                
                # Extract timestamp
                warc_date = self.extract_warc_date(record)
                if not warc_date:
                    warc_date = datetime.utcnow()  # Fallback to current time
                
                # Read HTML content
                try:
                    html_content = record.content_stream().read()
                    if isinstance(html_content, bytes):
                        html_content = html_content.decode('utf-8', errors='ignore')
                except Exception as e:
                    self.log_error(warc_filename, record_id, url, "ReadError", str(e))
                    self.total_failures += 1
                    self.batch_failures += 1
                    self.batch_articles += 1
                    continue
                
                # Extract article content
                try:
                    extraction_result = self.extractor.extract(html_content, url)
                    if not extraction_result or not extraction_result.get('title'):
                        raise ValueError("Extraction returned no title")
                    
                    # Create database objects
                    candidate_link = CandidateLink(
                        url=url,
                        source=url,  # Will be updated with proper source mapping
                        status='article',
                        discovered_by='warc-archive',
                        discovered_at=warc_date,
                        dataset_id=self.dataset_id
                    )
                    
                    # Generate text hash for deduplication
                    text_content = extraction_result.get('text', '')
                    text_hash = hashlib.sha256(text_content.encode('utf-8')).hexdigest()
                    
                    article = Article(
                        url=url,
                        title=extraction_result.get('title', ''),
                        author=extraction_result.get('author'),
                        published_date=extraction_result.get('published_date'),
                        text=text_content,
                        content=extraction_result.get('content'),
                        status='extracted',
                        wire_check_status='pending',
                        extracted_at=warc_date,
                        text_hash=text_hash
                    )
                    
                    if dry_run:
                        logger.info(f"[DRY RUN] Would import: {url} (title: {article.title[:50]}...)")
                    else:
                        self.pending_commits.append((candidate_link, article))
                        
                        # Commit batch if interval reached
                        if len(self.pending_commits) >= self.commit_interval:
                            with self.db.get_session() as session:
                                self.commit_batch(session, warc_filename, record_id)
                    
                    self.batch_articles += 1
                    
                except Exception as e:
                    self.log_error(warc_filename, record_id, url, "ExtractionError", str(e))
                    self.total_failures += 1
                    self.batch_failures += 1
                    self.batch_articles += 1
                
                # Check failure rate every batch_size articles
                if self.batch_articles >= self.batch_size:
                    if self.check_failure_rate():
                        logger.error("Failure threshold exceeded, stopping import")
                        return False
                    
                    # Reset batch counters
                    self.batch_number += 1
                    self.batch_articles = 0
                    self.batch_failures = 0
        
        # Commit any remaining articles
        if self.pending_commits and not dry_run:
            with self.db.get_session() as session:
                self.commit_batch(session, warc_filename, last_record_id or "final")
        
        return True
    
    def import_directory(
        self,
        warc_dir: Path,
        resume: bool = False,
        dry_run: bool = False
    ) -> bool:
        """Import all WARC files in directory.
        
        Args:
            warc_dir: Directory containing WARC files
            resume: If True, resume from last checkpoint
            dry_run: If True, validate without database writes
            
        Returns:
            True if all files processed successfully, False if stopped due to failures
        """
        # Load progress if resuming
        resume_from_id = None
        resume_from_file = None
        if resume:
            progress = self.load_progress()
            if progress:
                resume_from_file = progress.get("current_warc_file")
                resume_from_id = progress.get("last_warc_record_id")
                self.total_imported = progress.get("total_articles_imported", 0)
                self.total_failures = progress.get("total_failures", 0)
                self.batch_number = progress.get("batch_number", 0)
                logger.info(f"Resuming from {resume_from_file}, record {resume_from_id}")
        
        # Get all WARC files
        warc_files = sorted(warc_dir.glob("*.warc*"))
        if not warc_files:
            logger.error(f"No WARC files found in {warc_dir}")
            return False
        
        logger.info(f"Found {len(warc_files)} WARC files")
        
        # Process each file
        skip_until_file = resume_from_file
        for warc_path in warc_files:
            # Skip files until we reach resume point
            if skip_until_file:
                if warc_path.name == skip_until_file:
                    skip_until_file = None  # Found it, start processing
                else:
                    logger.info(f"Skipping {warc_path.name} (before resume point)")
                    continue
            
            # Process this file
            resume_id = resume_from_id if warc_path.name == resume_from_file else None
            success = self.process_warc(warc_path, resume_from=resume_id, dry_run=dry_run)
            
            if not success:
                logger.error(f"Stopped due to failure threshold in {warc_path.name}")
                return False
            
            # Clear resume_from_id after first file
            resume_from_id = None
        
        logger.info(f"Import complete: {self.total_imported} articles imported, {self.total_failures} failures")
        return True


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Import articles from WARC archives into Minnesota dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate without importing
  python scripts/import_warc_minnesota.py --warc-dir /data/warc --dataset-id <uuid> --dry-run
  
  # Import with default settings
  python scripts/import_warc_minnesota.py --warc-dir /data/warc --dataset-id <uuid>
  
  # Resume from last checkpoint
  python scripts/import_warc_minnesota.py --warc-dir /data/warc --dataset-id <uuid> --resume
  
  # Custom batch size and threshold
  python scripts/import_warc_minnesota.py --warc-dir /data/warc --dataset-id <uuid> \\
    --batch-size 500 --commit-interval 20 --failure-threshold 10.0
        """
    )
    
    parser.add_argument(
        "--warc-dir",
        type=Path,
        required=True,
        help="Directory containing WARC files"
    )
    parser.add_argument(
        "--dataset-id",
        required=True,
        help="UUID of the Minnesota dataset"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Monitoring window for failure rate calculation (default: 250)"
    )
    parser.add_argument(
        "--commit-interval",
        type=int,
        default=10,
        help="Number of articles per database commit (default: 10)"
    )
    parser.add_argument(
        "--failure-threshold",
        type=float,
        default=5.0,
        help="Maximum failure rate percentage before stopping (default: 5.0)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint in progress file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate WARC files without database writes"
    )
    
    args = parser.parse_args()
    
    # Validate warc directory
    if not args.warc_dir.exists():
        logger.error(f"WARC directory does not exist: {args.warc_dir}")
        return 1
    
    # Create importer
    importer = WARCImporter(
        dataset_id=args.dataset_id,
        batch_size=args.batch_size,
        commit_interval=args.commit_interval,
        failure_threshold=args.failure_threshold
    )
    
    # Run import
    try:
        success = importer.import_directory(
            args.warc_dir,
            resume=args.resume,
            dry_run=args.dry_run
        )
        return 0 if success else 1
    except KeyboardInterrupt:
        logger.info("Import interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Import failed with exception: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
