#!/usr/bin/env python3
"""Extract missing sources from CSV and create a new CSV with details."""

import csv
import subprocess
import json
from urllib.parse import urlparse

# Read CSV data
csv_data = []
csv_file = '/Users/kiesowd/Downloads/Missouri URL Tracker - Working URLs.csv'

with open(csv_file, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('URL') and row['URL'].strip():
            csv_data.append({
                'name': row.get('Name', ''),
                'url': row['URL'],
                'owner': row.get('Owner', ''),
                'working': row.get('Working', ''),
                'host_id': row.get('host_id', '')
            })

print(f"Read {len(csv_data)} sources from CSV")

# Extract hosts from URLs
url_to_host = {}
for item in csv_data:
    url = item['url']
    try:
        parsed = urlparse(url)
        host = parsed.netloc or parsed.path.split('/')[0]
        if host:
            url_to_host[url] = host.lower()
    except:
        url_to_host[url] = ''

# Get existing hosts from PRODUCTION database via kubectl
print("Querying production database...")
kubectl_cmd = [
    'kubectl', 'exec', '-n', 'production',
    'deployment/mizzou-api', '--',
    'python', '-c',
    '''
from src.models.database import DatabaseManager
from sqlalchemy import text
import json

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text("SELECT DISTINCT LOWER(host) as host FROM sources WHERE host IS NOT NULL")).fetchall()
    hosts = [row[0] for row in result if row[0]]
    print(json.dumps(hosts))
'''
]

result = subprocess.run(kubectl_cmd, capture_output=True, text=True)
db_hosts = json.loads(result.stdout.strip())
db_host_set = set(db_hosts)

print(f"Found {len(db_host_set)} existing hosts in production database")

# Find missing sources
missing_sources = []
for item in csv_data:
    url = item['url']
    host = url_to_host.get(url, '')

    if host and host not in db_host_set:
        missing_sources.append({
            'name': item['name'],
            'host': host,
            'url': url,
            'owner': item['owner'],
            'working': item['working'],
            'host_id': item['host_id']
        })

# Write to new CSV
output_file = '/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts/missing_sources.csv'
with open(output_file, 'w', newline='', encoding='utf-8') as f:
    fieldnames = ['name', 'host', 'url', 'owner', 'working', 'host_id']
    writer = csv.DictWriter(f, fieldnames=fieldnames)

    writer.writeheader()
    for source in sorted(missing_sources, key=lambda x: x['host']):
        writer.writerow(source)

print(f'Found {len(missing_sources)} missing sources')
print(f'Written to: {output_file}')
print('\nMissing sources:')
for source in sorted(missing_sources, key=lambda x: x['host']):
    owner_info = f" (Owner: {source['owner']})" if source['owner'] else ""
    print(f"  {source['host']}: {source['name']}{owner_info}")
