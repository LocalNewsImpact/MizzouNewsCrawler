import json
import sys
from typing import Iterable

sys.path.append('/app')

from sqlalchemy import text
from src.models.database import DatabaseManager

PENDING_QUERY = text(
    """
    SELECT a.id,
           cl.source,
           a.status,
           a.wire_check_status,
           a.url,
           a.title,
           a.wire,
           a.extracted_at
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE a.wire_check_status = 'pending'
    ORDER BY a.extracted_at DESC
    LIMIT :limit
    """
)

WIRE_QUERY = text(
    """
    SELECT a.id,
           cl.source,
           a.status,
           a.wire_check_status,
           a.url,
           a.title,
           a.wire,
           a.extracted_at
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE a.wire_check_status = 'wire'
    ORDER BY a.extracted_at DESC
    LIMIT :limit
    """
)


def _deserialize(payload):
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
    return payload


def _print_rows(label: str, rows: Iterable, limit: int) -> None:
    print("=" * 80, flush=True)
    print(f"{label} (showing up to {limit})", flush=True)
    print("=" * 80, flush=True)
    count = 0
    for row in rows:
        count += 1
        payload = _deserialize(row.wire)
        print(f"#{count}", flush=True)
        print(f"  Article ID: {row.id}", flush=True)
        print(f"  Source    : {row.source}", flush=True)
        print(f"  Status    : {row.status} / wire_check_status={row.wire_check_status}", flush=True)
        print(f"  URL       : {row.url}", flush=True)
        print(f"  Title     : {row.title}", flush=True)
        print(f"  Extracted : {row.extracted_at}", flush=True)
        print(f"  Wire data : {payload}", flush=True)
        print("-" * 80, flush=True)
    if count == 0:
        print("(no rows)", flush=True)


def main(limit: int = 20) -> None:
    print("Sampling pending and wire articles...", flush=True)
    db = DatabaseManager()
    with db.get_session() as session:
        pending_rows = session.execute(PENDING_QUERY, {"limit": limit}).fetchall()
        wire_rows = session.execute(WIRE_QUERY, {"limit": limit}).fetchall()

    _print_rows("Pending queue sample", pending_rows, limit)
    _print_rows("Confirmed wire sample", wire_rows, limit)


if __name__ == "__main__":
    main()
