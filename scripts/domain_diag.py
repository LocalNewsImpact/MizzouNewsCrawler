import sys
from datetime import datetime, timedelta
from sqlalchemy import text

from src.models.database import DatabaseManager


def main(domains):
    variants = set()
    for d in domains:
        variants.add(d)
        if not d.startswith("www."):
            variants.add("www." + d)
    print("Domains:", domains)
    print("Variants:", sorted(list(variants)))

    db = DatabaseManager()
    with db.get_session() as s:
        # Resolve actual source hosts in sources table
        params_eq = {f"h{i}": h for i, h in enumerate(variants)}
        where_eq = " OR ".join([f"host = :h{i}" for i in range(len(params_eq))])
        rows = s.execute(text(f"SELECT host FROM sources WHERE {where_eq}"), params_eq).fetchall()
        source_hosts = sorted({r[0] for r in rows})
        if not source_hosts:
            params_like = {f"h{i}": f"%{h}%" for i, h in enumerate(variants)}
            where_like = " OR ".join([f"host ILIKE :h{i}" for i in range(len(params_like))])
            rows = s.execute(text(f"SELECT host FROM sources WHERE {where_like}"), params_like).fetchall()
            source_hosts = sorted({r[0] for r in rows})
        print("Resolved sources.host:", source_hosts)

        hosts = source_hosts if source_hosts else list(variants)
        since_60 = datetime.utcnow() - timedelta(days=60)

        # Counts by status
        q = text(
            """
            SELECT status, COUNT(*)
            FROM candidate_links
            WHERE source = ANY(:hosts)
              AND discovered_at >= :since
            GROUP BY status ORDER BY status
            """
        )
        rows = s.execute(q, {"hosts": hosts, "since": since_60}).fetchall()
        print("candidate_links counts (60d):", rows)

        # Article-status not extracted
        q2 = text(
            """
            SELECT COUNT(*)
            FROM candidate_links cl
            WHERE cl.source = ANY(:hosts)
              AND cl.status = 'article'
              AND cl.discovered_at >= :since
              AND NOT EXISTS (
                SELECT 1 FROM articles a WHERE a.candidate_link_id = cl.id
              )
            """
        )
        cnt_art_no_extract = s.execute(q2, {"hosts": hosts, "since": since_60}).scalar()
        print("article-status not extracted (60d):", cnt_art_no_extract)

        # Discovered-status count
        q3 = text(
            """
            SELECT COUNT(*)
            FROM candidate_links cl
            WHERE cl.source = ANY(:hosts)
              AND cl.status = 'discovered'
              AND cl.discovered_at >= :since
            """
        )
        cnt_discovered = s.execute(q3, {"hosts": hosts, "since": since_60}).scalar()
        print("discovered-status count (60d):", cnt_discovered)

        # Sample article-status not extracted URLs
        q4 = text(
            """
            SELECT cl.id, cl.url, cl.discovered_at
            FROM candidate_links cl
            WHERE cl.source = ANY(:hosts)
              AND cl.status = 'article'
              AND cl.discovered_at >= :since
              AND NOT EXISTS (
                SELECT 1 FROM articles a WHERE a.candidate_link_id = cl.id
              )
            ORDER BY cl.discovered_at DESC
            LIMIT 10
            """
        )
        sample = s.execute(q4, {"hosts": hosts, "since": since_60}).fetchall()
        print("sample article-status not extracted:")
        for r in sample:
            print(r)


if __name__ == "__main__":
    domains = sys.argv[1:] or ["newstribune.com", "kq2.com", "republicmonitor.com"]
    main(domains)
