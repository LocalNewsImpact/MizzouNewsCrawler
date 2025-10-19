# BigQuery Export Pipeline

> **⚠️ DEPRECATED**: This manual export approach has been replaced with **Google Cloud Datastream**, a managed CDC (Change Data Capture) service that provides real-time replication.
>
> **See [DATASTREAM_SETUP.md](../DATASTREAM_SETUP.md) for the new approach.**

## Migration to Datastream

The manual BigQuery export code has been removed in favor of Google Cloud Datastream, which provides:

✅ **Automatic replication** of ALL tables (articles, labels, entities)  
✅ **Real-time sync** (seconds of latency instead of daily batch)  
✅ **Automatic schema changes** handling  
✅ **No custom code** to maintain  
✅ **No batching, limits, or pagination** issues  
✅ **Managed service** with built-in monitoring and retries  

For setup instructions, see: **[DATASTREAM_SETUP.md](../DATASTREAM_SETUP.md)**

---

## Historical Overview (For Reference Only)

The previous BigQuery export pipeline extracted article data from the PostgreSQL production database and loaded it into BigQuery for analytics and reporting. This enabled:

- Historical analysis of article trends
- County-level news coverage metrics
- CIN (Community Information Need) classification analytics
- Named entity extraction analysis
- Source performance tracking

## Architecture

### Data Flow

```
PostgreSQL (Cloud SQL)
    ↓
Python Export Script (src/pipeline/bigquery_export.py)
    ↓
BigQuery Dataset (mizzou_analytics)
    → articles table (partitioned by published_date)
    → cin_labels table
    → entities table
    → sources table (dimension)
```

### Tables Exported

1. **articles**: Core article data with metadata
   - Partitioned by `published_date` (monthly)
   - Clustered by `county`, `source_id`
   - Includes: title, text, summary, authors, word count

2. **cin_labels**: CIN classification results
   - Links to articles table
   - Includes: label, confidence, model version
   
3. **entities**: Named entity extraction results
   - Links to articles table
   - Includes: entity_type, entity_text, confidence

4. **sources**: Dimension table for news sources
   - Static reference data
   - Includes: name, URL, county, state, type

## Deployment

### Kubernetes CronJob

The export runs daily at 2 AM UTC (after the main pipeline completes):

```bash
# Deploy the CronJob
kubectl apply -f k8s/bigquery-export-cronjob.yaml

# Check status
kubectl get cronjobs -n production
kubectl get jobs -n production | grep bigquery-export

# View logs
kubectl logs -n production job/bigquery-export-<timestamp>
```

### Manual Execution

You can trigger the export manually for testing or backfilling:

```bash
# Export last 7 days (default)
kubectl exec -n production deployment/mizzou-cli -- \
  python -m src.cli.main bigquery-export

# Export last 30 days
kubectl exec -n production deployment/mizzou-cli -- \
  python -m src.cli.main bigquery-export --days-back 30

# Custom batch size
kubectl exec -n production deployment/mizzou-cli -- \
  python -m src.cli.main bigquery-export --days-back 7 --batch-size 500
```

### Local Development

```bash
# Activate virtual environment
source venv/bin/activate

# Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost/dbname"
export GOOGLE_CLOUD_PROJECT="mizzou-news-crawler"

# Run export
python -m src.cli.main bigquery-export --days-back 7
```

## Configuration

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--days-back` | 7 | Number of days to look back for articles |
| `--batch-size` | 1000 | Number of rows to process at once |

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `GOOGLE_CLOUD_PROJECT`: GCP project ID (mizzou-news-crawler)
- `APP_ENV`: Application environment (production/staging)
- `LOG_LEVEL`: Logging level (INFO/DEBUG)

## Monitoring

### Success Metrics

The export logs statistics on completion:

```
INFO: Articles exported: 245
INFO: CIN labels exported: 189
INFO: Entities exported: 1,234
INFO: Errors: 0
```

### Cloud Monitoring

Query export job metrics in Cloud Console:

```sql
-- Check export job history
SELECT
  timestamp,
  jsonPayload.articles_exported,
  jsonPayload.cin_labels_exported,
  jsonPayload.entities_exported
FROM `mizzou-news-crawler.logs`
WHERE resource.type = 'k8s_container'
  AND resource.labels.container_name = 'bigquery-export'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY timestamp DESC
```

### Kubernetes Monitoring

```bash
# Check CronJob schedule
kubectl get cronjob bigquery-export -n production -o yaml | grep schedule

# View recent job executions
kubectl get jobs -n production | grep bigquery-export

# Check for failed jobs
kubectl get jobs -n production --field-selector status.successful!=1 | \
  grep bigquery-export

# View pod logs
kubectl logs -n production -l app=bigquery-export --tail=100
```

## Querying BigQuery Data

### Example Queries

**Articles by county over time:**

```sql
SELECT
  county,
  DATE_TRUNC(published_date, MONTH) as month,
  COUNT(*) as article_count
