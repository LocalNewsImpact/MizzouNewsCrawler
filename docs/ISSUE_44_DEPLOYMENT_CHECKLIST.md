# Issue #44 Deployment Checklist

Quick reference checklist for deploying the API backend migration to production.

## Pre-Deployment (30 minutes)

### 1. Database Verification
```bash
# Connect to API pod
export API_POD=$(kubectl get pods -l app=mizzou-api -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $API_POD -- bash

# Inside pod - verify article count
python -c "
from src.models.database import DatabaseManager
from src import config
from src.models import Article
db = DatabaseManager(config.DATABASE_URL)
with db.get_session() as session:
    print(f'Articles: {session.query(Article).count()}')
    print(f'Wire articles: {sum(1 for a in session.query(Article).filter(Article.wire.isnot(None)).all() if a.wire and a.wire not in (\"null\", \"[]\", \"\"))}')
"
# Expected: Articles: 3958 (or current count)
```

- [ ] Verified database has articles (count > 0)
- [ ] Verified wire articles exist (if applicable)
- [ ] Checked database indexes exist (articles.created_at, articles.candidate_link_id)

### 2. Build New Image
```bash
cd /home/runner/work/MizzouNewsCrawler/MizzouNewsCrawler

# Get commit SHA
export SHORT_SHA=$(git rev-parse --short HEAD)
echo "Deploying commit: $SHORT_SHA"

# Trigger build
gcloud builds submit \
  --config cloudbuild-api-only.yaml \
  --substitutions=SHORT_SHA=$SHORT_SHA

# Verify build succeeded
gcloud builds list --limit=1
```

- [ ] Build completed successfully
- [ ] Image pushed to Artifact Registry
- [ ] Commit SHA recorded: ________________

### 3. Local Testing (Optional)
```bash
# Run unit tests
python -m pytest backend/tests/test_api_dashboard_endpoints.py -v -o addopts=""

# Expected: 9 tests pass
```

- [ ] All unit tests passing

## Deployment (15 minutes)

### Option A: Blue-Green (Recommended for First Time)

```bash
# 1. Create green deployment
cat > k8s/api-green-deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mizzou-api-green
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mizzou-api
      version: green
  template:
    metadata:
      labels:
        app: mizzou-api
        version: green
    spec:
      containers:
      - name: api
        image: us-central1-docker.pkg.dev/mizzou-news-crawler/images/api:$SHORT_SHA
        # ... rest of spec same as current deployment
EOF

kubectl apply -f k8s/api-green-deployment.yaml
```

- [ ] Green deployment created
- [ ] Pods are running: `kubectl get pods -l version=green`
- [ ] Pods are ready (2/2 running)

```bash
# 2. Test green deployment
kubectl port-forward svc/mizzou-api-green 8001:8000 &
curl http://localhost:8001/api/ui_overview
curl http://localhost:8001/api/articles?limit=5

# Check response
```

- [ ] Green deployment responds to health check
- [ ] `/api/ui_overview` returns non-zero article count
- [ ] `/api/articles` returns results

```bash
# 3. Switch traffic
kubectl patch service mizzou-api \
  -p '{"spec":{"selector":{"version":"green"}}}'
```

- [ ] Traffic switched to green

### Option B: Rolling Update (Faster, Less Safe)

```bash
# Update deployment
kubectl set image deployment/mizzou-api \
  api=us-central1-docker.pkg.dev/mizzou-news-crawler/images/api:$SHORT_SHA

# Monitor rollout
kubectl rollout status deployment/mizzou-api
```

- [ ] Rollout completed without errors
- [ ] All pods are ready

## Post-Deployment Validation (10 minutes)

### 1. Health Check
```bash
curl https://compute.localnewsimpact.org/health
# Expected: {"status": "healthy", "service": "api"}
```

- [ ] Health check passes

### 2. Dashboard API
```bash
curl https://compute.localnewsimpact.org/api/ui_overview
# Expected: {"total_articles": 3958, "wire_count": XX, ...}
```

- [ ] `total_articles` > 0 (not zero!)
- [ ] `wire_count` shows reasonable value
- [ ] `candidate_issues` returned
- [ ] `dedupe_near_misses` returned

### 3. Article Listing
```bash
# Test pagination
curl -s "https://compute.localnewsimpact.org/api/articles?limit=5" | jq '.count'
# Expected: 3958 (or current total)

curl -s "https://compute.localnewsimpact.org/api/articles?limit=5" | jq '.results | length'
# Expected: 5
```

- [ ] Article count matches database
- [ ] Results contain expected fields (url, title, author, etc.)
- [ ] Pagination works

### 4. Single Article
```bash
ARTICLE_ID=$(curl -s "https://compute.localnewsimpact.org/api/articles?limit=1" | jq -r '.results[0].id')
curl -s "https://compute.localnewsimpact.org/api/articles/${ARTICLE_ID}" | jq '.title'
# Expected: article title
```

- [ ] Single article lookup works
- [ ] Returns full article data

### 5. Frontend Validation
Open in browser: https://compute.localnewsimpact.org

- [ ] Dashboard loads without errors
- [ ] Article count shows 3,958 (not 0)
- [ ] Wire count shows non-zero value
- [ ] No console errors in browser DevTools

### 6. Performance Check
```bash
# Measure response time (run 10 times, check average)
for i in {1..10}; do
  curl -w "@curl-format.txt" -o /dev/null -s https://compute.localnewsimpact.org/api/ui_overview
done

# Create curl-format.txt:
cat > curl-format.txt <<EOF
time_total: %{time_total}s\n
EOF
```

- [ ] Average response time < 500ms
- [ ] No timeouts or errors

### 7. Log Check
```bash
# Check for errors in last 100 log lines
kubectl logs -l app=mizzou-api --tail=100 | grep -i error

# Check for database connection errors
kubectl logs -l app=mizzou-api --tail=100 | grep -i "database\|connection"
```

- [ ] No unexpected errors in logs
- [ ] Database connections successful

## Monitoring (First 24 Hours)

### Set Alerts
- [ ] API pod restart count (alert if > 3 in 10 min)
- [ ] Error rate (alert if > 5%)
- [ ] Response time p95 (alert if > 1000ms)

### Check Metrics
```bash
# Pod resource usage
kubectl top pods -l app=mizzou-api

# Error count in last hour
kubectl logs -l app=mizzou-api --since=1h | grep -c ERROR
```

- [ ] CPU usage < 80%
- [ ] Memory usage < 80%
- [ ] Error count < 10/hour

## Rollback Procedure (If Needed)

### Immediate Rollback
```bash
# Option A: If using blue-green
kubectl patch service mizzou-api \
  -p '{"spec":{"selector":{"version":"blue"}}}'

# Option B: If using rolling update
kubectl rollout undo deployment/mizzou-api

# Verify rollback
curl https://compute.localnewsimpact.org/api/ui_overview
```

### Symptoms That Require Rollback
- API returns 500 errors consistently
- Dashboard shows 0 articles
- Response times > 5 seconds
- Database connection pool exhausted
- Pods crash-looping

## Sign-Off

### Deployment Team
- [ ] Code deployed: ________________ (name)
- [ ] Validation passed: ________________ (name)
- [ ] Timestamp: ________________

### Approvals
- [ ] Technical lead: ________________
- [ ] Product owner: ________________

## Notes

Additional observations or issues encountered:

```
[Add notes here]
```

---

**Issue**: #44  
**Commit**: 68ed365  
**Deployment Date**: ________________  
**Rollback Count**: ________________  
