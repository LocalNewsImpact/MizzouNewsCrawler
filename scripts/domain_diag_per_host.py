import sys
import json
from datetime import datetime, timedelta
from sqlalchemy import text

from src.models.database import DatabaseManager


def main(domains, out_path=None):
    variants = set()
    for d in domains:
        variants.add(d)
        if not d.startswith("www."):
            variants.add("www." + d)
    print("Domains:", domains)
    print("Variants:", sorted(list(variants)))

    db = DatabaseManager()
    output = {
        "generated_at": datetime.utcnow().isoformat(),
        "domains": domains,
        "hosts_resolved": [],
        "per_host": {}
    }
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
        output["hosts_resolved"] = source_hosts

        hosts = source_hosts if source_hosts else list(variants)
        since_60 = datetime.utcnow() - timedelta(days=60)

        for host in hosts:
            print(f"\n=== Host: {host} ===")
            host_result = {
                "counts": [],
                "article_not_extracted": 0,
                "discovered_count": 0,
                "sample_article_not_extracted": []
            }

            # Counts by status (join to sources for reliable matching)
            rows = s.execute(text(
                """
                SELECT cl.status, COUNT(*)
                FROM candidate_links cl
                JOIN sources s2 ON cl.source_id = s2.id
                WHERE s2.host = :host
                  AND cl.discovered_at >= :since
                GROUP BY cl.status ORDER BY cl.status
                """
            ), {"host": host, "since": since_60}).fetchall()
            print("candidate_links counts (60d):", rows)
            host_result["counts"] = [(r[0], int(r[1])) for r in rows]

            # Article-status not extracted
            cnt_art_no_extract = s.execute(text(
                """
                SELECT COUNT(*)
                FROM candidate_links cl
                JOIN sources s2 ON cl.source_id = s2.id
                WHERE s2.host = :host
                  AND cl.status = 'article'
                  AND cl.discovered_at >= :since
                  AND NOT EXISTS (
                    SELECT 1 FROM articles a WHERE a.candidate_link_id = cl.id
                  )
                """
            ), {"host": host, "since": since_60}).scalar()
            print("article-status not extracted (60d):", cnt_art_no_extract)
            host_result["article_not_extracted"] = int(cnt_art_no_extract or 0)

            # Discovered-status count
            cnt_discovered = s.execute(text(
                """
                SELECT COUNT(*)
                FROM candidate_links cl
                JOIN sources s2 ON cl.source_id = s2.id
                WHERE s2.host = :host
                  AND cl.status = 'discovered'
                  AND cl.discovered_at >= :since
                """
            ), {"host": host, "since": since_60}).scalar()
            print("discovered-status count (60d):", cnt_discovered)
            host_result["discovered_count"] = int(cnt_discovered or 0)

            # Sample article-status not extracted URLs
            sample = s.execute(text(
                """
                SELECT cl.id, cl.url, cl.discovered_at
                FROM candidate_links cl
                JOIN sources s2 ON cl.source_id = s2.id
                WHERE s2.host = :host
                  AND cl.status = 'article'
                  AND cl.discovered_at >= :since
                  AND NOT EXISTS (
                    SELECT 1 FROM articles a WHERE a.candidate_link_id = cl.id
                  )
                ORDER BY cl.discovered_at DESC
                LIMIT 10
                """
            ), {"host": host, "since": since_60}).fetchall()
            print("sample article-status not extracted:")
            for r in sample:
                print(r)
                host_result["sample_article_not_extracted"].append(
                    {
                        "candidate_id": str(r[0]),
                        "url": r[1],
                        "discovered_at": r[2].isoformat() if hasattr(r[2], 'isoformat') else str(r[2])
                    }
                )
            output["per_host"][host] = host_result

    # Write JSON output if requested
    if out_path:
        try:
            with open(out_path, "w") as f:
                json.dump(output, f, indent=2)
            print(f"\nSaved JSON to: {out_path}")
        except Exception as e:
            print(f"Failed to write JSON to {out_path}: {e}")


if __name__ == "__main__":
    # Parse optional --out arg manually (avoid argparse to simplify quoting)
    out_arg = None
    doms = []
    for a in sys.argv[1:]:
        if a.startswith("--out="):
            out_arg = a.split("=",1)[1]
        else:
            doms.append(a)
    domains = doms or ["newstribune.com", "kq2.com", "republicmonitor.com"]
    main(domains, out_arg)
