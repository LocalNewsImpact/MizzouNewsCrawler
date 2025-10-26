#!/usr/bin/env python3
"""
Script to re-clean article author names using updated byline cleaning rules.

This script addresses the byline truncation bug where organization names were
incorrectly removing parts of author names (e.g., "Jason Hancock" -> "Jason").

The script:
1. Backs up the current articles table
2. Re-processes original bylines using the improved BylineCleaner
3. Updates author names in the articles table
4. Provides rollback capabilities
5. Logs all changes for auditing

Usage:
    python scripts/reclean_article_authors.py [options]

Options:
    --dry-run: Show what would be changed without making actual updates
    --limit N: Only process N articles (for testing)
    --source-filter NAME: Only process articles from specific source
    --rollback BACKUP_ID: Rollback to a specific backup
    --list-backups: List available backups
"""

import argparse
import json
import logging
import sqlite3
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.byline_cleaner import BylineCleaner  # noqa: E402


class ArticleAuthorRecleaner:
    """Re-clean article author names using improved byline cleaning rules."""

    def __init__(self, db_path: str = "data/mizzou.db"):
        """Initialize the recleaner with database connection."""
        self.db_path = db_path
        self.backup_dir = Path("data/backups")
        self.backup_dir.mkdir(exist_ok=True)

        # Initialize the improved byline cleaner
        self.cleaner = BylineCleaner(enable_telemetry=False)

        # Setup logging
        self.setup_logging()

        # Stats tracking
        self.stats = {
            "total_processed": 0,
            "changed": 0,
            "unchanged": 0,
            "errors": 0,
            "improvements": 0,  # Cases where truncated names were fixed
            "no_change_needed": 0,
        }

    def setup_logging(self):
        """Setup logging for the recleaning process."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"data/reclean_authors_{timestamp}.log"

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
        )

        self.logger = logging.getLogger(__name__)
        self.logger.info("Starting article author re-cleaning process")
        self.logger.info(f"Log file: {log_file}")

    def create_backup(self) -> str:
        """Create a backup of the articles table."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = f"articles_backup_{timestamp}"
        backup_file = self.backup_dir / f"{backup_id}.sql"

        self.logger.info(f"Creating backup: {backup_file}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                # Create backup table
                conn.execute(f"""
                    CREATE TABLE {backup_id} AS
                    SELECT * FROM articles
                """)

                # Export to SQL file for extra safety
                with open(backup_file, "w") as f:
                    for line in conn.iterdump():
                        if backup_id in line:
                            f.write(line + "\n")

                self.logger.info(f"Backup created successfully: {backup_id}")
                return backup_id

        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}")
            raise

    def list_backups(self):
        """List available backups."""
        self.logger.info("Available backups:")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'articles_backup_%'
                ORDER BY name DESC
            """)

            backups = cursor.fetchall()

            if not backups:
                self.logger.info("No backups found.")
                return

            for backup in backups:
                backup_name = backup[0]
                # Get row count
                count_query = f"SELECT COUNT(*) FROM {backup_name}"
                count_cursor = conn.execute(count_query)
                count = count_cursor.fetchone()[0]

                # Extract timestamp from backup name
                timestamp_str = backup_name.replace("articles_backup_", "")
                try:
                    dt = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    formatted_time = timestamp_str

                msg = f"  {backup_name}: {count} articles ({formatted_time})"
                self.logger.info(msg)

    def rollback_to_backup(self, backup_id: str):
        """Rollback the articles table to a specific backup."""
        self.logger.info(f"Rolling back to backup: {backup_id}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                # Verify backup exists
                cursor = conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name = ?
                """,
                    (backup_id,),
                )

                if not cursor.fetchone():
                    raise ValueError(f"Backup '{backup_id}' not found")

                # Create a backup of current state before rollback
                current_backup = self.create_backup()
                msg = f"Current state backed up as: {current_backup}"
                self.logger.info(msg)

                # Drop current articles table and replace with backup
                conn.execute("DROP TABLE articles")
                conn.execute(f"ALTER TABLE {backup_id} RENAME TO articles")

                self.logger.info(f"Successfully rolled back to {backup_id}")

        except Exception as e:
            self.logger.error(f"Failed to rollback: {e}")
            raise

    def get_articles_with_telemetry(
        self, limit: int | None = None, source_filter: str | None = None
    ) -> list[dict]:
        """Get articles that have telemetry data with original bylines."""
        query = """
            SELECT DISTINCT
                a.id as article_id,
                a.candidate_link_id,
                a.author as current_author,
                bct.raw_byline,
                bct.source_name,
                bct.source_canonical_name,
                cl.source_name as candidate_source_name
            FROM articles a
            JOIN byline_cleaning_telemetry bct ON a.id = bct.article_id
            LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE bct.raw_byline IS NOT NULL 
            AND bct.raw_byline != ''
            AND a.author IS NOT NULL
            AND a.author != ''
        """

        params = []

        if source_filter:
            query += " AND (bct.source_name LIKE ? OR cl.source_name LIKE ?)"
            params.extend([f"%{source_filter}%", f"%{source_filter}%"])

        query += " ORDER BY a.id"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def clean_single_byline(self, article_data: dict) -> tuple[str | None, dict]:
        """Clean a single article's byline and return the result."""
        try:
            raw_byline = article_data["raw_byline"]
            source_name = (
                article_data["source_name"]
                or article_data["source_canonical_name"]
                or article_data["candidate_source_name"]
            )

            # Clean the byline using the improved cleaner
            cleaned_authors = self.cleaner.clean_byline(
                byline=raw_byline, source_name=source_name, return_json=False
            )

            # Convert to JSON format for storage
            if cleaned_authors:
                new_author_json = json.dumps(cleaned_authors)
            else:
                new_author_json = None

            # Analysis
            current_author = article_data["current_author"]

            # Parse current author (it should be JSON)
            try:
                if current_author.startswith("["):
                    current_authors = json.loads(current_author)
                else:
                    # Handle legacy format
                    current_authors = [current_author] if current_author else []
            except (json.JSONDecodeError, TypeError):
                current_authors = [current_author] if current_author else []

            analysis = {
                "raw_byline": raw_byline,
                "source_name": source_name,
                "current_authors": current_authors,
                "new_authors": cleaned_authors,
                "current_author_json": current_author,
                "new_author_json": new_author_json,
                "changed": current_authors != cleaned_authors,
                "improvement_detected": False,
                "change_details": [],
            }

            # Detect improvements (e.g., truncated names being fixed)
            if current_authors != cleaned_authors:
                # Check for name completions
                for old_name in current_authors:
                    for new_name in cleaned_authors:
                        if (
                            old_name
                            and new_name
                            and old_name in new_name
                            and len(new_name) > len(old_name)
                        ):
                            analysis["improvement_detected"] = True
                            analysis["change_details"].append(
                                f"Name completion: '{old_name}' -> '{new_name}'"
                            )

                # Check for organization truncation fixes
                if any("Associated" in str(author) for author in current_authors):
                    if any(
                        "Associated Press" in str(author) for author in cleaned_authors
                    ):
                        analysis["improvement_detected"] = True
                        analysis["change_details"].append(
                            "Fixed 'Associated Press' truncation"
                        )

                # General change description
                if not analysis["change_details"]:
                    analysis["change_details"].append(
                        f"Authors changed from {current_authors} to {cleaned_authors}"
                    )

            return new_author_json, analysis

        except Exception as e:
            self.logger.error(
                f"Error cleaning byline for article {article_data['article_id']}: {e}"
            )
            self.logger.error(f"Raw byline: {article_data.get('raw_byline', 'N/A')}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")

            return None, {
                "error": str(e),
                "raw_byline": article_data.get("raw_byline", "N/A"),
                "changed": False,
                "improvement_detected": False,
            }

    def update_article_author(
        self, article_id: str, new_author_json: str, dry_run: bool = False
    ) -> bool:
        """Update the author field for a specific article."""
        if dry_run:
            return True

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE articles 
                    SET author = ?, processed_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """,
                    (new_author_json, article_id),
                )

                return conn.total_changes > 0

        except Exception as e:
            self.logger.error(f"Failed to update article {article_id}: {e}")
            return False

    def process_articles(
        self,
        limit: int | None = None,
        source_filter: str | None = None,
        dry_run: bool = False,
    ):
        """Process all articles and re-clean their author names."""

        if not dry_run:
            backup_id = self.create_backup()
            self.logger.info(f"Backup created: {backup_id}")
        else:
            self.logger.info("DRY RUN MODE - No changes will be made")

        # Get articles to process
        articles = self.get_articles_with_telemetry(limit, source_filter)
        self.logger.info(f"Found {len(articles)} articles to process")

        if not articles:
            self.logger.info("No articles found to process")
            return

        # Process each article
        changes_log = []

        for i, article_data in enumerate(articles, 1):
            article_id = article_data["article_id"]

            if i % 10 == 0:
                self.logger.info(
                    f"Processing article {i}/{len(articles)}: {article_id}"
                )

            # Clean the byline
            new_author_json, analysis = self.clean_single_byline(article_data)

            # Update stats
            self.stats["total_processed"] += 1

            if "error" in analysis:
                self.stats["errors"] += 1
                continue

            if analysis["changed"]:
                if new_author_json:
                    # Update the database
                    success = self.update_article_author(
                        article_id, new_author_json, dry_run
                    )

                    if success:
                        self.stats["changed"] += 1
                        if analysis["improvement_detected"]:
                            self.stats["improvements"] += 1

                        # Log the change
                        change_record = {
                            "article_id": article_id,
                            "raw_byline": analysis["raw_byline"],
                            "old_authors": analysis["current_authors"],
                            "new_authors": analysis["new_authors"],
                            "improvement": analysis["improvement_detected"],
                            "details": analysis["change_details"],
                        }
                        changes_log.append(change_record)

                        if analysis["improvement_detected"]:
                            self.logger.info(
                                f"IMPROVEMENT - Article {article_id}: {' | '.join(analysis['change_details'])}"
                            )
                    else:
                        self.stats["errors"] += 1
                else:
                    # New cleaning resulted in no authors
                    self.logger.warning(
                        f"Article {article_id}: New cleaning removed all authors"
                    )
                    self.stats["changed"] += 1
            else:
                self.stats["unchanged"] += 1
                if not analysis.get("error"):
                    self.stats["no_change_needed"] += 1

        # Save changes log
        if changes_log:
            changes_file = f"data/author_cleaning_changes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(changes_file, "w") as f:
                json.dump(changes_log, f, indent=2, default=str)

            self.logger.info(f"Changes log saved to: {changes_file}")

        # Report final stats
        self.report_stats()

    def report_stats(self):
        """Report final processing statistics."""
        self.logger.info("=" * 60)
        self.logger.info("FINAL STATISTICS")
        self.logger.info("=" * 60)
        self.logger.info(f"Total articles processed: {self.stats['total_processed']}")
        self.logger.info(f"Articles changed: {self.stats['changed']}")
        self.logger.info(f"Articles unchanged: {self.stats['unchanged']}")
        self.logger.info(f"Errors encountered: {self.stats['errors']}")
        self.logger.info(f"Improvements detected: {self.stats['improvements']}")
        self.logger.info(f"No change needed: {self.stats['no_change_needed']}")

        if self.stats["total_processed"] > 0:
            change_rate = (self.stats["changed"] / self.stats["total_processed"]) * 100
            improvement_rate = (
                self.stats["improvements"] / self.stats["total_processed"]
            ) * 100
            self.logger.info(f"Change rate: {change_rate:.1f}%")
            self.logger.info(f"Improvement rate: {improvement_rate:.1f}%")

        self.logger.info("=" * 60)


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Re-clean article author names using improved byline cleaning rules"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making actual updates",
    )
    parser.add_argument(
        "--limit", type=int, help="Only process N articles (for testing)"
    )
    parser.add_argument(
        "--source-filter",
        type=str,
        help="Only process articles from specific source (partial match)",
    )
    parser.add_argument(
        "--rollback", type=str, help="Rollback to a specific backup (backup table name)"
    )
    parser.add_argument(
        "--list-backups", action="store_true", help="List available backups and exit"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/mizzou.db",
        help="Path to the database file",
    )

    args = parser.parse_args()

    # Initialize the recleaner
    recleaner = ArticleAuthorRecleaner(db_path=args.db_path)

    try:
        if args.list_backups:
            recleaner.list_backups()
            return

        if args.rollback:
            recleaner.rollback_to_backup(args.rollback)
            return

        # Process articles
        recleaner.process_articles(
            limit=args.limit, source_filter=args.source_filter, dry_run=args.dry_run
        )

    except KeyboardInterrupt:
        recleaner.logger.info("Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        recleaner.logger.error(f"Fatal error: {e}")
        recleaner.logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
