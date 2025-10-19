# Datastream Migration Status

## Completed Steps ✅

### 1. Enabled Datastream API
```bash
✅ gcloud services enable datastream.googleapis.com
```

### 2. Created Replication User
```bash
✅ Created user: datastream_user
✅ Granted REPLICATION privilege
✅ Granted SELECT on all tables in public schema
✅ Granted USAGE on public schema
✅ Set default privileges for future tables
```

### 3. Enabled Logical Replication
```bash
✅ Set database flag: cloudsql.logical_decoding=on
✅ Instance is RUNNABLE
```

## Connection Details

**Cloud SQL Instance:**
- Connection Name: `mizzou-news-crawler:us-central1:mizzou-db-prod`
- Public IP: `34.61.162.107`
- Database: `mizzou_prod`
- Replication User: `datastream_user`

## Remaining Manual Steps (Google Cloud Console)

### Step 4: Create Connection Profiles

Go to: https://console.cloud.google.com/datastream/connection-profiles?project=mizzou-news-crawler

#### A. PostgreSQL Source Connection Profile

1. Click **"+ CREATE CONNECTION PROFILE"**
2. Select **PostgreSQL**
3. Fill in details:
   - **Connection profile name**: `cloudsql-postgres-source`
   - **Connection profile ID**: `cloudsql-postgres-source`
   - **Region**: `us-central1`
   
4. **Connection method**: Select **IP allowlisting** (since no private IP)
   
5. **Connectivity details**:
   - **Hostname or IP address**: `34.61.162.107`
   - **Port**: `5432`
   - **Username**: `datastream_user`
   - **Password**: (retrieve from Kubernetes secret or set new one)
   - **Database**: `mizzou_prod`
   
6. Click **CONTINUE**
7. Click **CREATE**

#### B. BigQuery Destination Connection Profile

1. Click **"+ CREATE CONNECTION PROFILE"**
2. Select **BigQuery**
3. Fill in details:
   - **Connection profile name**: `bigquery-mizzou-analytics`
   - **Connection profile ID**: `bigquery-mizzou-analytics`
   - **Region**: `us-central1`
   
4. Click **CREATE**

### Step 5: Create Datastream Stream

Go to: https://console.cloud.google.com/datastream/streams?project=mizzou-news-crawler

1. Click **"+ CREATE STREAM"**
2. **Stream details**:
   - **Stream name**: `cloudsql-to-bigquery`
   - **Stream ID**: `cloudsql-to-bigquery`
   - **Region**: `us-central1`

3. **Source configuration**:
   - **Connection profile**: Select `cloudsql-postgres-source`
   - **Configure source**: Click **CONTINUE**
   - **Select objects**: Choose the following tables:
     - ☑ `articles`
     - ☑ `article_labels`
     - ☑ `article_entities`
     - ☑ `candidate_links`
     - ☑ `sources`
     - ☑ `source_metadata`
   - Click **CONTINUE**

4. **Destination configuration**:
   - **Connection profile**: Select `bigquery-mizzou-analytics`
   - **Dataset**: `mizzou_analytics`
   - **Table name prefix**: (leave empty)
   - **Stale data deletion**: `Disabled` (recommended)
   - Click **CONTINUE**

5. **Stream configuration**:
   - **Backfill mode**: `Automatic` (copies existing data first)
   - **Stream start behavior**: `Start immediately`
   - Click **CREATE & START**

### Step 6: Monitor Initial Backfill

The stream will start backfilling historical data:
- Expected backfill time: 5-15 minutes for ~6,000 articles
- Monitor at: https://console.cloud.google.com/datastream/streams/locations/us-central1/streams/cloudsql-to-bigquery?project=mizzou-news-crawler

### Step 7: Verify Data in BigQuery

Once backfill completes, verify data:

```bash
# Check article count
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) as total FROM `mizzou-news-crawler.mizzou_analytics.articles`'

# Check labels
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) as total FROM `mizzou-news-crawler.mizzou_analytics.article_labels`'

# Check entities
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) as total FROM `mizzou-news-crawler.mizzou_analytics.article_entities`'
```

### Step 8: Delete Old Export CronJob

Once Datastream is working and verified:

```bash
kubectl delete cronjob bigquery-export -n production
```

## Getting the Datastream User Password

If you need to retrieve the password for the datastream_user:

```bash
# Option 1: Reset password
gcloud sql users set-password datastream_user \
  --instance=mizzou-db-prod \
  --password=YOUR_NEW_SECURE_PASSWORD

# Option 2: Use Cloud SQL Auth Proxy (recommended)
# Datastream can use Cloud SQL Auth Proxy instead of password
```

## Benefits After Migration

✅ **Real-time replication** - Changes appear in BigQuery within seconds  
✅ **All tables synced** - No more batch size limits or partial exports  
✅ **Automatic schema changes** - No code updates needed  
✅ **Zero maintenance** - Managed service with built-in monitoring  
✅ **No 413 errors** - Handles data of any size  

## Estimated Cost

- **Backfill**: ~$0.20 per GB (one-time, ~$1-3 for initial data)
- **Ongoing CDC**: ~$0.10 per GB/month (~$1-5/month for new data)
- **Total**: ~$5-10/month for continuous real-time replication

---

**Next Action**: Complete Steps 4-7 in the Google Cloud Console using the links above.
