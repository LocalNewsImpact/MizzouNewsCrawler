# Cloud SQL Connector Migration Guide

This guide documents the migration from Cloud SQL Proxy sidecars to the Cloud SQL Python Connector library.

## Overview

**Problem Solved:** Cloud SQL Proxy sidecar containers never exit, causing Kubernetes Jobs to hang indefinitely in "Running" state even after the main container completes. This requires manual cleanup and wastes cluster resources.

**Solution:** Replace the proxy sidecar with the [Cloud SQL Python Connector](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector) library, which connects directly from application code.

## Benefits

✅ **Automatic Job Completion** - Jobs complete immediately when main container exits  
✅ **Resource Savings** - Frees ~89-445Mi memory and ~75-125m CPU per pod  
✅ **Simpler Configuration** - No sidecar containers in Kubernetes manifests  
✅ **Production-Grade** - Google's recommended approach for Cloud SQL connections  
✅ **Better Reliability** - Fewer moving parts, less complexity  

## Architecture Comparison

### Before (Proxy Sidecar)

```
┌─────────────────────────────────────┐
│           Kubernetes Pod            │
│                                     │
│  ┌──────────────┐  ┌─────────────┐ │
│  │     App      │  │  SQL Proxy  │ │
│  │ Container    │──│  Sidecar    │─┼─► Cloud SQL
│  │              │  │  (Port 5432)│ │
│  └──────────────┘  └─────────────┘ │
│   Exits when done   Never exits!   │
└─────────────────────────────────────┘
       ❌ Job hangs forever
```

### After (Python Connector)

```
┌─────────────────────────┐
│    Kubernetes Pod       │
│                         │
│  ┌──────────────┐       │
│  │     App      │       │
│  │ Container    │───────┼─► Cloud SQL
│  │ (w/Connector)│       │    (Direct)
│  └──────────────┘       │
│   Exits when done       │
└─────────────────────────┘
       ✅ Job completes
```

## What Changed

### 1. Python Dependencies

**Added to `requirements.txt`:**
```txt
cloud-sql-python-connector[pg8000]>=1.11.0
```

The `[pg8000]` extra includes the `pg8000` driver, which is recommended for use with the connector.

### 2. Configuration Variables

**New environment variables in `.env.example` and `src/config.py`:**

```bash
# Enable Cloud SQL Python Connector
USE_CLOUD_SQL_CONNECTOR=true

# Cloud SQL instance connection name
CLOUD_SQL_INSTANCE=project:region:instance
# Example: mizzou-news-crawler:us-central1:mizzou-db-prod

# Database credentials (same as before)
DATABASE_USER=your_db_user
DATABASE_PASSWORD=your_db_password
DATABASE_NAME=your_db_name
```

### 3. New Module: `src/models/cloud_sql_connector.py`

Created a new module that provides:
- `create_cloud_sql_engine()` - Factory for SQLAlchemy engines using the connector
- `get_connection_string_info()` - Helper to parse database URLs

### 4. Updated `src/models/database.py`

The `DatabaseManager` class now:
- Checks `USE_CLOUD_SQL_CONNECTOR` flag
- Uses Cloud SQL connector when enabled
- Falls back to traditional connections (SQLite, direct PostgreSQL) otherwise

**Backward compatible:** Existing SQLite and direct PostgreSQL connections continue to work.

### 5. Kubernetes Manifests

All three manifests updated to remove sidecar containers:

#### Before (api-deployment.yaml):
```yaml
containers:
- name: api
  env:
  - name: DATABASE_URL
    value: "postgresql://$(DB_USER):$(DB_PASSWORD)@127.0.0.1:5432/$(DB_NAME)"
  # ... more config

- name: cloud-sql-proxy  # ❌ Removed
  image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.2
  args:
    - "--port=5432"
    - "mizzou-news-crawler:us-central1:mizzou-db-prod"
```

#### After (api-deployment.yaml):
```yaml
containers:
- name: api
  env:
  - name: USE_CLOUD_SQL_CONNECTOR  # ✅ New
    value: "true"
  - name: CLOUD_SQL_INSTANCE  # ✅ New
    value: "mizzou-news-crawler:us-central1:mizzou-db-prod"
  - name: DATABASE_USER
    valueFrom:
      secretKeyRef:
        name: cloudsql-db-credentials
        key: username
  # ... other credentials
```

Same changes applied to:
- `k8s/crawler-cronjob.yaml`
- `k8s/processor-cronjob.yaml`

## Deployment Steps

### Step 1: Update Docker Images

The new dependency must be in Docker images:

```bash
# Rebuild images with updated requirements.txt
docker build -f Dockerfile.api -t api:latest .
docker build -f Dockerfile.crawler -t crawler:latest .
docker build -f Dockerfile.processor -t processor:latest .

# Push to registry
docker tag api:latest us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:latest
docker push us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:latest
# ... repeat for crawler and processor
```

