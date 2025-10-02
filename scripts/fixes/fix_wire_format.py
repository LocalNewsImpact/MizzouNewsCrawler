#!/usr/bin/env python3
"""
Fix articles where wire field is stored as JSON array instead of string.
Also handle remaining wire service duplications.
"""

import json
import logging
import os
import sys

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text

from src.models.database import DatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fix_wire_field_format(dry_run: bool = True) -> None:
    """
    Fix wire fields that are stored as JSON arrays instead of strings.
    Also handle any remaining wire service duplications.
    
    Args:
        dry_run: If True, only show what would be changed without making
                 updates
    """
    db = DatabaseManager()

    wire_service_patterns = {
        'The Associated Press': [
            'associated press', 'the associated press', 'ap'
        ],
        'CNN NewsSource': ['cnn', 'cnn newsource', 'cnn newssource'],
        'Hearst': ['hearst', 'hearst stations inc'],
        'ABC News': ['abc', 'abc news'],
    }

    try:
        with db.engine.begin() as conn:
            # Find articles with wire fields stored as JSON arrays
            result = conn.execute(text(
                'SELECT id, author, wire, title FROM articles '
                'WHERE wire LIKE "[%]"'
            ))

            anomalous_entries = result.fetchall()

            logger.info(
                f"Found {len(anomalous_entries)} articles with wire field "
                "stored as JSON array"
            )

            fixes_made = 0

            for article_id, author_field, wire_field, title in (
                    anomalous_entries):
                try:
                    # Parse the wire field (it's stored as JSON array)
                    if wire_field.startswith('[') and wire_field.endswith(']'):
                        wire_array = json.loads(wire_field)
                        # Extract the first wire service name
                        wire_string = wire_array[0] if wire_array else None
                    else:
                        wire_string = wire_field

                    # Parse author field
                    if (author_field and author_field.startswith('[') and
                            author_field.endswith(']')):
                        authors = json.loads(author_field)
                    else:
                        authors = [author_field] if author_field else []

                    # Find wire service patterns to remove from authors
                    wire_patterns_to_remove = set()
                    if wire_string:
                        for canonical_name, patterns in (
                                wire_service_patterns.items()):
                            if (wire_string.lower().strip() in
                                    [p.lower() for p in patterns] or
                                    wire_string == canonical_name):
                                wire_patterns_to_remove.update(
                                    [p.lower() for p in patterns]
                                )
                                wire_patterns_to_remove.add(
                                    canonical_name.lower()
                                )

                    # Filter authors
                    original_authors = authors.copy()
                    filtered_authors = []

                    for author in authors:
                        author_normalized = author.lower().strip()
                        if author_normalized not in wire_patterns_to_remove:
                            filtered_authors.append(author)

                    logger.info(f"Article {article_id[:8]}...")
                    logger.info(f"  Title: {title[:50]}...")
                    logger.info(f"  Wire (array): {wire_field}")
                    logger.info(f"  Wire (string): {wire_string}")
                    logger.info(f"  Original authors: {original_authors}")
                    logger.info(f"  Filtered authors: {filtered_authors}")

                    if not dry_run:
                        # Update both wire and author fields
                        new_author_json = json.dumps(filtered_authors)
                        conn.execute(text(
                            "UPDATE articles SET wire = :new_wire, "
                            "author = :new_author WHERE id = :article_id"
                        ), {
                            "new_wire": wire_string,
                            "new_author": new_author_json,
                            "article_id": article_id
                        })

                    fixes_made += 1

                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Could not parse fields for article {article_id}: {e}"
                    )
                    continue
                except Exception as e:
                    logger.error(f"Error processing article {article_id}: {e}")
                    continue

            if dry_run:
                logger.info(
                    f"\nDRY RUN SUMMARY: {fixes_made} articles would be fixed"
                )
                logger.info("Run with --execute to apply changes")
            else:
                logger.info(f"\nFix complete: {fixes_made} articles updated")

                # Show final wire service distribution
                result = conn.execute(text(
                    'SELECT wire, COUNT(*) as count FROM articles '
                    'WHERE wire IS NOT NULL '
                    'GROUP BY wire '
                    'ORDER BY count DESC'
                ))

                logger.info("\nFinal wire service distribution:")
                for wire, count in result.fetchall():
                    logger.info(f"  {wire}: {count} articles")

    except Exception as e:
        logger.error(f"Error during fix: {e}")
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix wire field format issues"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the fixes (default is dry run)"
    )

    args = parser.parse_args()

    # Run fixes
    fix_wire_field_format(dry_run=not args.execute)
