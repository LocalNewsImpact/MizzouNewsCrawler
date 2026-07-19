#!/usr/bin/env python3
"""Manually trigger BigQuery Data Transfer runs."""

import requests
from datetime import datetime, timezone
from google.auth import default
from google.auth.transport.requests import Request

credentials, _ = default()
credentials.refresh(Request())

base_url = 'https://bigquerydatatransfer.googleapis.com/v1'
headers = {
    'Authorization': f'Bearer {credentials.token}',
    'Content-Type': 'application/json'
}

# Articles transfer config
config_path = 'projects/145096615031/locations/us/transferConfigs/693ab8dd-0000-2226-891c-582429a83fdc'

# Trigger manual run - must use midnight UTC
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
run_time = f'{today}T00:00:00Z'
url = f'{base_url}/{config_path}:scheduleRuns'
body = {
    'startTime': run_time,
    'endTime': run_time
}

print(f'Triggering manual articles sync at {run_time}...')
resp = requests.post(url, headers=headers, json=body)

if resp.status_code == 200:
    runs = resp.json().get('runs', [])
    for run in runs:
        print(f"Started run: {run.get('name')}")
        print(f"State: {run.get('state')}")
else:
    print(f'ERROR: {resp.status_code}')
    print(resp.text)