### Step 2: Apply Kubernetes Manifests

```bash
# Apply updated manifests (removes sidecars, adds connector config)
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/crawler-cronjob.yaml
kubectl apply -f k8s/processor-cronjob.yaml

# Verify deployment
kubectl get pods -n production
kubectl logs -n production <pod-name> --tail=50
```

### Step 3: Test Job Completion

Create a manual crawler job to verify it completes:

```bash
# Create a test job
kubectl create job --from=cronjob/mizzou-crawler test-crawler-$(date +%s) -n production

# Watch the job - it should complete automatically
kubectl get jobs -n production -w

# Check logs
kubectl logs -n production job/test-crawler-<timestamp>

# Cleanup
kubectl delete job test-crawler-<timestamp> -n production
```

Expected behavior:
- ✅ Job status shows "Complete" 
- ✅ Pod exits after work finishes
- ✅ No manual cleanup needed

### Step 4: Verify Resource Usage

```bash
# Check resource consumption
kubectl top pods -n production

# Compare memory/CPU before and after
# Expected savings per pod: ~89-445Mi memory, ~75-125m CPU
```

## Rollback Procedure

If issues occur, rollback is straightforward:

### Option 1: Disable Connector (Quick)

Set environment variable to disable connector and fall back to proxy:

```bash
# Edit deployment/cronjob
kubectl edit deployment mizzou-api -n production

# Change:
- name: USE_CLOUD_SQL_CONNECTOR
  value: "false"  # ← Changed from "true"

# Redeploy with proxy sidecar manifest (keep a backup)
kubectl apply -f k8s-backup/api-deployment-with-proxy.yaml
```

### Option 2: Full Rollback

```bash
# Restore previous Docker images
kubectl set image deployment/mizzou-api api=api:previous-tag -n production

# Restore proxy sidecar manifests
git checkout HEAD~1 k8s/
kubectl apply -f k8s/
```

## Testing

### Local Testing (SQLite)

The connector is disabled by default for local development:

```bash
# Default behavior (SQLite)
export DATABASE_URL=sqlite:///data/mizzou.db
python -m src.cli.main status
```

### Local Testing (PostgreSQL Direct)

Test direct PostgreSQL connection without connector:

```bash
# Direct PostgreSQL (no connector)
export DATABASE_URL=postgresql://user:pass@localhost:5432/mydb
python -m src.cli.main status
```

### Testing Cloud SQL Connector

To test with Cloud SQL connector locally:

```bash
# Enable connector
export USE_CLOUD_SQL_CONNECTOR=true
export CLOUD_SQL_INSTANCE=my-project:us-central1:my-instance
export DATABASE_USER=my_user
export DATABASE_PASSWORD=my_password
export DATABASE_NAME=my_db

# Run application
python -m src.cli.main status
```

**Note:** Requires:
1. Google Cloud credentials configured (`gcloud auth application-default login`)
2. IAM permissions for Cloud SQL Client role
3. Cloud SQL Admin API enabled

## Troubleshooting

### Issue: "Module not found: google.cloud.sql.connector"

**Solution:** Install the connector dependency:
```bash
pip install cloud-sql-python-connector[pg8000]
```

### Issue: "Connection failed: IAM authentication error"

**Solution:** Ensure the service account has Cloud SQL Client role:
```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:SA_NAME@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client"
```

### Issue: "Jobs still not completing"

**Check:**
1. Connector is enabled: `USE_CLOUD_SQL_CONNECTOR=true`
2. Docker images rebuilt with new dependency
3. No other blocking containers in pod
4. Application code exits cleanly (check logs)

### Issue: "Database connection refused"

**Check:**
1. Instance name format: `project:region:instance`
2. Database credentials correct
3. Cloud SQL Admin API enabled
4. Network connectivity from GKE to Cloud SQL

## Verification Checklist

After deployment, verify:

- [ ] API pod running with single container (no sidecar)
- [ ] Crawler jobs complete automatically (not stuck in Running)
- [ ] Processor jobs complete automatically
- [ ] Database connections working (check application logs)
- [ ] No "database locked" or connection errors
- [ ] Resource usage reduced (~89-445Mi memory, ~75-125m CPU per pod)
- [ ] No manual job cleanup needed

## References

- [Cloud SQL Python Connector Documentation](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector)
- [Issue #28: Replace Cloud SQL Proxy Sidecar](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/28)
- [Google Cloud SQL Best Practices](https://cloud.google.com/sql/docs/postgres/connect-overview)

## Support

For issues or questions:
1. Check logs: `kubectl logs -n production <pod-name>`
2. Review configuration: `kubectl describe pod <pod-name> -n production`
3. Verify environment variables: `kubectl exec <pod-name> -n production -- env | grep -E 'SQL|DATABASE'`
4. Contact: infrastructure team or open GitHub issue
