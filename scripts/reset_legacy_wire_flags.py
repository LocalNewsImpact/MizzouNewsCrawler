
import sys
import os
import time
from sqlalchemy import text
from src.models.database import DatabaseManager

def reset_legacy_wire_flags():
    """
    Resets 'wire' status for articles that were NOT identified by the
    URL-based verification (i.e. wire_check_status != 'wire').
    
    Target state for reset articles:
    - status: 'cleaned' (so they are valid for analysis but not final)
    - wire_check_status: 'pending' (so they can be re-evaluated if needed)
    - wire: {} (empty dict)
    """
    db = DatabaseManager()
    
    # We want to reset articles where:
    # 1. status = 'wire'
    # 2. wire_check_status IS DISTINCT FROM 'wire'
    #    (This protects the 6420 we just backfilled)
    
    print("Connecting to database...", flush=True)
    count_query = text("""
        SELECT count(*) 
        FROM articles 
        WHERE status = 'wire' 
        AND (wire_check_status != 'wire' OR wire_check_status IS NULL)
    """)
    
    update_query = text("""
        UPDATE articles
        SET 
            status = 'cleaned',
            wire_check_status = 'pending',
            wire = '{}',
            wire_check_attempted_at = NULL
        WHERE id IN (
            SELECT id FROM articles
            WHERE status = 'wire'
            AND (wire_check_status != 'wire' OR wire_check_status IS NULL)
            LIMIT 5000
        )
    """)
    
    with db.get_session() as session:
        # Get total count first
        total_to_fix = session.execute(count_query).scalar()
        print(f"Found {total_to_fix} articles with status='wire' but wire_check_status!='wire'.")
        
        if total_to_fix == 0:
            print("No legacy wire flags to reset.")
            return

        print(f"Starting reset of {total_to_fix} articles in batches of 5000...")
        
        processed = 0
        while processed < total_to_fix:
            try:
                result = session.execute(update_query)
                count = result.rowcount
                session.commit()
                processed += count
                print(f"Reset {count} articles. Total processed: {processed}/{total_to_fix}")
                
                if count == 0:
                    break
                    
                time.sleep(1) # Breathe to avoid locks
                
            except Exception as e:
                print(f"Error executing batch: {e}")
                session.rollback()
                break
                
        # Final count check
        remaining = session.execute(count_query).scalar()
        print(f"Finished. Remaining legacy wire articles: {remaining}")

if __name__ == "__main__":
    reset_legacy_wire_flags()
