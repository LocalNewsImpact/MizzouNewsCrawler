# Datastream Setup Blocked - Simpler Alternative Recommended

## Issue Encountered

Datastream connection to Cloud SQL failed with:
```
CONNECTION_TIMEOUT: We timed out trying to connect to the data source
```

**Root Cause:** Cloud SQL instance only has a public IP, and Datastream requires either:
1. Private IP connectivity (requires VPC setup)
2. Allowlisting Datastream's IP ranges (complex, region-specific)

## Recommended Alternative: BigQuery Data Transfer Service

Instead of Datastream (which is overkill for batch analytics), use **BigQuery Data Transfer Service** which:
- ✅ Works with public Cloud SQL IPs
- ✅ No VPC configuration needed
- ✅ Scheduled queries/imports
- ✅ Simpler to set up
- ❌ Not real-time (but we don't need real-time for analytics)

### Setup (5 minutes)

1. **Enable the API:**
```bash
gcloud services enable bigquerydatatransfer.googleapis.com
```

2. **Create scheduled query in BigQuery Console:**
   - Go to: https://console.cloud.google.com/bigquery/scheduled-queries?project=mizzou-news-crawler
   - Click "CREATE TRANSFER"
   - Choose "Scheduled query"
   - Set schedule (e.g., daily at 2 AM)
   - Query: `SELECT * FROM EXTERNAL_QUERY(...)`

3. **Use Federated Queries** to read from Cloud SQL directly:
```sql
SELECT * FROM EXTERNAL_QUERY(
  "projects/mizzou-news-crawler/locations/us-central1/connections/cloudsql",
  "SELECT * FROM articles WHERE extracted_at > CURRENT_DATE - INTERVAL '7 days';"
)
```

## Even Simpler Option: Keep Manual Export with Improvements

Since we already have the manual export working, we could:
1. **Fix the batch looping** for labels/entities (already identified the issue)
2. **Run it daily** (already have cronjob)
3. **Add deduplication** (already implemented)

This is actually fine for analytics use cases where:
- Real-time sync isn't critical
- Data is small (~6K articles)
- Daily updates are sufficient

### Current Status
- ✅ Manual export works and deduplicates properly
- ✅ Exports 5,940 articles successfully
- ⚠️ Only exports 100 labels/entities (needs fixing)

## Decision Point

**Option A: Fix Manual Export (Recommended for now)**
- Pros: Already working, simple, sufficient for analytics
- Cons: Not real-time, manual code to maintain
- Time: 30 minutes to fix labels/entities looping

**Option B: BigQuery Data Transfer**
- Pros: Managed service, scheduled automatically
- Cons: Still requires configuration, not real-time
- Time: 1-2 hours to set up federated queries

**Option C: Datastream (Not Recommended)**
- Pros: Real-time CDC, fully managed
- Cons: Requires VPC setup, complex networking, expensive for small dataset
- Time: 3-4 hours for VPC + private connectivity setup

## Recommendation

**Keep the manual export** for now since:
1. It works (5,940 articles exported successfully)
2. Daily sync is sufficient for analytics
3. Simple and maintainable
4. Just needs labels/entities batch looping fixed

Once data volume grows or real-time becomes critical, revisit Datastream with proper VPC setup.

---

**Next Action:** Should I:
1. Fix the labels/entities batch looping in the export?
2. Set up BigQuery Data Transfer with federated queries?
3. Configure VPC for Datastream (3-4 hour effort)?
