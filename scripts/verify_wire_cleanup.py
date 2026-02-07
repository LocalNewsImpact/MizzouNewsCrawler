
import sys
from sqlalchemy import text
from src.models.database import DatabaseManager

def check_counts():
    db = DatabaseManager()
    query = text("""
        SELECT 
            (SELECT COUNT(*) FROM articles WHERE status = 'wire') as total_wire_status,
            (SELECT COUNT(*) FROM articles WHERE wire_check_status = 'wire') as total_wire_check,
            (SELECT COUNT(*) FROM articles WHERE status = 'wire' AND wire_check_status != 'wire') as mismatch_count
    """)
    
    with db.get_session() as session:
        result = session.execute(query).fetchone()
        print(f"Total Status='wire': {result[0]}")
        print(f"Total WireCheck='wire': {result[1]}")
        print(f"Mismatch (candidates for reset): {result[2]}")

if __name__ == "__main__":
    check_counts()
