# Setting up Google Cloud Datastream for PostgreSQL → BigQuery

**✅ This replaces the manual BigQuery export code with Google's managed CDC service.**

The manual export code (`src/pipeline/bigquery_export.py`, CLI command, and CronJob) has been removed.
This document provides the setup instructions for the replacement: Google Cloud Datastream.

## What Datastream Does
- Continuously replicates Cloud SQL PostgreSQL to BigQuery in real-time
- Handles schema changes automatically
- No custom code needed
- Handles inserts, updates, deletes
- Automatic backfill of historical data

## Setup Steps

### 1. Enable APIs
```bash
gcloud services enable datastream.googleapis.com \
  --project=mizzou-news-crawler
```

### 2. Create Cloud SQL User for Replication
Datastream needs a PostgreSQL user with replication privileges:

```bash
# Connect to Cloud SQL
gcloud sql connect mizzou-db-prod --user=postgres --database=mizzou_prod

# In psql:
CREATE USER datastream_user WITH REPLICATION PASSWORD 'YOUR_STRONG_PASSWORD';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO datastream_user;
GRANT USAGE ON SCHEMA public TO datastream_user;

# Enable logical replication
ALTER SYSTEM SET wal_level = logical;
```

Then restart Cloud SQL instance:
```bash
gcloud sql instances restart mizzou-db-prod
```

### 3. Create Datastream Connection Profile for Cloud SQL

Go to: https://console.cloud.google.com/datastream/connection-profiles

**Create PostgreSQL connection profile:**
- Name: `cloudsql-postgres-source`
- Type: PostgreSQL
- Hostname: Use the Cloud SQL private IP
- Port: 5432
- Username: `datastream_user`
- Password: (from step 2)
- Database: `mizzou_prod`

### 4. Create Datastream Connection Profile for BigQuery

**Create BigQuery connection profile:**
- Name: `bigquery-destination`
- Type: BigQuery
- Location: `us-central1` (same as Cloud SQL)

### 5. Create Datastream Stream

Go to: https://console.cloud.google.com/datastream/streams

**Create stream:**
- Name: `cloudsql-to-bigquery`
- Source: `cloudsql-postgres-source`
- Destination: `bigquery-destination`
- Dataset: `mizzou_analytics`
- Tables to replicate:
  - `articles`
  - `article_labels`
  - `article_entities`
  - `candidate_links`
  - `sources`
  - (add any other tables you want)

**Stream options:**
- Backfill mode: Automatic (will copy all existing data first)
- CDC mode: Enabled (continuous replication)
- Write mode: Append (keeps history) or Merge (updates in place)

### 6. Start the Stream

Once created, click "Start" on the stream. Datastream will:
1. Backfill all historical data (5,940 articles + labels + entities)
2. Then continuously replicate new changes in real-time

### 7. Clean Up Old Export Code

Once Datastream is working, you can:
1. Delete the BigQuery export cronjob:
   ```bash
   kubectl delete cronjob bigquery-export -n production
   ```

2. Remove the export code:
   - `src/pipeline/bigquery_export.py`
   - `src/cli/commands/bigquery_export.py`
   - Related tests

## Monitoring

View Datastream status:
- Console: https://console.cloud.google.com/datastream/streams
- Metrics: Latency, throughput, errors
- Logs: Cloud Logging

## Cost Estimate

Datastream pricing (approximate):
- $0.20 per GB processed (one-time backfill)
- $0.10 per GB/month (ongoing CDC)
- Your data is small, so costs will be minimal (~$1-5/month)

## Benefits Over Custom Code

✅ No manual batching logic  
✅ No duplicate detection needed  
✅ Handles schema changes automatically  
✅ Real-time replication (seconds of latency)  
✅ Managed service (no maintenance)  
✅ Automatic retries and error handling  
✅ Built-in monitoring and alerting  

## Next Steps

1. Follow the setup steps above
2. Verify data is flowing to BigQuery
3. Delete the manual export cronjob and code
4. Enjoy automatic real-time replication!
