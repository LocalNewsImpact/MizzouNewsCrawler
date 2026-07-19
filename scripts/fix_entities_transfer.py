#!/usr/bin/env python3
"""Fix entities transfer by removing partitioning_field requirement."""
import subprocess
import json
import urllib.request
import urllib.error

# Get auth token
result = subprocess.run(['gcloud', 'auth', 'print-access-token'], capture_output=True, text=True)
token = result.stdout.strip()

config_id = '692c3665-0000-2628-be02-f4f5e80d0508'
url = f'https://bigquerydatatransfer.googleapis.com/v1/projects/mizzou-news-crawler/locations/us/transferConfigs/{config_id}?updateMask=params'

# New params WITHOUT partitioning_field
new_params = {
    'params': {
        'destination_table_name_template': 'article_entities',
        'query': "SELECT * FROM EXTERNAL_QUERY(\"mizzou-news-crawler.us.cloudsql_connection\", \"SELECT * FROM article_entities WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '4 days';\");",
        'write_disposition': 'WRITE_APPEND'
    }
}

body = json.dumps(new_params).encode()
req = urllib.request.Request(url, data=body, method='PATCH', headers={
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json'
})

try:
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    print('SUCCESS! Updated params:')
    print(json.dumps(result.get('params', {}), indent=2))
except urllib.error.HTTPError as e:
    print(f'ERROR: {e.code} {e.reason}')
    print(e.read().decode())