FROM `mizzou-news-crawler.mizzou_analytics.articles`
WHERE published_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
  AND county IS NOT NULL
GROUP BY county, month
ORDER BY county, month
```

**CIN label distribution:**

```sql
SELECT
  label,
  COUNT(DISTINCT article_id) as article_count,
  AVG(confidence) as avg_confidence
FROM `mizzou-news-crawler.mizzou_analytics.cin_labels`
WHERE labeled_at >= DATE_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY label
ORDER BY article_count DESC
```

**Top entities by type:**

```sql
SELECT
  entity_type,
  entity_text,
  COUNT(*) as mention_count
FROM `mizzou-news-crawler.mizzou_analytics.entities`
WHERE extracted_at >= DATE_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY entity_type, entity_text
ORDER BY entity_type, mention_count DESC
```

**Source performance:**

```sql
SELECT
  s.name as source_name,
  s.county,
  COUNT(a.id) as article_count,
  AVG(a.word_count) as avg_word_count
FROM `mizzou-news-crawler.mizzou_analytics.articles` a
JOIN `mizzou-news-crawler.mizzou_analytics.sources` s
  ON a.source_id = s.id
WHERE a.published_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY s.name, s.county
ORDER BY article_count DESC
```

## Troubleshooting

### Export Fails with Permission Errors

**Symptom**: `403 Permission denied: BigQuery`

**Solution**: Ensure the Kubernetes service account has BigQuery Data Editor role:

```bash
gcloud projects add-iam-policy-binding mizzou-news-crawler \
  --member="serviceAccount:mizzou-app-sa@mizzou-news-crawler.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"
```

### Database Connection Timeout

**Symptom**: `psycopg2.OperationalError: could not connect`

**Solution**: Check Cloud SQL Proxy is running:

```bash
kubectl get pods -n production | grep cloudsql-proxy
kubectl logs -n production deployment/mizzou-api -c cloudsql-proxy
```

### Export Takes Too Long

**Symptom**: Job exceeds 1-hour timeout

**Solutions**:
1. Reduce `--days-back` parameter (export fewer days)
2. Increase `--batch-size` for faster processing
3. Check database query performance:

```sql
EXPLAIN ANALYZE
SELECT * FROM articles
WHERE extracted_at BETWEEN NOW() - INTERVAL '30 days' AND NOW();
```

### Duplicate Records in BigQuery

**Symptom**: Same article appears multiple times

**Solution**: BigQuery insert is append-only. Use MERGE for upserts:

```sql
MERGE `mizzou-news-crawler.mizzou_analytics.articles` T
USING staging_table S
ON T.id = S.id
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
```

## Data Retention

### BigQuery Partitioning

Articles table is partitioned by `published_date` (monthly). Configure partition expiration:

```bash
bq update --time_partitioning_expiration=15552000 \
  mizzou-news-crawler:mizzou_analytics.articles
```

This sets 180-day retention (15552000 seconds).

### Cost Optimization

BigQuery charges for:
- Storage: $0.02/GB/month (first 10 GB free)
- Queries: $5/TB processed (first 1 TB free per month)

Tips:
- Use `published_date` in WHERE clauses to scan fewer partitions
- Cluster by `county` and `source_id` for better query performance
- Monitor query costs in Cloud Console

## Maintenance

### Backfilling Historical Data

To export articles from before the CronJob was deployed:

```bash
# Export last 90 days in batches
for i in {0..12}; do
  START=$((i * 7))
  END=$(((i + 1) * 7))
  echo "Exporting days $START to $END..."
  
  kubectl exec -n production deployment/mizzou-cli -- \
    python -m src.cli.main bigquery-export --days-back $END
    
  sleep 60  # Rate limiting
done
```

### Schema Updates

If BigQuery schema changes:

1. Update `bigquery/schema.sql`
2. Add new columns with ALTER TABLE:

```bash
bq query --use_legacy_sql=false '
ALTER TABLE `mizzou-news-crawler.mizzou_analytics.articles`
ADD COLUMN new_field STRING;
'
```

3. Deploy updated export script

### Monitoring Dashboard

Create a custom dashboard for export metrics:

- Last successful export timestamp
- Articles exported per run (trend)
- Export job duration
- Error rate

See `monitoring/dashboards/pipeline-metrics.json` for configuration.

## References

- BigQuery Schema: `bigquery/schema.sql`
- Export Script: `src/pipeline/bigquery_export.py`
- CLI Command: `src/cli/commands/bigquery_export.py`
- Kubernetes CronJob: `k8s/bigquery-export-cronjob.yaml`
- Cloud SQL Migration: `API_CLOUDSQL_MIGRATION_STATUS.md`
