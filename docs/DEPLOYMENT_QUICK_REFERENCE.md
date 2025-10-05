# Deployment Quick Reference

## Individual Service Deployment

### Automatic (Main Branch Only)

**Smart Path-Based Triggers** - Only modified services rebuild:

| You Changed | What Rebuilds | What Stays Same |
|-------------|---------------|-----------------|
| `backend/app/routers/articles.py` | ✅ API only | ✅ Processor, Crawler |
| `orchestration/continuous_processor.py` | ✅ Processor only | ✅ API, Crawler |
| `src/extraction/extractor.py` | ✅ Processor, Crawler | ✅ API |
| `requirements.txt` | ⚠️ All three | ❌ None |
| `Dockerfile.api` | ✅ API only | ✅ Processor, Crawler |

**Setup:**

```bash
./scripts/setup-triggers.sh
# Answer "y" to enable path-based filtering
```

### Manual (Feature Branches)

Deploy one service at a time:

```bash
# Processor only
./scripts/deploy.sh processor v1.2.3 --auto-deploy

# API only
./scripts/deploy.sh api v1.3.2 --auto-deploy

# Crawler only
./scripts/deploy.sh crawler v1.2.1 --auto-deploy
```

Or use gcloud:

```bash
# Deploy processor only
gcloud builds submit \
  --config=cloudbuild-processor-autodeploy.yaml \
  --region=us-central1 \
  --substitutions="_VERSION=feature-test-v1"

# Deploy API only
gcloud builds submit \
  --config=cloudbuild-api-autodeploy.yaml \
  --region=us-central1 \
  --substitutions="_VERSION=feature-test-v1"

# Deploy crawler only
gcloud builds submit \
  --config=cloudbuild-crawler-autodeploy.yaml \
  --region=us-central1 \
  --substitutions="_VERSION=feature-test-v1"
```

## File to Service Mapping

### Processor Triggers

```
cloudbuild-processor-autodeploy.yaml
```

**Files:**

- `Dockerfile.processor`
- `orchestration/**/*`
- `src/**/*`
- `requirements.txt`
- `pyproject.toml`
- `.dockerignore`

**Deployment Target:** `mizzou-processor` deployment

### API Triggers

```
cloudbuild-api-autodeploy.yaml
```

**Files:**

- `Dockerfile.api`
- `backend/**/*`
- `requirements.txt`
- `.dockerignore`

**Deployment Target:** `mizzou-api` deployment

### Crawler Triggers

```
cloudbuild-crawler-autodeploy.yaml
```

**Files:**

- `Dockerfile.crawler`
- `src/**/*`
- `requirements.txt`
- `pyproject.toml`
- `.dockerignore`

**Deployment Target:** `mizzou-crawler` CronJob

## Common Scenarios

### Scenario 1: API bug fix

```bash
# 1. Fix the bug in backend/
vim backend/app/routers/articles.py

# 2. Push to main
git add backend/app/routers/articles.py
git commit -m "fix: Correct article endpoint response"
git push origin main

# Result: Only API rebuilds (~5-8 min)
# Processor and Crawler remain untouched ✓
```

### Scenario 2: Add new extraction logic

```bash
# 1. Update processor code
vim orchestration/continuous_processor.py

# 2. Push to main
git add orchestration/continuous_processor.py
git commit -m "feat: Add entity extraction"
git push origin main

# Result: Only Processor rebuilds (~8-10 min)
# API and Crawler remain untouched ✓
```

### Scenario 3: Update shared utilities

```bash
# 1. Update shared code
vim src/extraction/extractor.py

# 2. Push to main
git add src/extraction/extractor.py
git commit -m "fix: Improve extraction accuracy"
git push origin main

# Result: Processor + Crawler rebuild (~15-18 min)
# API remains untouched ✓
```

### Scenario 4: Update all dependencies

