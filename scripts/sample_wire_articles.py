import sys
import json

sys.path.append('/app')

from src.models.database import DatabaseManager
from sqlalchemy import text

QUERY = text(
    """
    SELECT a.id, a.url, cl.source, a.title, a.wire, a.wire_check_status, a.status, a.extracted_at
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE a.wire_check_status = 'wire'
    ORDER BY a.extracted_at DESC
    LIMIT 10
    """
)


def main() -> None:
    print("Fetching sample wire articles...", flush=True)
    db = DatabaseManager()
    with db.get_session() as session:
        rows = session.execute(QUERY).fetchall()

    if not rows:
        print("No wire articles found.", flush=True)
        return

    for row in rows:
        wire_payload = row.wire
        if isinstance(wire_payload, str):
            try:
                wire_payload = json.loads(wire_payload)
            except json.JSONDecodeError:
                pass
        print("-" * 80, flush=True)
        print(f"Article ID: {row.id}", flush=True)
        print(f"Source: {row.source}", flush=True)
        print(f"Status: {row.status} / wire_check_status={row.wire_check_status}", flush=True)
        print(f"URL: {row.url}", flush=True)
        print(f"Title: {row.title}", flush=True)
        print(f"Extracted at: {row.extracted_at}", flush=True)
        print(f"Wire payload: {wire_payload}", flush=True)


if __name__ == "__main__":
    main()
