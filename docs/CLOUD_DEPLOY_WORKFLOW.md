# Cloud Deploy Workflow Summary

## How It Works

### Main Branch (Automatic Build + Deploy)

```
git push origin main
    ↓
GitHub webhook triggers Cloud Build
    ↓
Cloud Build:
  1. Builds all 3 Docker images
  2. Pushes to Artifact Registry
  3. Creates Cloud Deploy release (automatic)
    ↓
Cloud Deploy:
  4. Automatically deploys to production
    ↓
✅ Done! All services deployed
```

### Feature Branch (Build Only - Manual Deploy)

```
git push origin feature/my-branch
    ↓
GitHub webhook triggers Cloud Build
    ↓
Cloud Build:
  1. Builds all 3 Docker images
  2. Pushes to Artifact Registry
  3. Prints manual deploy command
  4. STOPS (no deployment)
    ↓
⚠️  Images ready but NOT deployed

To deploy manually:
gcloud deploy releases create release-abc123 \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=...,api=...,crawler=...
```

## Key Features

✅ **Main Branch**: Fully automatic (build → deploy)
✅ **Feature Branches**: Build only (safe testing)
✅ **Individual Services**: Deploy any service independently
✅ **Rollbacks**: Promote previous releases easily
✅ **Audit Trail**: Track all deployments

## Setup

```bash
./scripts/setup-cloud-deploy.sh
```

This creates:
- Cloud Deploy delivery pipeline
- Cloud Build trigger (monitors all branches)
- IAM permissions

## Common Commands

### Deploy from Feature Branch
```bash
# After Cloud Build completes, use the printed command or:
COMMIT_SHA=$(git rev-parse --short HEAD)
gcloud deploy releases create release-$COMMIT_SHA \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/processor:$COMMIT_SHA,api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/api:$COMMIT_SHA,crawler=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/crawler:$COMMIT_SHA
```

### Deploy Single Service
```bash
# Deploy only processor (latest)
gcloud deploy releases create processor-hotfix \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/processor:latest
```

### Rollback
```bash
# List releases
gcloud deploy releases list --delivery-pipeline=mizzou-news-crawler --region=us-central1

# Promote previous release
gcloud deploy releases promote --release=release-abc123 \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --to-target=production
```

## Monitoring

- **Cloud Build**: https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler
- **Cloud Deploy**: https://console.cloud.google.com/deploy/delivery-pipelines?project=mizzou-news-crawler
- **GKE Workloads**: https://console.cloud.google.com/kubernetes/workload?project=mizzou-news-crawler
