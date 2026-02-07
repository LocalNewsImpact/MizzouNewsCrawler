import sys
sys.path.append('/app')
from src.models.database import DatabaseManager
from sqlalchemy import text
import time

def verify():
    with open('/tmp/verify_output.txt', 'w') as f:
        f.write("Starting...\n")
        db = DatabaseManager()
        with db.get_session() as session:
            f.write("Connected.\n")
            
            # Simple count first
            count = session.execute(text("SELECT count(*) FROM articles")).scalar()
            f.write(f"Total Articles: {count}\n")
            
            # Status breakdown
            f.write("\n--- STATUS ---\n")
            rows = session.execute(text("SELECT status, count(*) FROM articles GROUP BY status")).fetchall()
            for r in rows:
                f.write(f"{r[0]}: {r[1]}\n")

            # Wire status breakdown
            f.write("\n--- WIRE CHECK STATUS ---\n")
            rows = session.execute(text("SELECT wire_check_status, count(*) FROM articles GROUP BY wire_check_status")).fetchall()
            for r in rows:
                f.write(f"{r[0]}: {r[1]}\n")
            
            # Specific wire JSON breakdown
            f.write("\n--- WIRE JSON ---\n")
            c = session.execute(text("SELECT count(*) FROM articles WHERE status='wire' AND wire IS NOT NULL")).scalar()
            f.write(f"Status=Wire & JSON Present: {c}\n")

if __name__ == "__main__":
    verify()
