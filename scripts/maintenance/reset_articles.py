"""
Script to remove the last 15 articles from the database and reset their candidate_links status.
This allows those articles to be re-extracted with the fixed byline cleaning logic.
"""

import logging
from src.models.database import DatabaseManager
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_last_articles(count=15):
    """
    Remove the last N articles and reset their candidate_links status to 'article'.
    
    Args:
        count (int): Number of articles to remove (default: 15)
    """
    db = DatabaseManager()
    session = db.session
    
    try:
        # First, get the last N articles with their candidate_link_ids
        logger.info(f"Finding last {count} articles to remove...")
        
        result = session.execute(text("""
            SELECT id, candidate_link_id, url, title, author, created_at 
            FROM articles 
            ORDER BY created_at DESC 
            LIMIT :count
        """), {"count": count})
        
        articles_to_remove = []
        candidate_link_ids = []
        
        for row in result:
            articles_to_remove.append({
                'id': row.id,
                'candidate_link_id': row.candidate_link_id,
                'url': row.url,
                'title': row.title[:50] + '...' if row.title and len(row.title) > 50 else row.title,
                'author': row.author,
                'created_at': row.created_at
            })
            if row.candidate_link_id:
                candidate_link_ids.append(row.candidate_link_id)
        
        if not articles_to_remove:
            logger.info("No articles found to remove.")
            return
        
        logger.info(f"Found {len(articles_to_remove)} articles to remove:")
        for i, article in enumerate(articles_to_remove, 1):
            logger.info(f"  {i}. {article['title']} (Author: {article['author']})")
            logger.info(f"     URL: {article['url']}")
            logger.info(f"     Created: {article['created_at']}")
            print()
        
        # Confirm before proceeding
        confirm = input(f"\nAre you sure you want to remove these {len(articles_to_remove)} articles? (y/N): ")
        if confirm.lower() != 'y':
            logger.info("Operation cancelled.")
            return
        
        # Step 1: Delete the articles
        article_ids = [article['id'] for article in articles_to_remove]
        logger.info(f"Deleting {len(article_ids)} articles...")
        
        # Create placeholders for the IN clause
        placeholders = ','.join([':id' + str(i) for i in range(len(article_ids))])
        delete_params = {f'id{i}': article_id for i, article_id in enumerate(article_ids)}
        
        delete_result = session.execute(text(f"""
            DELETE FROM articles WHERE id IN ({placeholders})
        """), delete_params)
        
        logger.info(f"Deleted {delete_result.rowcount} articles.")
        
        # Step 2: Reset candidate_links status to 'article'
        if candidate_link_ids:
            logger.info(f"Resetting {len(candidate_link_ids)} candidate_links status to 'article'...")
            
            # Create placeholders for the IN clause
            cl_placeholders = ','.join([':cl_id' + str(i) for i in range(len(candidate_link_ids))])
            cl_params = {f'cl_id{i}': cl_id for i, cl_id in enumerate(candidate_link_ids)}
            
            update_result = session.execute(text(f"""
                UPDATE candidate_links 
                SET status = 'article' 
                WHERE id IN ({cl_placeholders})
            """), cl_params)
            
            logger.info(f"Updated candidate_links status.")
        
        # Commit the transaction
        session.commit()
        logger.info("✅ Operation completed successfully!")
        logger.info(f"Removed {len(article_ids)} articles and reset {len(candidate_link_ids)} candidate_links.")
        logger.info("These articles can now be re-extracted with the fixed byline cleaning.")
        
    except Exception as e:
        logger.error(f"Error during reset operation: {e}")
        session.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    reset_last_articles(15)