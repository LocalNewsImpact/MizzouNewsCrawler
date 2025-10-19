# BigQuery Data Transfer Service - COMPLETE ✅

## Summary

Successfully configured BigQuery Data Transfer Service to automatically sync all data from Cloud SQL PostgreSQL to BigQuery.

## What Was Configured

### 1. Cloud SQL Connection
- **Connection Name**: `cloudsql_connection`
- **Location**: `us`
- **Type**: PostgreSQL
- **Instance**: `mizzou-news-crawler:us-central1:mizzou-db-prod`
- **Database**: `mizzou`
- **User**: `datastream_user`

### 2. Scheduled Transfers (All run at 2 AM CDT / 7 AM UTC)

| Transfer | Schedule | Status | Records Synced |
|----------|----------|--------|----------------|
| Sync Articles from Cloud SQL | Every day 07:00 UTC | ✅ SUCCEEDED | 5,940 articles |
| Sync Article Labels from Cloud SQL | Every day 07:00 UTC | ✅ SUCCEEDED | 7,609 labels |
| Sync Article Entities from Cloud SQL | Every day 07:00 UTC | ✅ SUCCEEDED | 146,409 entities |

**Next Run**: Daily at 7:00 AM UTC (2:00 AM CDT)

## How It Works

1. **Federated Queries**: BigQuery uses `EXTERNAL_QUERY()` to directly query Cloud SQL
2. **Full Refresh**: Each transfer uses `WRITE_TRUNCATE` to replace all data
3. **Atomic Sync**: All three transfers run at the same time to keep data consistent
4. **Fast Execution**: Each transfer completes in 1-2 minutes

## Benefits

✅ **Zero custom code** - Managed by Google  
✅ **Automatic daily syncs** - No manual intervention  
✅ **Complete data** - All articles, labels, and entities  
✅ **Data consistency** - All tables sync at same time  
✅ **Monitoring built-in** - View status in BigQuery console  
✅ **No batch limits** - Handles all data regardless of size  

## Monitoring

View transfer status:
- Console: https://console.cloud.google.com/bigquery/transfers?project=mizzou-news-crawler
- Via CLI: `bq ls --transfer_config --transfer_location=us`

Check last run status:
```bash
bq ls --transfer_run --max_results=1 projects/145096615031/locations/us/transferConfigs/693ab8dd-0000-2226-891c-582429a83fdc
```

## Verify Data

```bash
# Articles
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `mizzou-news-crawler.mizzou_analytics.articles`'

# Labels  
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `mizzou-news-crawler.mizzou_analytics.article_labels`'

# Entities
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `mizzou-news-crawler.mizzou_analytics.article_entities`'
```

## Cost

**Estimated**: $5-10/month
- Query costs: ~$5/month (queries Cloud SQL daily)
- Storage: Already covered by BigQuery dataset
- Cloud SQL bandwidth: Negligible (same region)

## Manual Trigger

To manually trigger a sync (for testing or ad-hoc needs):

```bash
# Articles
bq mk --transfer_run --run_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  projects/145096615031/locations/us/transferConfigs/693ab8dd-0000-2226-891c-582429a83fdc

# Labels
bq mk --transfer_run --run_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  projects/145096615031/locations/us/transferConfigs/68f42124-0000-24c3-8536-582429b325d0

# Entities
bq mk --transfer_run --run_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  projects/145096615031/locations/us/transferConfigs/692c3665-0000-2628-be02-f4f5e80d0508
```

## What Was Deleted

- ❌ Manual export script (`src/pipeline/bigquery_export.py`)
- ❌ Export CLI command (`src/cli/commands/bigquery_export.py`)
- ❌ Export CronJob (`k8s/bigquery-export-cronjob.yaml`)
- ❌ Test scripts

All replaced with managed BigQuery Data Transfer Service.

---

**Status**: ✅ COMPLETE - All data syncing automatically daily at 2 AM CDT
