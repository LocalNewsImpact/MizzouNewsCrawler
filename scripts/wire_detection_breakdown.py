import sys
import json
from collections import Counter

sys.path.append('/app')

from src.models.database import DatabaseManager
from sqlalchemy import text

QUERY = text(
    """
    SELECT id, wire
    FROM articles
    WHERE wire_check_status = 'wire'
    AND wire IS NOT NULL
    LIMIT 1000
    """
)


def main() -> None:
    print("Fetching sample...", flush=True)
    db = DatabaseManager()
    with db.get_session() as session:
        rows = session.execute(QUERY).fetchall()

    counter = Counter()
    for row in rows:
        payload = row.wire
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            method = payload.get("detection_method") or "unknown"
            counter[method] += 1
    total = sum(counter.values())
    print(f"Sample size: {total}", flush=True)
    for method, count in counter.most_common():
        pct = (count / total * 100) if total else 0
        print(f"{method}: {count} ({pct:.1f}%)", flush=True)


if __name__ == "__main__":
    main()
