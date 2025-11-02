# Deployment Plan: PR #136 - Telemetry Database Resolution Fix

## Executive Summary

**PR**: #136 - Fix telemetry default database resolution  
**Risk Level**: Low  
**Deployment Type**: Code change only (no schema changes)  
**Downtime Required**: None  
**Rollback Complexity**: Simple (revert commit)

This deployment fixes a critical bug where telemetry data was being written to local SQLite instead of production Cloud SQL database, causing data loss and inconsistent system state.

## Pre-Deployment Checklist

### 1. Code Review ✓
- [x] PR #136 reviewed and approved
- [x] All tests pass (17 new tests added)
- [x] No breaking changes identified
- [x] Backward compatibility verified

### 2. Database Preparation
- [ ] Verify Cloud SQL instance is running
- [ ] Verify telemetry tables exist in Cloud SQL:
  ```sql
  SELECT table_name 
  FROM information_schema.tables 
  WHERE table_schema = 'public' 
  AND (table_name LIKE '%telemetry%' 
       OR table_name IN ('operations', 'discovery_http_status_tracking', 'discovery_method_effectiveness'));
  ```
- [ ] If tables missing, run migrations:
  ```bash
  alembic upgrade head
  ```

### 3. Environment Configuration
- [ ] Verify `DATABASE_URL` is configured in production environment
- [ ] Verify `USE_CLOUD_SQL_CONNECTOR=true` (if using Cloud SQL Connector)
- [ ] Document current telemetry data location (for comparison)

### 4. Monitoring Setup
- [ ] Ensure Cloud SQL monitoring is active
- [ ] Set up queries to track telemetry data ingestion
- [ ] Prepare rollback command in advance

## Deployment Steps

### Step 1: Pre-Deployment Verification (5 minutes)

```bash
# Connect to production environment
kubectl get pods -n production

# Check current database configuration
kubectl exec -it <crawler-pod> -- env | grep DATABASE

# Verify current telemetry behavior (should be writing to SQLite)
kubectl exec -it <crawler-pod> -- ls -lh /data/mizzou.db
```

### Step 2: Merge and Deploy (10 minutes)

1. **Merge PR #136** to main branch:
   ```bash
   git checkout main
   git pull origin main
   # Verify commit is present
   git log --oneline -5 | grep "Fix telemetry"
   ```

2. **Trigger CI/CD Pipeline**:
   - CI will build new Docker images
   - CD will deploy to staging first (if configured)

3. **Monitor Build**:
   ```bash
   # Watch Cloud Build
   gcloud builds list --limit=1

   # Or monitor via GitHub Actions
   # Check workflow status at: 
   # https://github.com/LocalNewsImpact/MizzouNewsCrawler/actions
   ```

### Step 3: Staging Verification (15 minutes)

**If staging environment exists:**

1. **Verify deployment**:
   ```bash
   kubectl get pods -n staging
   kubectl logs -f <staging-crawler-pod> --tail=100
   ```

2. **Test telemetry writes**:
   ```bash
   # Trigger a discovery run
   kubectl exec -it <staging-crawler-pod> -- python -m src.cli.commands.discovery --limit 1
   
   # Verify telemetry data in Cloud SQL
   # Connect to Cloud SQL and check:
   ```
   ```sql
   SELECT COUNT(*), MAX(created_at) 
   FROM operations 
   WHERE operation_type = 'crawl_discovery'
   AND created_at > NOW() - INTERVAL '10 minutes';
   ```

3. **Verify no SQLite writes**:
   ```bash
   # SQLite file should not grow (or may not exist)
   kubectl exec -it <staging-crawler-pod> -- ls -lh /data/ 2>/dev/null || echo "No local data directory"
   ```

### Step 4: Production Deployment (10 minutes)

1. **Deploy to production**:
   ```bash
   # If using kubectl
   kubectl set image deployment/crawler \
     crawler=gcr.io/project/mizzou-crawler:latest \
     -n production

   # Or trigger CD pipeline
   # Or use skaffold/helm deployment
   ```

2. **Monitor pod rollout**:
   ```bash
   kubectl rollout status deployment/crawler -n production
   kubectl get pods -n production -w
   ```

3. **Check pod logs**:
   ```bash
   kubectl logs -f <new-crawler-pod> --tail=50
   # Look for: "NewsDiscovery initialized with..."
   # Should show Cloud SQL URL, not SQLite
   ```

### Step 5: Post-Deployment Verification (20 minutes)

#### 5.1 Verify Telemetry Data Flow

```sql
-- Connect to Cloud SQL production database

-- Check recent telemetry data (should start appearing immediately)
SELECT 
    COUNT(*) as total_operations,
    MAX(created_at) as latest_operation,
    operation_type
FROM operations
WHERE created_at > NOW() - INTERVAL '30 minutes'
GROUP BY operation_type
ORDER BY latest_operation DESC;

-- Check HTTP status tracking
SELECT 
    COUNT(*) as total_requests,
    MAX(timestamp) as latest_request
FROM discovery_http_status_tracking
WHERE timestamp > NOW() - INTERVAL '30 minutes';

-- Check method effectiveness tracking
SELECT 
    COUNT(*) as total_methods,
    MAX(last_attempt) as latest_attempt
FROM discovery_method_effectiveness
WHERE last_attempt > NOW() - INTERVAL '30 minutes';
```

#### 5.2 Verify No Regressions

```bash
# Run a full discovery cycle
kubectl exec -it <crawler-pod> -n production -- \
  python -m src.cli.commands.discovery --limit 5

# Check for errors in logs
kubectl logs <crawler-pod> -n production --tail=200 | grep -i error

# Verify candidate links are being created
```

