import sys
import re
import json
import logging
from sqlalchemy import text
from src.models.database import DatabaseManager

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def backfill_url_verification():
    """
    Backfills wire detection based on URL patterns for articles 
    that were already extracted but missed the initial verification filter.
    """
    logger.info("Starting retroactive URL verification backfill...")
    
    db = DatabaseManager()
    with db.get_session() as session:
        # 1. Load active patterns from wire_services
        logger.info("Loading active wire service patterns...")
        try:
            patterns_result = session.execute(text("""
                SELECT id, service_name, pattern, pattern_type 
                FROM wire_services 
                WHERE active = true 
                ORDER BY priority DESC
            """)).fetchall()
        except Exception as e:
            logger.error(f"Failed to load patterns: {e}")
            return

        compiled_patterns = []
        for p in patterns_result:
            try:
                # Compile regex (case-insensitive to match typical URL behavior)
                # Use raw string if pattern has escapes, but coming from DB 
                # we treat it as the pattern string.
                compiled_patterns.append({
                    're': re.compile(p.pattern, re.IGNORECASE),
                    'name': p.service_name,
                    'type': p.pattern_type,
                    'orig': p.pattern
                })
            except re.error as e:
                logger.error(f"Invalid regex in DB pattern '{p.pattern}': {e}")

        logger.info(f"Loaded {len(compiled_patterns)} verification patterns.")

        # 2. Fetch candidate articles
        # We target articles that are currently considered 'valid' content
        # statuses: extracted, cleaned, labeled, local
        # We explicitly verify them against the wire patterns.
        logger.info("Fetching candidate articles...")
        articles_query = text("""
            SELECT id, url, status 
            FROM articles 
            WHERE status IN ('extracted', 'cleaned', 'labeled', 'local')
        """)
        articles = session.execute(articles_query).fetchall()
        total_articles = len(articles)
        logger.info(f"Found {total_articles} articles to verify.")

        updated_count = 0
        processed_count = 0

        # 3. Iterate and Check
        for article in articles:
            processed_count += 1
            if processed_count % 1000 == 0:
                logger.info(f"Processed {processed_count}/{total_articles} articles...")

            url = article.url
            if not url:
                continue

            # Check logic mirrors URLVerificationService.verify_url
            
            # Check 1: Opinion (Hardcoded in service)
            if "/opinion/" in url.lower():
                # We could mark these as 'opinion' if that status exists, 
                # but user specifically asked for wire. 
                # If the goal is "filter out non-news", opinion applies too.
                # However, sticking to the "Wire Backfill" directive for now.
                # If user wants opinion filtered, we can add it, but safety first.
                pass 

            # Check 2: Dynamic Patterns
            match_found = False
            matched_service = None
            
            for cp in compiled_patterns:
                if cp['re'].search(url):
                    match_found = True
                    matched_service = cp['name']
                    # Log the match
                    logger.info(f"MATCH [Wire]: {url} -> {matched_service} (Pattern: {cp['orig']})")
                    break
            
            if match_found:
                # Update the article
                try:
                    # Use a nested transaction (SAVEPOINT) so that if this update fails,
                    # it doesn't abort the entire main transaction.
                    with session.begin_nested():
                        wire_payload = {
                            "provider": matched_service,
                            "detection_method": "url_normalization",
                            "pattern": cp['orig']
                        }
                        
                        update_stmt = text("""
                            UPDATE articles 
                            SET status = 'wire', 
                                wire_check_status = 'wire',
                                wire = :wire_payload,
                                wire_check_attempted_at = NOW()
                            WHERE id = :id
                        """)
                        session.execute(update_stmt, {
                            "wire_payload": json.dumps(wire_payload),
                            "id": article.id
                        })
                        updated_count += 1
                except Exception as e:
                    logger.error(f"Failed to update article {article.id}: {e}")

            # Commit periodically
            if updated_count > 0 and updated_count % 100 == 0:
                session.commit()
        
        # Final commit
        session.commit()
        logger.info("------------------------------------------------")
        logger.info(f"Backfill Complete.")
        logger.info(f"Total Processed: {total_articles}")
        logger.info(f"Total Identified as WIRE: {updated_count}")
        logger.info("------------------------------------------------")

if __name__ == "__main__":
    backfill_url_verification()
