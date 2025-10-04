# API Backend Cloud SQL Migration Guide

This guide documents the migration of the API backend from SQLite to Cloud SQL (PostgreSQL), following [Issue #30](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/30).

## Overview

### Problem
The API backend (`backend/app/main.py`) was using SQLite databases instead of Cloud SQL, causing:
- Data loss on pod restarts (ephemeral storage)
- Unable to scale to multiple replicas
- Data inconsistency between crawler/processor (Cloud SQL) and API (SQLite)
- Missing telemetry features in deployed API

### Solution
Migrate all API backend tables to Cloud SQL using SQLAlchemy ORM and DatabaseManager, ensuring:
- Single source of truth in Cloud SQL
- Data persistence across pod restarts
- Ability to scale API replicas
- All telemetry features available

## Migration Components

### 1. New SQLAlchemy Models

Created in `src/models/api_backend.py`:

- **Review** - Article review data from human reviewers
- **DomainFeedback** - Domain/host-level feedback notes
- **Snapshot** - HTML snapshots for extraction review
- **Candidate** - Candidate selectors for field extraction
- **ReextractionJob** - Re-extraction job tracking
- **DedupeAudit** - Deduplication audit trail
- **BylineCleaningTelemetry** - Byline cleaning telemetry
- **BylineTransformationStep** - Individual byline transformation steps
- **CodeReviewTelemetry** - Code review items and feedback

Updated `src/models/verification.py`:
- Added human feedback fields to **URLVerification** model

### 2. Alembic Migrations

**Configuration:**
- `alembic.ini` - Configured to use DATABASE_URL from config
- `alembic/env.py` - Set up to import models and use Base.metadata

**Migration:**
- `alembic/versions/e3114395bcc4_add_api_backend_and_telemetry_tables.py`
  - Creates all API backend tables
  - Creates all telemetry tables
  - Includes proper indexes and constraints

### 3. Telemetry API Modules

Created in `backend/app/telemetry/`:

- **verification.py** - URL verification telemetry using DatabaseManager
  - `get_pending_verification_reviews()`
  - `submit_verification_feedback()`
  - `get_verification_telemetry_stats()`
  - `enhance_verification_with_content()`
  - `get_labeled_verification_training_data()`

- **byline.py** - Byline cleaning telemetry using DatabaseManager
  - `get_pending_byline_reviews()`
  - `submit_byline_feedback()`
  - `get_byline_telemetry_stats()`
  - `get_labeled_training_data()`

- **code_review.py** - Code review telemetry using DatabaseManager
  - `get_pending_code_reviews()`
  - `submit_code_review_feedback()`
  - `get_code_review_stats()`
  - `add_code_review_item()`

All modules use:
- DatabaseManager context manager for connections
- SQLAlchemy ORM queries (no raw SQL)
- Proper error handling and transaction management

## Deployment Steps

### Prerequisites

1. **Cloud SQL instance running** with proper credentials
2. **Cloud SQL Python Connector** installed (in requirements.txt)
3. **Kubernetes cluster** with proper RBAC permissions

### Step 1: Backup Existing Data (If Any)

```bash
# Backup SQLite databases from running pod (if data exists)
kubectl cp production/mizzou-api-xxx:/app/backend/reviews.db ./backup/reviews.db
kubectl cp production/mizzou-api-xxx:/app/data/mizzou.db ./backup/mizzou.db
```

### Step 2: Run Migrations

Option A - Using kubectl exec on API pod:
```bash
kubectl exec -it deployment/mizzou-api -n production -- \
  python -m alembic upgrade head
```

Option B - Using temporary pod:
```bash
kubectl run -it --rm alembic-migrate \
  --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:v1.3.0 \
  --restart=Never \
  --env="USE_CLOUD_SQL_CONNECTOR=true" \
  --env="CLOUD_SQL_INSTANCE=mizzou-news-crawler:us-central1:mizzou-db-prod" \
  --env="DATABASE_USER=..." \
  --env="DATABASE_PASSWORD=..." \
  --env="DATABASE_NAME=mizzou" \
  -n production \
  -- python -m alembic upgrade head
```

### Step 3: Verify Tables Created

Connect to Cloud SQL and verify tables:

```sql
-- Check tables exist
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name IN (
    'reviews', 'domain_feedback', 'snapshots', 'candidates',
    'reextract_jobs', 'dedupe_audit', 'byline_cleaning_telemetry',
    'code_review_telemetry', 'url_verifications'
  );

-- Check review table structure
\d reviews

-- Check indexes
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename IN ('reviews', 'snapshots', 'byline_cleaning_telemetry');
```

### Step 4: Deploy Updated API

Build and deploy new API image:

```bash
# Build v1.3.0 with Cloud SQL support
gcloud builds submit --config=cloudbuild-api.yaml --substitutions=TAG_NAME=v1.3.0

# Update deployment
kubectl set image deployment/mizzou-api \
  api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:v1.3.0 \
  -n production

# Watch rollout
kubectl rollout status deployment/mizzou-api -n production
```

### Step 5: Verify Endpoints

```bash
API_IP=$(kubectl get svc mizzou-api -n production -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Test basic endpoints
curl http://$API_IP/api/articles
curl http://$API_IP/api/reviews

# Test telemetry endpoints
curl http://$API_IP/api/verification_telemetry/stats
curl http://$API_IP/api/byline_telemetry/stats
curl http://$API_IP/api/code_review_telemetry/stats
```

### Step 6: Monitor Logs

```bash
# Check for database connection logs
kubectl logs -f deployment/mizzou-api -n production | grep -i "database\|connection\|sql"

# Check for errors
kubectl logs deployment/mizzou-api -n production --tail=100 | grep -i "error\|exception"
```

## Rollback Procedure

If issues occur during deployment:

### 1. Immediate Rollback

```bash
# Roll back to previous version
kubectl rollout undo deployment/mizzou-api -n production

# Or explicitly roll back to specific version
kubectl set image deployment/mizzou-api \
  api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:v1.2.0 \
  -n production
```

### 2. Database Rollback (If Needed)

If migrations need to be rolled back:

```bash
# Check current migration version
kubectl exec -it deployment/mizzou-api -n production -- \
  python -m alembic current

# Downgrade to previous version
kubectl exec -it deployment/mizzou-api -n production -- \
  python -m alembic downgrade -1

# Or downgrade to specific version
kubectl exec -it deployment/mizzou-api -n production -- \
  python -m alembic downgrade <revision>
```

### 3. Data Restoration

If SQLite data needs to be restored:

```bash
# Copy backup to pod
kubectl cp ./backup/reviews.db production/mizzou-api-xxx:/app/backend/reviews.db
```

## Testing Guide

### Local Testing with PostgreSQL

1. **Start local PostgreSQL:**
   ```bash
   docker run --name postgres-test -e POSTGRES_PASSWORD=testpass -e POSTGRES_DB=mizzou_test -p 5432:5432 -d postgres:15
   ```

2. **Set environment variables:**
   ```bash
   export USE_CLOUD_SQL_CONNECTOR=false
   export DATABASE_URL=postgresql://postgres:testpass@localhost:5432/mizzou_test
   ```

3. **Run migrations:**
   ```bash
   python -m alembic upgrade head
   ```

4. **Start API:**
   ```bash
   python -m uvicorn backend.app.main:app --reload --port 8000
   ```

5. **Test endpoints:**
   ```bash
   curl http://localhost:8000/api/articles
   curl http://localhost:8000/api/verification_telemetry/stats
   ```

### Integration Testing

Run the API integration tests:

```bash
pytest backend/tests/ -v
```

## Architecture Changes

### Before Migration

```
┌─────────────────┐
│   API Pod       │
│                 │
│  ┌───────────┐  │
│  │ main.py   │  │
│  │  (SQLite) │  │
│  └─────┬─────┘  │
│        │        │
│   ┌────▼─────┐  │
│   │reviews.db│  │ (ephemeral)
│   │mizzou.db │  │ (lost on restart)
│   └──────────┘  │
└─────────────────┘

┌─────────────────┐
│ Crawler/Proc    │
│                 │
│  ┌───────────┐  │
│  │ CLI       │  │
│  │(Cloud SQL)│  │
│  └─────┬─────┘  │
└────────┼────────┘
         │
    ┌────▼────┐
    │Cloud SQL│ (persistent)
    │(Postgres)│
    └─────────┘
```

### After Migration

```
┌─────────────────┐      ┌─────────────────┐
│   API Pod       │      │ Crawler/Proc    │
│                 │      │                 │
│  ┌───────────┐  │      │  ┌───────────┐  │
│  │ main.py   │  │      │  │ CLI       │  │
│  │(Cloud SQL)│  │      │  │(Cloud SQL)│  │
│  └─────┬─────┘  │      │  └─────┬─────┘  │
└────────┼────────┘      └────────┼────────┘
         │                        │
         └────────┬───────────────┘
                  │
             ┌────▼────┐
             │Cloud SQL│ (persistent)
             │(Postgres)│ (single source of truth)
             └─────────┘
```

## Benefits

1. **✅ Data Persistence** - Data survives pod restarts
2. **✅ Scalability** - Can run multiple API replicas
3. **✅ Consistency** - Single source of truth for all data
4. **✅ Feature Complete** - All telemetry dashboards work
5. **✅ Operational Simplicity** - One database to manage

## Monitoring

### Key Metrics to Watch

1. **Database Connection Pool**
   - Active connections
   - Connection wait time
   - Connection errors

2. **Query Performance**
   - Average query time
   - Slow query count
   - Query errors

3. **API Performance**
   - Response times
   - Error rates
   - Request volume

### Troubleshooting

**Problem: Connection timeouts**
- Check Cloud SQL connector is enabled: `USE_CLOUD_SQL_CONNECTOR=true`
- Verify Cloud SQL instance is running and accessible
- Check credentials are correct

**Problem: Slow queries**
- Review query execution plans
- Check indexes are created (from migration)
- Monitor Cloud SQL performance insights

**Problem: Data not appearing**
- Verify migrations ran successfully
- Check database connection is to correct instance
- Review API logs for errors

## Additional Resources

- [Cloud SQL Python Connector Docs](https://cloud.google.com/sql/docs/postgres/connect-instance-cloud-sql-python-connector)
- [SQLAlchemy ORM Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Issue #30 - API Migration Plan](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/30)
- [Issue #28 - Cloud SQL Connector Implementation](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/28)