```sql
SELECT COUNT(*), MAX(discovered_at)
FROM candidate_links
WHERE discovered_at > NOW() - INTERVAL '1 hour';
```

#### 5.3 Verify Database URL Resolution

```bash
# Check environment inside pod
kubectl exec -it <crawler-pod> -n production -- python -c "
from src.config import DATABASE_URL
print(f'DATABASE_URL: {DATABASE_URL}')
"

# Should output Cloud SQL URL, not SQLite
```

### Step 6: Monitoring Setup (Ongoing)

Set up alerts for:

1. **Telemetry data ingestion rate**:
   ```sql
   -- Should be > 0 when discovery is running
   SELECT COUNT(*) FROM operations 
   WHERE created_at > NOW() - INTERVAL '5 minutes';
   ```

2. **Cloud SQL connection errors**:
   ```bash
   # Monitor pod logs
   kubectl logs -f <crawler-pod> -n production | grep -i "telemetry\|database"
   ```

3. **Disk usage** (should NOT grow on crawler pods):
   ```bash
   kubectl exec -it <crawler-pod> -n production -- df -h /data
   ```

## Rollback Procedure

If issues are detected, rollback is straightforward:

### Quick Rollback (5 minutes)

```bash
# Option 1: Revert to previous deployment
kubectl rollout undo deployment/crawler -n production

# Option 2: Deploy specific previous version
kubectl set image deployment/crawler \
  crawler=gcr.io/project/mizzou-crawler:v1.2.3 \
  -n production

# Verify rollback
kubectl rollout status deployment/crawler -n production
```

### Rollback Verification

```bash
# Check that pods are running previous version
kubectl get pods -n production -o jsonpath='{.items[*].spec.containers[*].image}'

# Verify system is stable
kubectl logs <crawler-pod> -n production --tail=50
```

### Data Recovery

- No data loss should occur during rollback
- Telemetry data written to Cloud SQL during deployment remains accessible
- After rollback, telemetry will resume writing to SQLite (previous behavior)

## Success Criteria

The deployment is considered successful when:

- ✅ All pods are running and healthy
- ✅ Telemetry data appears in Cloud SQL `operations` table
- ✅ Discovery operations complete without errors
- ✅ Candidate links are being created normally
- ✅ No SQLite file growth on crawler pods
- ✅ No increase in error rates
- ✅ Cloud SQL connection pool is stable

## Failure Scenarios and Responses

### Scenario 1: Cloud SQL Connection Failures

**Symptoms**: 
- Error logs: "Cannot connect to Cloud SQL"
- Telemetry errors in logs
- Discovery may still work (separate connection)

**Response**:
1. Check Cloud SQL instance status
2. Verify `USE_CLOUD_SQL_CONNECTOR` and connection settings
3. Check service account permissions
4. If unresolvable, execute rollback

### Scenario 2: Telemetry Data Not Appearing

**Symptoms**:
- No new rows in `operations` table
- Logs show SQLite path in database URL

**Response**:
1. Verify `DATABASE_URL` environment variable in pod
2. Check `src.config.DATABASE_URL` value:
   ```bash
   kubectl exec -it <pod> -- python -c "from src.config import DATABASE_URL; print(DATABASE_URL)"
   ```
3. Verify telemetry tables exist
4. Check pod logs for telemetry errors

### Scenario 3: Discovery Failures

**Symptoms**:
- Discovery pipeline fails
- No candidate links created

**Response**:
1. This is likely unrelated to PR #136 (telemetry is non-blocking)
2. Check broader system issues
3. If in doubt, rollback and investigate separately

## Post-Deployment Tasks

### Immediate (Day 1)

- [ ] Monitor telemetry data ingestion for 24 hours
- [ ] Verify data quality in Cloud SQL
- [ ] Compare telemetry data volume to expectations
- [ ] Update runbooks with new telemetry data location

### Short-term (Week 1)

- [ ] Analyze historical telemetry data gaps (from when SQLite was used)
- [ ] Set up dashboards for telemetry data
- [ ] Document new telemetry query patterns
- [ ] Archive any SQLite telemetry data from pods

### Long-term (Month 1)

- [ ] Review telemetry data retention policies
- [ ] Optimize telemetry table indices if needed
- [ ] Update documentation with production telemetry patterns
- [ ] Consider telemetry data export to BigQuery for analytics

## Communication Plan

### Pre-Deployment

**Audience**: Engineering team, DevOps  
**Message**: "Deploying fix for telemetry database resolution (PR #136). Low risk, no downtime expected. Telemetry will start writing to Cloud SQL instead of local SQLite."

### During Deployment

**Audience**: Engineering team  
**Channel**: Slack #deployments  
**Updates**:
- Deployment started
- Staging verification complete
- Production deployment in progress
- Verification complete

### Post-Deployment

**Audience**: All stakeholders  
**Message**: "PR #136 deployed successfully. Telemetry data now persisting to Cloud SQL. Monitor dashboards available at [link]."

## Contacts

- **Deployment Lead**: [Name]
- **Code Owner**: @dkiesow
- **DevOps On-Call**: [Name]
- **Database Admin**: [Name]

## Timeline Estimate

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Pre-deployment checks | 5 min | 5 min |
| Merge and build | 10 min | 15 min |
| Staging verification | 15 min | 30 min |
| Production deployment | 10 min | 40 min |
| Post-deployment verification | 20 min | 60 min |
| **Total** | **60 min** | **1 hour** |

*Note: Monitoring continues for 24 hours post-deployment*

## Sign-off

- [ ] Code reviewed and approved
- [ ] Tests passing
- [ ] Deployment plan reviewed
- [ ] Rollback procedure tested
- [ ] Monitoring configured
- [ ] Communication plan ready

**Approved by**: ________________  
**Date**: ________________
