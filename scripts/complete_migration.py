#!/usr/bin/env python3
"""Complete entities migration steps 4 and 5."""
import subprocess
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timezone

def get_token():
    result = subprocess.run(['gcloud', 'auth', 'print-access-token'], capture_output=True, text=True)
    return result.stdout.strip()

def bq_query(query, token):
    url = 'https://bigquery.googleapis.com/bigquery/v2/projects/mizzou-news-crawler/queries'
    body = {'query': query, 'useLegacySql': False, 'timeoutMs': 120000}
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

def wait_for_job(job_id, token):
    project = 'mizzou-news-crawler'
    for i in range(60):
        time.sleep(5)
        status_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/jobs/{job_id}'
        req = urllib.request.Request(status_url, headers={'Authorization': f'Bearer {token}'})
        resp = urllib.request.urlopen(req)
        status = json.loads(resp.read())
        state = status.get('status', {}).get('state')
        print(f'  Status: {state}')
        if state == 'DONE':
            if 'errorResult' in status.get('status', {}):
                print(f"  ERROR: {status['status']['errorResult']}")
                return False
            return True
    return False

def main():
    token = get_token()
    project = 'mizzou-news-crawler'
    
    # Step 4: Create article_entities with partitioning
    print('[4/5] Creating article_entities from partitioned table...')
    query = """
    CREATE TABLE `mizzou-news-crawler.mizzou_analytics.article_entities`
    PARTITION BY DATE(created_at)
    OPTIONS(description='Article entities extracted via gazetteer NER')
    AS SELECT * FROM `mizzou-news-crawler.mizzou_analytics.article_entities_partitioned`
    """
    
    result = bq_query(query, token)
    job_id = result.get('jobReference', {}).get('jobId')
    
    if not result.get('jobComplete', False):
        print(f'  Job {job_id} started, waiting...')
        if not wait_for_job(job_id, token):
            return
    
    print('  ✓ article_entities created with partitioning')
    
    # Delete temp table
    print('\n  Cleaning up temp table...')
    delete_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/mizzou_analytics/tables/article_entities_partitioned'
    req = urllib.request.Request(delete_url, method='DELETE', headers={'Authorization': f'Bearer {token}'})
    urllib.request.urlopen(req)
    print('  ✓ Temp table deleted')
    
    # Step 5: Update transfer config
    print('\n[5/5] Updating transfer config to use partitioning...')
    config_id = '692c3665-0000-2628-be02-f4f5e80d0508'
    url = f'https://bigquerydatatransfer.googleapis.com/v1/projects/{project}/locations/us/transferConfigs/{config_id}?updateMask=params'
    
    new_params = {
        'params': {
            'destination_table_name_template': 'article_entities',
            'query': "SELECT * FROM EXTERNAL_QUERY(\"mizzou-news-crawler.us.cloudsql_connection\", \"SELECT * FROM article_entities WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '4 days';\");",
            'write_disposition': 'WRITE_APPEND',
            'partitioning_field': 'created_at'
        }
    }
    
    body = json.dumps(new_params).encode()
    req = urllib.request.Request(url, data=body, method='PATCH', headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    print('  ✓ Transfer config updated with partitioning_field: created_at')
    
    # Verify
    print('\n' + '=' * 60)
    print('MIGRATION COMPLETE!')
    print('=' * 60)
    
    # Check table structure
    table_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/mizzou_analytics/tables/article_entities'
    req = urllib.request.Request(table_url, headers={'Authorization': f'Bearer {token}'})
    resp = urllib.request.urlopen(req)
    table_info = json.loads(resp.read())
    partitioning = table_info.get('timePartitioning', {})
    print(f'\nNew table partitioning: {partitioning}')
    print(f'Rows: {table_info.get("numRows", "N/A")}')
    
    # Trigger test sync
    print('\nTriggering test sync...')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    run_time = f'{today}T00:00:00Z'
    
    trigger_url = f'https://bigquerydatatransfer.googleapis.com/v1/projects/{project}/locations/us/transferConfigs/{config_id}:scheduleRuns'
    trigger_body = {'startTime': run_time, 'endTime': run_time}
    
    req = urllib.request.Request(trigger_url, data=json.dumps(trigger_body).encode(), method='POST', headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    resp = urllib.request.urlopen(req)
    trigger_result = json.loads(resp.read())
    
    runs = trigger_result.get('runs', [])
    if runs:
        print(f"  Started run: {runs[0].get('name', '').split('/')[-1]}")
        print(f"  State: {runs[0].get('state', 'UNKNOWN')}")

if __name__ == '__main__':
    main()
