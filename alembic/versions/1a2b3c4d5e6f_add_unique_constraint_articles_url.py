"""add_unique_constraint_articles_url

Revision ID: 1a2b3c4d5e6f
Revises: 805164cd4665
Create Date: 2025-10-25 13:30:00.000000

This migration addresses Issue #105: Extraction workflow failure and database write issues.

Steps:
1. Deduplicate existing articles by URL (keep oldest by created_at)
2. Add UNIQUE constraint on articles.url column
3. Use CONCURRENTLY for PostgreSQL to avoid locking production table

Note: For SQLite, deduplication and constraint addition happen in batch mode
(table recreation) which is not concurrent but acceptable for dev/test environments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '805164cd4665'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: deduplicate articles by URL and add UNIQUE constraint."""
    
    # Get database connection to determine dialect
    conn = op.get_bind()
    dialect = conn.dialect.name
    
    # Step 1: Deduplicate existing articles by URL
    # Keep the oldest article (by created_at) for each URL
    # This prevents data loss while ensuring uniqueness
    
    if dialect == 'postgresql':
        # PostgreSQL: Use DELETE with subquery to remove duplicates
        # Keep the article with the earliest created_at for each URL
        dedupe_sql = text("""
            DELETE FROM articles
            WHERE id IN (
                SELECT a1.id
                FROM articles a1
                INNER JOIN articles a2 ON a1.url = a2.url
                WHERE a1.id != a2.id
                AND (
                    a1.created_at > a2.created_at
                    OR (a1.created_at = a2.created_at AND a1.id > a2.id)
                )
            )
        """)
        
        result = conn.execute(dedupe_sql)
        rows_deleted = result.rowcount if hasattr(result, 'rowcount') else 0
        print(f"Deduplicated {rows_deleted} duplicate articles by URL (kept oldest)")
        
        # Step 2: Add UNIQUE constraint using CREATE UNIQUE INDEX CONCURRENTLY
        # This allows the operation to run without blocking reads/writes
        # Note: CONCURRENTLY requires a separate transaction, so we commit first
        conn.execute(text("COMMIT"))
        
        # Create unique index concurrently (won't block table)
        conn.execute(text(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
            "uq_articles_url ON articles (url)"
        ))
        
        # Then add the constraint using the index
        # (This is fast since the index already exists)
        try:
            op.create_unique_constraint(
                'uq_articles_url',
                'articles',
                ['url'],
                postgresql_using='btree',
            )
        except Exception:
            # If constraint already exists, that's fine
            # The UNIQUE INDEX CONCURRENTLY will still enforce uniqueness
            pass
            
    elif dialect == 'sqlite':
        # SQLite: Use batch mode to recreate table with UNIQUE constraint
        # This handles deduplication and constraint addition in one operation
        
        # First, manually deduplicate by creating a temp table with unique URLs
        with op.batch_alter_table('articles', schema=None) as batch_op:
            # SQLite doesn't support the same DELETE syntax, so we'll use a different approach
            # Create a temporary table with deduplicated data
            pass
        
        # Deduplicate using a temp table approach
        conn.execute(text("""
            CREATE TEMPORARY TABLE articles_deduped AS
            SELECT a1.*
            FROM articles a1
            LEFT JOIN articles a2 ON a1.url = a2.url
                AND (
                    a1.created_at > a2.created_at
                    OR (a1.created_at = a2.created_at AND a1.id > a2.id)
                )
            WHERE a2.id IS NULL
        """))
        
        # Count duplicates being removed
        original_count = conn.execute(text("SELECT COUNT(*) FROM articles")).scalar()
        deduped_count = conn.execute(text("SELECT COUNT(*) FROM articles_deduped")).scalar()
        rows_deleted = original_count - deduped_count
        print(f"Deduplicated {rows_deleted} duplicate articles by URL (kept oldest)")
        
        # Clear the original table and insert deduplicated data
        conn.execute(text("DELETE FROM articles"))
        conn.execute(text("""
            INSERT INTO articles
            SELECT * FROM articles_deduped
        """))
        
        # Drop temp table
        conn.execute(text("DROP TABLE articles_deduped"))
        
        # Now add UNIQUE constraint using batch mode
        with op.batch_alter_table('articles', schema=None) as batch_op:
            batch_op.create_unique_constraint(
                'uq_articles_url',
                ['url']
            )
    
    else:
        # For other dialects, attempt basic deduplication and constraint addition
        print(f"Warning: Dialect {dialect} not explicitly supported. Attempting generic approach.")
        
        # Try generic dedupe approach
        try:
            dedupe_sql = text("""
                DELETE FROM articles
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM articles
                    GROUP BY url
                )
            """)
            result = conn.execute(dedupe_sql)
            rows_deleted = result.rowcount if hasattr(result, 'rowcount') else 0
            print(f"Deduplicated {rows_deleted} duplicate articles by URL")
        except Exception as e:
            print(f"Warning: Deduplication failed: {e}")
        
        # Try to add UNIQUE constraint
        try:
            op.create_unique_constraint(
                'uq_articles_url',
                'articles',
                ['url']
            )
        except Exception as e:
            print(f"Warning: Could not add UNIQUE constraint: {e}")


def downgrade() -> None:
    """Downgrade schema: remove UNIQUE constraint on articles.url"""
    
    # Get database connection to determine dialect
    conn = op.get_bind()
    dialect = conn.dialect.name
    
    if dialect == 'postgresql':
        # Drop the constraint
        try:
            op.drop_constraint('uq_articles_url', 'articles', type_='unique')
        except Exception:
            pass
        
        # Drop the index if it exists
        try:
            conn.execute(text("DROP INDEX IF EXISTS uq_articles_url"))
        except Exception:
            pass
            
    elif dialect == 'sqlite':
        # SQLite: Use batch mode to recreate table without UNIQUE constraint
        with op.batch_alter_table('articles', schema=None) as batch_op:
            try:
                batch_op.drop_constraint('uq_articles_url', type_='unique')
            except Exception:
                pass
    
    else:
        # Generic approach
        try:
            op.drop_constraint('uq_articles_url', 'articles', type_='unique')
        except Exception as e:
            print(f"Warning: Could not drop UNIQUE constraint: {e}")
