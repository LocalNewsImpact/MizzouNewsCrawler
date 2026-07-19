#!/usr/bin/env python3
"""
Migrate article_entities to partitioned table.

Steps:
1. Create article_entities_partitioned with daily partitioning on created_at
2. Copy all data from article_entities
3. Delete article_entities
4. Rename article_entities_partitioned to article_entities
5. Update transfer config to use partitioning
"""
import subprocess
import json
import urllib.request
import urllib.error
import time

def get_token():
    result = subprocess.run(['gcloud', 'auth', 'print-access-token'], capture_output=True, text=True)
    return result.stdout.strip()

def bq_request(method, url, body=None, token=None):
    if token is None:
        token = get_token()
    
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    
    try:
        resp = urllib.request.urlopen(req)
        content = resp.read()
        if not content:
            return {}  # DELETE returns empty body on success
        return json.loads(content)
    except urllib.error.HTTPError as e:
        print(f'ERROR: {e.code} {e.reason}')
        print(e.read().decode())
        raise

def run_query(query, token):
    """Run a BigQuery query and wait for completion."""
    url = 'https://bigquery.googleapis.com/bigquery/v2/projects/mizzou-news-crawler/queries'
    body = {
        'query': query,
        'useLegacySql': False,
        'timeoutMs': 120000  # 2 minutes
    }
    return bq_request('POST', url, body, token)

def main():
    token = get_token()
    project = 'mizzou-news-crawler'
    dataset = 'mizzou_analytics'
    
    print("=" * 60)
    print("MIGRATING article_entities TO PARTITIONED TABLE")
    print("=" * 60)
    
    # Step 1: Create partitioned table using DDL
    print("\n[1/5] Creating partitioned table...")
    create_ddl = """
    CREATE TABLE IF NOT EXISTS `mizzou-news-crawler.mizzou_analytics.article_entities_partitioned`
    PARTITION BY DATE(created_at)
    OPTIONS(
        description='Article entities with daily partitioning on created_at'
    )
    AS SELECT * FROM `mizzou-news-crawler.mizzou_analytics.article_entities`
    """
    
    result = run_query(create_ddl, token)
    
    # Check if job is still running
    job_ref = result.get('jobReference', {})
    job_id = job_ref.get('jobId')
    
    if not result.get('jobComplete', False):
        print(f"  Job {job_id} started, waiting for completion...")
        # Poll for completion
        for i in range(60):  # Wait up to 5 minutes
            time.sleep(5)
            status_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/jobs/{job_id}'
            status = bq_request('GET', status_url, token=token)
            state = status.get('status', {}).get('state')
            print(f"  Status: {state}")
            if state == 'DONE':
                if 'errorResult' in status.get('status', {}):
                    print(f"  ERROR: {status['status']['errorResult']}")
                    return
                break
        else:
            print("  Timeout waiting for job!")
            return
    
    print("  ✓ Partitioned table created with data copied")
    
    # Step 2: Verify row counts match
    print("\n[2/5] Verifying row counts...")
    verify_query = """
    SELECT 
        (SELECT COUNT(*) FROM `mizzou-news-crawler.mizzou_analytics.article_entities`) as original,
        (SELECT COUNT(*) FROM `mizzou-news-crawler.mizzou_analytics.article_entities_partitioned`) as partitioned
    """
    result = run_query(verify_query, token)
    rows = result.get('rows', [])
    if rows:
        original = int(rows[0]['f'][0]['v'])
        partitioned = int(rows[0]['f'][1]['v'])
        print(f"  Original: {original:,} rows")
        print(f"  Partitioned: {partitioned:,} rows")
        if original != partitioned:
            print(f"  ✗ Row count mismatch! Aborting.")
            return
        print("  ✓ Row counts match")
    
    # Step 3: Delete original table
    print("\n[3/5] Deleting original table...")
    delete_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables/article_entities'
    bq_request('DELETE', delete_url, token=token)
    print("  ✓ Original table deleted")
    
    # Step 4: Rename partitioned table
    print("\n[4/5] Renaming partitioned table to article_entities...")
    # BigQuery doesn't have RENAME, so we use COPY then DELETE
    copy_query = """
    CREATE TABLE `mizzou-news-crawler.mizzou_analytics.article_entities`
    PARTITION BY DATE(created_at)
    OPTIONS(
        description='Article entities extracted via gazetteer NER'
    )
    AS SELECT * FROM `mizzou-news-crawler.mizzou_analytics.article_entities_partitioned`
    """
    result = run_query(copy_query, token)
    
    job_ref = result.get('jobReference', {})
    job_id = job_ref.get('jobId')
    
    if not result.get('jobComplete', False):
        print(f"  Job {job_id} started, waiting for completion...")
        for i in range(60):
            time.sleep(5)
            status_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/jobs/{job_id}'
            status = bq_request('GET', status_url, token=token)
            state = status.get('status', {}).get('state')
            print(f"  Status: {state}")
            if state == 'DONE':
                if 'errorResult' in status.get('status', {}):
                    print(f"  ERROR: {status['status']['errorResult']}")
                    return
                break
    
    print("  ✓ New partitioned table created as article_entities")
    
    # Delete the _partitioned temp table
    delete_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables/article_entities_partitioned'
    bq_request('DELETE', delete_url, token=token)
    print("  ✓ Temp table cleaned up")
    
    # Step 5: Update transfer config to use partitioning
    print("\n[5/5] Updating transfer config to use partitioning...")
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
    print("  ✓ Transfer config updated with partitioning_field: created_at")
    
    # Final verification
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE!")
    print("=" * 60)
    
    # Check table structure
    table_url = f'https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables/article_entities'
    table_info = bq_request('GET', table_url, token=token)
    partitioning = table_info.get('timePartitioning', {})
    print(f"\nNew table partitioning: {partitioning}")
    print(f"Rows: {table_info.get('numRows', 'N/A')}")
    
    # Trigger a test run
    print("\nTriggering test sync...")
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    run_time = f'{today}T00:00:00Z'
    
    trigger_url = f'https://bigquerydatatransfer.googleapis.com/v1/projects/{project}/locations/us/transferConfigs/{config_id}:scheduleRuns'
    trigger_body = {'startTime': run_time, 'endTime': run_time}
    
    trigger_req = urllib.request.Request(trigger_url, data=json.dumps(trigger_body).encode(), method='POST', headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    trigger_resp = urllib.request.urlopen(trigger_req)
    trigger_result = json.loads(trigger_resp.read())
    
    runs = trigger_result.get('runs', [])
    if runs:
        print(f"  Started run: {runs[0].get('name', '').split('/')[-1]}")
        print(f"  State: {runs[0].get('state', 'UNKNOWN')}")

if __name__ == '__main__':
    main()