```bash
# 1. Update requirements
vim requirements.txt

# 2. Push to main
git add requirements.txt
git commit -m "chore: Update dependencies"
git push origin main

# Result: All three rebuild (~25-30 min)
# All services updated with new dependencies
```

### Scenario 5: Test one service from feature branch

```bash
# On feature branch
git checkout feature/api-improvements
vim backend/app/routers/articles.py

# Deploy ONLY the API for testing
./scripts/deploy.sh api feature-test-v1 --auto-deploy

# Result: Only API deploys to test your changes
# Other services remain on main branch version
```

## Monitoring Individual Builds

### View all recent builds

```bash
gcloud builds list --limit=10
```

### View builds for specific service

```bash
# Processor builds
gcloud builds list --filter="substitutions._DEPLOYMENT_NAME=mizzou-processor" --limit=5

# API builds
gcloud builds list --filter="substitutions._DEPLOYMENT_NAME=mizzou-api" --limit=5

# Crawler builds
gcloud builds list --filter="substitutions._DEPLOYMENT_NAME=mizzou-crawler" --limit=5
```

### Stream logs for active build

```bash
# Get the latest build ID
BUILD_ID=$(gcloud builds list --ongoing --limit=1 --format='value(id)')

# Stream its logs
gcloud builds log $BUILD_ID --stream
```

## Verify Individual Deployments

### Check processor

```bash
kubectl get pods -n production -l app=mizzou-processor
kubectl logs -n production -l app=mizzou-processor --tail=50
```

### Check API

```bash
kubectl get pods -n production -l app=mizzou-api
kubectl logs -n production -l app=mizzou-api --tail=50

# Test the API
curl https://api.mizzou-news.com/api/articles?limit=5
```

### Check crawler

```bash
kubectl get cronjob -n production mizzou-crawler
kubectl get jobs -n production -l app=mizzou-crawler --sort-by=.metadata.creationTimestamp
```

## Cost Optimization

**Path-based triggers save money!**

| Deployment Strategy | Cost per Push | Time per Push |
|---------------------|---------------|---------------|
| Build all three every time | ~$0.50-$1.00 | 25-30 min |
| Smart path-based (one service) | ~$0.15-$0.35 | 5-10 min |
| Smart path-based (two services) | ~$0.30-$0.65 | 15-20 min |

**Example Monthly Savings:**

- 100 pushes/month to main
- 60% are single-service changes
- 30% are two-service changes
- 10% are three-service changes

**Without path-based:** 100 × $0.75 = **$75/month**

**With path-based:** (60 × $0.25) + (30 × $0.50) + (10 × $0.75) = **$30/month**

**Savings: $45/month (60% reduction)** 💰

## Troubleshooting

### Service didn't rebuild when expected

```bash
# Check trigger configuration
gcloud builds triggers describe processor-autodeploy-main

# Look for "includedFiles" field
# If missing, path-based filtering isn't enabled
```

### Wrong service rebuilt

```bash
# Check what files changed in the commit
git show --name-only HEAD

# Compare with service file patterns in docs/DEPLOYMENT_QUICK_REFERENCE.md
```

### Need to force rebuild all services

```bash
# Option 1: Disable path filtering temporarily
# Edit trigger in Cloud Console, remove "Included files"

# Option 2: Touch a shared file
touch requirements.txt
git add requirements.txt
git commit -m "chore: Trigger full rebuild"
git push origin main
```

## Best Practices

1. **Use path-based triggers** - Save time and money
2. **Deploy single services from feature branches** - Test before merging
3. **Monitor build logs** - Catch issues early
4. **Update version tags** - Track what's deployed
5. **Test after deployment** - Verify each service independently

## Getting Help

- **Build logs:** `https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler`
- **Trigger management:** `https://console.cloud.google.com/cloud-build/triggers?project=mizzou-news-crawler`
- **GKE workloads:** `https://console.cloud.google.com/kubernetes/workload?project=mizzou-news-crawler`
