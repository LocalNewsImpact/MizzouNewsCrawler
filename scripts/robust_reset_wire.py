import sys
import os
sys.path.append('/app')

from src.models.database import DatabaseManager
from sqlalchemy import text
import time
import sys

def reset_invalid_wires():
    db = DatabaseManager()
    total_reset = 0
    batch_size = 1000
    
    print("Starting batched reset of invalid wire flags...")
    
    while True:
        with db.get_session() as session:
            # Select IDs of articles that are status='wire' BUT NOT confirmed by our URL check
            # We want to clear these out.
            result = session.execute(text("""
                SELECT id FROM articles 
                WHERE status = 'wire' 
                AND (wire_check_status != 'wire' OR wire_check_status IS NULL)
                LIMIT :limit
            """), {"limit": batch_size}).fetchall()
            
            if not result:
                print("No more invalid wire articles found.")
                break
                
            article_ids = [row[0] for row in result]
            count = len(article_ids)
            
            # Update batch
            # Resetting to 'cleaned' allows them to proceed down the pipeline again if needed
            # Set wire_check_status back to 'pending' so the processor will re-run detection
            stmt = text("""
                UPDATE articles 
                SET status = 'cleaned', 
                    wire_check_status = 'pending',
                    wire = NULL
                WHERE id = ANY(:ids)
            """)
            
            session.execute(stmt, {"ids": article_ids})
            session.commit()
            
            total_reset += count
            print(f"Reset batch of {count}. Total reset so far: {total_reset}")
            
            # Short pause to prevent lock contention
            time.sleep(0.5)

if __name__ == "__main__":
    try:
        reset_invalid_wires()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)
