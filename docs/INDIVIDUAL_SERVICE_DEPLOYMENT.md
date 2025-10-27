# Individual Service Deployment Guide

This guide shows how to build and deploy individual services from feature branches.

## Quick Reference

### Build + Deploy Processor Only

```bash
# Build only processor
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-processor-only.yaml

# Deploy only processor
gcloud deploy releases create processor-$(git rev-parse --short HEAD) \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/processor:latest
```

### Build + Deploy API Only

```bash
# Build only API
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-api-only.yaml

# Deploy only API
gcloud deploy releases create api-$(git rev-parse --short HEAD) \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/api:latest
```

### Build + Deploy Crawler Only

```bash
# Build only crawler
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-crawler-only.yaml

# Deploy only crawler
gcloud deploy releases create crawler-$(git rev-parse --short HEAD) \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=crawler=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/crawler:latest
```

## Detailed Workflows

### Option 1: Build Individual Service (Recommended)

**When to use:** You only changed one service

```bash
# Example: Only modified processor code
git checkout feature/processor-fix
git push origin feature/processor-fix

# Build ONLY processor (saves time and money)
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-processor-only.yaml

# Deploy ONLY processor
gcloud deploy releases create processor-hotfix \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/processor:latest
```

### Option 2: Build All, Deploy One

**When to use:** You changed multiple services but want to test one

```bash
# Build all three services
gcloud builds submit --config=gcp/cloudbuild/cloudbuild.yaml

# Deploy ONLY the one you want to test
gcloud deploy releases create api-test \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/api:latest
```

### Option 3: Build All, Deploy All

**When to use:** You changed multiple services and want to test everything

```bash
# Build all services
gcloud builds submit --config=gcp/cloudbuild/cloudbuild.yaml

# Deploy all services together
COMMIT_SHA=$(git rev-parse --short HEAD)
gcloud deploy releases create release-$COMMIT_SHA \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/processor:$COMMIT_SHA,api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/api:$COMMIT_SHA,crawler=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/crawler:$COMMIT_SHA
```

## Real-World Examples

### Scenario 1: Hotfix for Processor

```bash
# You're on feature/fix-extraction-bug
git push origin feature/fix-extraction-bug

# Build only processor (fast, cheap)
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-processor-only.yaml

# Deploy only processor
gcloud deploy releases create processor-extraction-fix \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/processor:latest

# Verify deployment
kubectl get pods -n production -l app=mizzou-processor -w
```

### Scenario 2: API Endpoint Update

```bash
# You're on feature/new-api-endpoint
git push origin feature/new-api-endpoint

# Build only API (no need to rebuild processor/crawler)
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-api-only.yaml

# Deploy only API
gcloud deploy releases create api-new-endpoint \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/api:latest

# Test the API
kubectl port-forward -n production svc/mizzou-api 8000:80
curl http://localhost:8000/api/articles
```

### Scenario 3: Crawler Schedule Change

```bash
# You're on feature/crawler-schedule
git push origin feature/crawler-schedule

# Build only crawler
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-crawler-only.yaml

# Deploy only crawler
gcloud deploy releases create crawler-schedule-update \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=crawler=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/crawler:latest

# Verify CronJob
kubectl get cronjob -n production mizzou-crawler
```

## Build Configs Available

| File | Purpose | Build Time | Use When |
|------|---------|------------|----------|
| `gcp/cloudbuild/cloudbuild.yaml` | All 3 services | ~10-15 min | Changed multiple services |
| `gcp/cloudbuild/cloudbuild-processor-only.yaml` | Processor only | ~3-5 min | Changed processor code |
| `gcp/cloudbuild/cloudbuild-api-only.yaml` | API only | ~3-5 min | Changed API code |
| `gcp/cloudbuild/cloudbuild-crawler-only.yaml` | Crawler only | ~3-5 min | Changed crawler code |

## Cost Savings

Building individual services saves significant Cloud Build minutes:

- **All services**: ~15 minutes = $0.15 per build
- **Single service**: ~5 minutes = $0.05 per build
- **Savings**: 67% reduction in build time and cost!

If you deploy processor 10 times during development:
- Building all: 150 minutes = $1.50
- Building processor only: 50 minutes = $0.50
- **Save: $1.00 per 10 deploys**

## Monitoring

Watch your builds and deployments:

- **Cloud Build**: <https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler>
- **Cloud Deploy**: <https://console.cloud.google.com/deploy/delivery-pipelines/us-central1/mizzou-news-crawler?project=mizzou-news-crawler>
- **GKE Workloads**: <https://console.cloud.google.com/kubernetes/workload?project=mizzou-news-crawler>

## Rollback Individual Service

If something goes wrong, rollback just that service:

```bash
# List recent releases
gcloud deploy releases list \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --limit=10

# Rollback to previous processor version
gcloud deploy releases promote \
  --release=processor-previous-working-version \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --to-target=production
```
