import sys
sys.path.append('/app')
from src.models.database import DatabaseManager
from sqlalchemy import text

def kill_stuck_pid(pid):
    db = DatabaseManager()
    with db.get_session() as session:
        print(f'Attempting to terminate PID {pid}...', flush=True)
        # Use pg_terminate_backend
        query = text(f"SELECT pg_terminate_backend({pid})")
        result = session.execute(query).scalar()
        print(f'Result: {result}', flush=True)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        pid = int(sys.argv[1])
        kill_stuck_pid(pid)
    else:
        print("Please provide a PID")