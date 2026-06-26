#!/bin/bash
# Run export from pod and copy back

POD=$(kubectl get pod -n production -l app=mizzou-api -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n production $POD -- python3 -c '
import csv, sys
sys.path.insert(0, "/app")
from src.models.database import DatabaseManager
from sqlalchemy import text

hosts = ["mycameronnews.com", "griffonnews.com", "kcur.org", "studlife.com", "joplinglobe.com"]
db = DatabaseManager()
with db.get_session() as session:
    with open("/tmp/source_export.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["hostname", "canonical_name", "url", "status", "discovered_at", "wire_check_status", "wire_service_name"])
        for host_pattern in hosts:
            clean_host = host_pattern.replace("www.", "")
            source = session.execute(text(f"SELECT id, host, canonical_name FROM sources WHERE host LIKE '%{clean_host}%' LIMIT 1")).fetchone()
            source = session.execute(text(f"SELECT id, host, canonical_name FROM sources WHERE host LIKE '%{clean_host}%' LIMIT 1")).fetchone()
                continue
            source_id, hostname, name = source
            links = session.execute(text(f"SELECT cl.url, cl.status, cl.discovered_at FROM candidate_links cl WHERE cl.source_id = '"'"'{source_id}'"'"' AND cl.discovered_at >= NOW() - INTERVAL '"'"'14 days'"'"' ORDER BY cl.discovered_at DESC LIMIT 50")).fetchall()
            for url, status, disc_at in links:
                article = session.execute(text(f"SELECT wire_check_status, wire_service_name FROM articles WHERE candidate_link_id IN (SELECT id FROM candidate_links WHERE url = '"'"'{url}'"'"') LIMIT 1")).fetchone()
                wire_status = article[0] if article else ""
                wire_name = article[1] if article else ""
                writer.writerow([hostname, name, url, status, disc_at, wire_status, wire_name])
print("Export complete")
'

kubectl cp production/$POD:/tmp/source_export.csv /tmp/source_export.csv

wc -l /tmp/source_export.csv
head -20 /tmp/source_export.csv
