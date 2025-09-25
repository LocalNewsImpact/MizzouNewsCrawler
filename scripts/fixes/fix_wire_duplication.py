#!/usr/bin/env python3
"""
Fix existing articles where wire services appear in both author and wire
fields.

This script:
1. Finds articles where wire services appear in the author field
2. Removes wire service names from the author field
3. Keeps the wire field populated with normalized names
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


def fix_wire_service_duplication(dry_run: bool = True) -> None:
    """
    Fix articles where wire services appear in both author and wire fields.
    
    Args:
        dry_run: If True, only show what would be changed without making
                 updates
    """
    db = DatabaseManager()
    
    # Define wire service variations for filtering
    wire_service_patterns = {
        'The Associated Press': [
            'associated press', 'the associated press', 'ap'
        ],
        'CNN NewsSource': ['cnn', 'cnn newsource', 'cnn newssource'],
        'Hearst': ['hearst', 'hearst stations inc'],
        'ABC News': ['abc', 'abc news'],
        'Reuters': ['reuters'],
        'Bloomberg': ['bloomberg'],
        'NPR': ['npr'],
        'PBS': ['pbs']
    }
    
    try:
        with db.engine.begin() as conn:
            # Find articles with wire content that have authors
            result = conn.execute(text(
                "SELECT id, author, wire FROM articles "
                "WHERE wire IS NOT NULL AND author IS NOT NULL "
                "AND author != '[]'"
            ))
            
            articles_with_issues = result.fetchall()
            
            logger.info(
                f"Found {len(articles_with_issues)} articles with both "
                "wire and author fields populated"
            )
            
            fixes_made = 0
            
            for article_id, author_field, wire_field in articles_with_issues:
                try:
                    # Parse the author field (it's stored as JSON array)
                    if (author_field.startswith('[') and
                            author_field.endswith(']')):
                        authors = json.loads(author_field)
                    else:
                        # Handle non-JSON format
                        authors = [author_field] if author_field else []
                    
                    # Find wire service patterns in the wire field
                    wire_patterns_to_remove = set()
                    if wire_field:
                        for canonical_name, patterns in (
                                wire_service_patterns.items()):
                            if (wire_field.lower().strip() in
                                    [p.lower() for p in patterns] or
                                    wire_field == canonical_name):
                                wire_patterns_to_remove.update(
                                    [p.lower() for p in patterns]
                                )
                                wire_patterns_to_remove.add(
                                    canonical_name.lower()
                                )
                    
                    # Filter out wire service names from authors
                    original_authors = authors.copy()
                    filtered_authors = []
                    
                    for author in authors:
                        author_normalized = author.lower().strip()
                        if author_normalized not in wire_patterns_to_remove:
                            filtered_authors.append(author)
                    
                    # Check if any changes were made
                    if len(filtered_authors) != len(original_authors):
                        logger.info(f"Article {article_id[:8]}...")
                        logger.info(f"  Wire: {wire_field}")
                        logger.info(f"  Original authors: {original_authors}")
                        logger.info(f"  Filtered authors: {filtered_authors}")
                        
                        if not dry_run:
                            # Update the author field with filtered authors
                            new_author_json = json.dumps(filtered_authors)
                            conn.execute(text(
                                "UPDATE articles SET author = :new_author "
                                "WHERE id = :article_id"
                            ), {"new_author": new_author_json,
                                "article_id": article_id})
                        
                        fixes_made += 1
                
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Could not parse author field for article "
                        f"{article_id}: {e}"
                    )
                    continue
                except Exception as e:
                    logger.error(f"Error processing article {article_id}: {e}")
                    continue
            
            if dry_run:
                logger.info(
                    f"\nDRY RUN SUMMARY: {fixes_made} articles would have "
                    "wire services removed from author field"
                )
                logger.info("Run with --execute to apply changes")
            else:
                logger.info(f"\nFix complete: {fixes_made} articles updated")
                
                # Show some examples of the results
                result = conn.execute(text(
                    "SELECT id, author, wire FROM articles "
                    "WHERE wire IS NOT NULL "
                    "ORDER BY wire "
                    "LIMIT 5"
                ))
                
                logger.info("\nSample of updated articles:")
                for article_id, author_field, wire_field in result.fetchall():
                    logger.info(
                        f"  {article_id[:8]}... | Authors: {author_field} | "
                        f"Wire: {wire_field}"
                    )
                    
    except Exception as e:
        logger.error(f"Error during fix: {e}")
        raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fix wire service duplication in articles"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the fixes (default is dry run)"
    )
    
    args = parser.parse_args()
    
    # Run fixes
    fix_wire_service_duplication(dry_run=not args.execute)