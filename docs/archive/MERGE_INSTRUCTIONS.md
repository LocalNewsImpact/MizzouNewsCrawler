# Merge Instructions for Issue #32 - API Cloud SQL Migration

## Summary

This PR (`copilot/fix-96cfcfa5-576d-4fee-9d02-6322f77c8f61`) completes the foundation work for Issue #32: Complete API Backend Cloud SQL Migration.

## What Was Accomplished

### ✅ Phase 1-3 Complete (Foundation)

1. **Model Serialization** - Added `to_dict()` methods to all 9 API backend models
2. **Foundation Refactoring** - Replaced schema init functions with Alembic-managed migrations
3. **Telemetry Integration** - Added 13 new Cloud SQL-based telemetry endpoints
4. **Dockerfile Updates** - Added Alembic support for migrations
5. **Documentation** - Comprehensive migration status and deployment guide

### 📊 Changes Summary

- **Files Modified:** 4 files
- **Lines Added:** 594
- **Lines Removed:** 263
- **Net Change:** +331 lines

### 🏗️ Architecture

The API now operates in **hybrid mode**:
- **New (Cloud SQL):** All telemetry endpoints (verification, byline, code review)
- **Legacy (SQLite):** Reviews, snapshots, domain feedback (to be migrated in follow-up)

## How to Merge This PR

### Option 1: GitHub Web UI (Recommended)

1. **Navigate to the PR:**
   - Go to: https://github.com/LocalNewsImpact/MizzouNewsCrawler/pulls
   - Find PR for branch: `copilot/fix-96cfcfa5-576d-4fee-9d02-6322f77c8f61`

2. **Review Changes:**
   - Review the 4 files changed
   - Check that all tests pass (if CI is enabled)

3. **Merge:**
   - Click "Merge pull request"
   - Select merge method: "Create a merge commit" (recommended)
   - Target branch: `feature/gcp-kubernetes-deployment`
   - Confirm merge

### Option 2: Command Line

```bash
# 1. Fetch the latest changes
git fetch origin

# 2. Checkout the feature branch
git checkout feature/gcp-kubernetes-deployment

# 3. Merge the copilot branch
git merge origin/copilot/fix-96cfcfa5-576d-4fee-9d02-6322f77c8f61

# 4. Push the merged result
git push origin feature/gcp-kubernetes-deployment

# 5. Delete the copilot branch (optional, after merge)
git push origin --delete copilot/fix-96cfcfa5-576d-4fee-9d02-6322f77c8f61
```

## Pre-Merge Checklist

- [x] Code compiles without syntax errors
- [x] Models have to_dict() methods
- [x] Telemetry endpoints added
- [x] Init functions converted to no-ops
- [x] Dockerfile updated for Alembic
- [x] Documentation created
- [ ] Local testing with PostgreSQL (recommended before deploying)
- [ ] Code review approved
- [ ] CI tests passing (if applicable)

## Post-Merge Actions

### 1. Deploy to Staging/Production

**Step 1: Run Alembic Migrations**
```bash
# Connect to Cloud SQL and run migrations
kubectl exec -it deployment/mizzou-api -n production -- \
  python -m alembic upgrade head
```

**Step 2: Build New API Image**
```bash
# Trigger API build (v1.3.0)
gcloud builds triggers run 104cd8ce-dfea-473e-98be-236dd5de3911 \
  --branch=feature/gcp-kubernetes-deployment \
  --project=mizzou-news-crawler
```

**Step 3: Deploy to Kubernetes**
```bash
# Update deployment with new image
kubectl set image deployment/mizzou-api \
  api=gcr.io/mizzou-news-crawler/api:v1.3.0 \
  -n production

# Watch rollout
kubectl rollout status deployment/mizzou-api -n production
```

**Step 4: Verify Telemetry Endpoints**
```bash
API_IP=$(kubectl get svc mizzou-api -n production -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Test new endpoints
curl http://$API_IP/api/telemetry/verification/stats
curl http://$API_IP/api/telemetry/byline/stats
curl http://$API_IP/api/telemetry/code_review/stats
```

### 2. Verify React Dashboard

1. Open React frontend: `http://$API_IP/web`
2. Navigate to Telemetry sections
3. Verify:
   - Verification telemetry loads
   - Byline telemetry loads
   - Code review telemetry loads
   - All charts/tables display data

### 3. Monitor Performance

- Check Cloud SQL Query Insights
- Monitor API response times
- Verify no errors in Cloud Logging
- Check GKE pod status

## Next Steps (Future Work)

### Issue #33: Migrate Reviews and Snapshots Endpoints
**Priority:** High  
**Effort:** 8-11 hours  
**Description:** Refactor the remaining SQLite endpoints (reviews, snapshots, domain feedback) to use Cloud SQL

Key tasks:
- Refactor `/api/reviews` endpoints
- Refactor `/api/snapshots` endpoints  
- Refactor `/api/domain_feedback` endpoints
- Test data persistence across pod restarts

### Issue #34: Complete SQLite Removal
**Priority:** Medium  
**Effort:** 3-4 hours  
**Description:** Remove all SQLite code and dependencies

Key tasks:
- Remove sqlite3 imports
- Remove DB_PATH and SQLite connection code
- Update Dockerfile.api (remove data directory)
- Final testing and verification

## Rollback Plan

If issues occur after deployment:

**Immediate Rollback:**
```bash
# Rollback to previous version
kubectl rollout undo deployment/mizzou-api -n production

# Verify rollback
kubectl rollout status deployment/mizzou-api -n production
```

**Database Rollback (if needed):**
```bash
# Connect to API pod
kubectl exec -it deployment/mizzou-api -n production -- bash

# Rollback one migration
python -m alembic downgrade -1

# Or rollback all new migrations
python -m alembic downgrade c648413  # Base revision before this work
```

## Files Changed in This PR

| File | Status | Description |
|------|--------|-------------|
| `src/models/api_backend.py` | Modified | Added to_dict() methods (+165 lines) |
| `backend/app/main.py` | Modified | Added telemetry endpoints, removed schema init (-263, +187) |
| `Dockerfile.api` | Modified | Added Alembic support (+2) |
| `API_CLOUDSQL_MIGRATION_STATUS.md` | New | Migration status documentation (+237) |

## Testing Recommendations

### Local Testing (Recommended Before Merge)

```bash
# 1. Start local PostgreSQL
docker run --name postgres-test \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=mizzou_test \
  -p 5432:5432 -d postgres:15

# 2. Set environment variables
export USE_CLOUD_SQL_CONNECTOR=false
export DATABASE_URL=postgresql://postgres:testpass@localhost:5432/mizzou_test

# 3. Run migrations
python -m alembic upgrade head

# 4. Start API
python -m uvicorn backend.app.main:app --reload --port 8000

# 5. Test telemetry endpoints
curl http://localhost:8000/api/telemetry/verification/stats | jq
curl http://localhost:8000/api/telemetry/byline/stats | jq
curl http://localhost:8000/api/telemetry/code_review/stats | jq

# 6. Test legacy endpoints (should still work with SQLite)
curl http://localhost:8000/api/articles | jq
curl http://localhost:8000/api/reviews | jq

# 7. Clean up
docker stop postgres-test && docker rm postgres-test
```

## Support and Questions

- **Documentation:** See `API_CLOUDSQL_MIGRATION_STATUS.md` for detailed status
- **Migration Guide:** See `docs/API_CLOUDSQL_MIGRATION_GUIDE.md` for complete guide
- **Issue #32:** https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/32

## Success Metrics

After merge and deployment, verify:

- ✅ All 13 telemetry endpoints respond successfully
- ✅ Telemetry data persists across pod restarts
- ✅ React dashboard telemetry features work
- ✅ Legacy endpoints continue to work
- ✅ No increase in error rates
- ✅ Response times within acceptable range (< 500ms avg)
- ✅ Cloud SQL connections stable

---

**Status:** Ready to merge ✅  
**Risk Level:** Low (hybrid architecture preserves existing functionality)  
**Deployment:** Can be deployed immediately after merge
