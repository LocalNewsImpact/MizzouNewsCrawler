# Automated Deployment Guide

## Overview

This project uses **Google Cloud Deploy** for managed CI/CD with a clean separation of concerns:

### Deployment Strategy

**🚀 Main Branch (Production):**
- ✅ Automatic build → release → deploy on `git push`
- Cloud Build creates Docker images
- Cloud Deploy automatically deploys to GKE
- Built-in rollback and promotion capabilities

**🔧 Feature Branches:**
- ✅ Automatic build on `git push` (images ready)
- ⚠️ Manual deployment (explicit release creation)
- Test builds before merging to main
- Prevents accidental production deployment

### Architecture

```
GitHub Push (any branch)
    ↓
Cloud Build (builds images)
    ↓
Artifact Registry (stores images)
    ↓
Cloud Deploy Release
    ├─ Main branch: Auto-created ✅
    └─ Feature branch: Manual 🔧
    ↓
Production (GKE)
```

### Why Cloud Deploy?

- **Separation of concerns**: Build once, deploy many times
- **Individual service deployment**: Deploy processor, API, or crawler independently
- **Better rollbacks**: Promote previous releases easily
- **Deployment verification**: Automated health checks
- **Progressive delivery**: Ready for canary/blue-green deployments
- **Audit trail**: Track who deployed what and when

**Everything happens in Google Cloud - no local builds required!**

## Quick Start

### One-Time Setup

```bash
# Run the setup script to configure Cloud Deploy
./scripts/setup-cloud-deploy.sh
```

This script:

- Enables required Google Cloud APIs
- Creates the Cloud Deploy delivery pipeline
- Sets up Cloud Build trigger (builds on any branch)
- Grants necessary permissions
- Configures automatic deployment for main branch

### Daily Workflow - Production Deployment (Main Branch)

```bash
# 1. Make changes and push to main
git add .
git commit -m "feat: your feature"
git push origin main  # ← Triggers build + automatic deployment!

# 2. Watch Cloud Build (builds images)
# https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler

# 3. Watch Cloud Deploy (deploys to GKE)
# https://console.cloud.google.com/deploy/delivery-pipelines?project=mizzou-news-crawler

# 4. Verify deployment
kubectl get pods -n production -w
```

### Feature Branch Workflow (Build + Manual Deploy)

```bash
# 1. Push feature branch - builds automatically
git checkout -b feature/my-feature
git add .
git commit -m "feat: your feature"
git push origin feature/my-feature  # ← Builds images (doesn't deploy)

# 2. Images are ready in Artifact Registry!

# 3. Manually create Cloud Deploy release to test
COMMIT_SHA=$(git rev-parse --short HEAD)
gcloud deploy releases create release-$COMMIT_SHA \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --images=processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/processor:$COMMIT_SHA,api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/api:$COMMIT_SHA,crawler=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-news-crawler/crawler:$COMMIT_SHA

# 4. Merge to main when ready - auto-deploys latest build
```

## Deploying Individual Services

**Each service has its own independent build configuration** - you never have to rebuild all three!

### Automatic Path-Based Deployment (Main Branch)

When you run `./scripts/setup-triggers.sh`, you'll be asked about **smart path-based triggers**. If enabled:

**Only modified services rebuild automatically!**

```bash
# Scenario 1: You only modified the API
git commit -m "fix: Update API endpoint"
git push origin main
# → ONLY the API rebuilds and deploys
# → Processor and crawler stay unchanged ✓

# Scenario 2: You modified processor code
git commit -m "feat: Add new extraction logic"
git push origin main
# → ONLY the processor rebuilds and deploys
# → API and crawler stay unchanged ✓

# Scenario 3: You modified shared code in src/
git push origin main
# → Both processor and crawler rebuild (they use src/)
# → API is unchanged (doesn't use src/) ✓
```

### Manual Deployment of Individual Services

From feature branches or for testing, deploy any single service:

```bash
# Deploy ONLY the processor
./scripts/deploy.sh processor v1.2.3 --auto-deploy

# Deploy ONLY the API
./scripts/deploy.sh api v1.3.2 --auto-deploy

# Deploy ONLY the crawler
./scripts/deploy.sh crawler v1.2.1 --auto-deploy

# Or use gcloud directly for one service
gcloud builds submit \
  --config=cloudbuild-processor-autodeploy.yaml \
  --region=us-central1 \
  --substitutions="_VERSION=hotfix-v1.2.4"
```

### Which Files Trigger Which Service?

**Processor** (`cloudbuild-processor-autodeploy.yaml`):
- `Dockerfile.processor`
- `orchestration/**` - continuous processor code
- `src/**` - shared utilities
- `requirements.txt`, `pyproject.toml`

**API** (`cloudbuild-api-autodeploy.yaml`):
- `Dockerfile.api`
- `backend/**` - FastAPI application
- `requirements.txt`

**Crawler** (`cloudbuild-crawler-autodeploy.yaml`):
- `Dockerfile.crawler`
- `src/**` - crawler source
- `requirements.txt`, `pyproject.toml`

**Shared files** (trigger multiple services):
- `requirements.txt` - triggers all three
- `src/**` - triggers processor + crawler
- `backend/**` - triggers only API

## How It Works

### Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────────────┐
│             │  push   │              │ webhook │                 │
│   GitHub    │────────▶│   Your Repo  │────────▶│  Cloud Build    │
│             │         │              │         │   Triggers      │
└─────────────┘         └──────────────┘         └────────┬────────┘
                                                           │
                                                           │ starts
                                                           ▼
                                                   ┌───────────────┐
                                                   │  Build Job    │
                                                   │  (in cloud)   │
                                                   └───────┬───────┘
                                                           │
                                    ┌──────────────────────┼──────────────────────┐
                                    │                      │                      │
                                    ▼                      ▼                      ▼
                            ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
                            │ Build Docker │      │ Push to      │      │ Deploy to    │
                            │ Image        │─────▶│ Artifact     │─────▶│ GKE          │
                            │              │      │ Registry     │      │              │
                            └──────────────┘      └──────────────┘      └──────────────┘
                                                                                 │
                                                                                 ▼
                                                                         ┌──────────────┐
                                                                         │ Health Check │
                                                                         │ & Verify     │
                                                                         └──────────────┘
```

### What Happens in the Cloud

When you push a commit:

1. **GitHub Webhook** → Cloud Build receives notification
2. **Clone Repo** → Cloud Build pulls your latest code
3. **Build Image** → Docker builds in powerful cloud machines
4. **Security Scan** → (Optional) Image vulnerability scanning
5. **Push Image** → To Artifact Registry with versioning
6. **Get GKE Credentials** → Authenticate to Kubernetes cluster
7. **Update Deployment** → `kubectl set image` with new version
8. **Wait for Rollout** → Monitors deployment status
9. **Health Check** → Verifies pods are running
10. **Log Results** → All logs available in Cloud Console

## Cloud Build Configurations

### Files

- `cloudbuild-processor-autodeploy.yaml` - Processor build + deploy
- `cloudbuild-api-autodeploy.yaml` - API build + deploy
- `cloudbuild-crawler-autodeploy.yaml` - Crawler build + deploy

### Triggers Created

#### Feature Branch Triggers (Auto-deploy)

| Trigger Name | Service | Branch | Approval | Version |
|--------------|---------|--------|----------|---------|
| `processor-autodeploy-feature` | Processor | `feature/gcp-kubernetes-deployment` | No | `latest` |
| `api-autodeploy-feature` | API | `feature/gcp-kubernetes-deployment` | No | `latest` |
| `crawler-autodeploy-feature` | Crawler | `feature/gcp-kubernetes-deployment` | No | `latest` |

#### Production Triggers (With Approval)

| Trigger Name | Service | Branch | Approval | Version |
|--------------|---------|--------|----------|---------|
| `processor-autodeploy-prod` | Processor | `main` | **Yes** | `main-{SHA}` |
| `api-autodeploy-prod` | API | `main` | **Yes** | `main-{SHA}` |
| `crawler-autodeploy-prod` | Crawler | `main` | **Yes** | `main-{SHA}` |

## Monitoring Deployments

### Cloud Console

View builds in real-time:
```
https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler
```

### Command Line

```bash
# List recent builds
gcloud builds list --limit=10

# Watch ongoing build
gcloud builds list --ongoing

# Stream logs for specific build
gcloud builds log <BUILD_ID> --stream

# View trigger status
gcloud builds triggers list

# View deployment status
kubectl get pods -n production -w
```

### GitHub

Build status appears automatically on your commits and PRs as checks.

## Customization

### Change Version Numbers

Edit the substitutions in the Cloud Build YAML:

```yaml
substitutions:
  _VERSION: 'v1.2.4'  # Change this
  _CLUSTER_NAME: 'mizzou-cluster'
  _NAMESPACE: 'production'
```

Or override when manually triggering:

```bash
gcloud builds triggers run processor-autodeploy-feature \
  --branch=feature/gcp-kubernetes-deployment \
  --substitutions=_VERSION=v1.2.5
```

### Path-Based Triggers

Only trigger builds when specific files change:

```bash
gcloud builds triggers update processor-autodeploy-feature \
  --included-files="Dockerfile.processor,orchestration/**,src/**,requirements.txt"
```

Now processor only builds when those files change!

### Add Test Step

Edit `cloudbuild-*-autodeploy.yaml` to add a test step:

```yaml
steps:
  # Add before building
  - name: 'python:3.11-slim'
    id: 'run-tests'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        pip install -r requirements.txt
        pip install pytest
        pytest tests/ -v --tb=short -x
```

## Rollback

If a deployment fails or has issues:

```bash
# Rollback to previous version
kubectl rollout undo deployment/mizzou-processor -n production

# Rollback to specific revision
kubectl rollout history deployment/mizzou-processor -n production
kubectl rollout undo deployment/mizzou-processor --to-revision=2 -n production

# Check rollout status
kubectl rollout status deployment/mizzou-processor -n production
```

## Troubleshooting

### Build Fails

**Check logs:**
```bash
gcloud builds list --limit=5
gcloud builds log <BUILD_ID>
```

**Common issues:**
- Dockerfile syntax errors
- Missing dependencies in requirements.txt
- Insufficient Cloud Build permissions

### Deployment Fails

**Check Kubernetes events:**
```bash
kubectl get events -n production --sort-by='.lastTimestamp'
kubectl describe pod <POD_NAME> -n production
```

**Common issues:**
- Image pull errors (check Artifact Registry permissions)
- Resource limits too low
- Health check failures

### Trigger Doesn't Fire

**Check webhook:**
1. Go to GitHub repo → Settings → Webhooks
2. Look for `https://cloudbuild.googleapis.com/...`
3. Check "Recent Deliveries" for errors

**Check trigger configuration:**
```bash
gcloud builds triggers describe processor-autodeploy-feature
```

### Permission Errors

**Grant Cloud Build permissions:**
```bash
PROJECT_ID="mizzou-news-crawler"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/container.developer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

## Manual Deployment

If you need to deploy manually (bypass triggers):

```bash
# Build and deploy in one command
gcloud builds submit \
  --config=cloudbuild-processor-autodeploy.yaml \
  --region=us-central1 \
  --substitutions=_VERSION=v1.2.3
```

## Best Practices

### ✅ Do's

- ✅ Always run tests before pushing
- ✅ Use semantic versioning (v1.2.3)
- ✅ Monitor build logs for errors
- ✅ Verify deployments after push
- ✅ Use feature branches for testing
- ✅ Require approval for production
- ✅ Tag releases in Git

### ❌ Don'ts

- ❌ Don't push directly to main without review
- ❌ Don't skip tests to "save time"
- ❌ Don't ignore build failures
- ❌ Don't manually edit deployments (use triggers)
- ❌ Don't commit sensitive data (use secrets)

## Security

### Secrets Management

Never commit secrets! Use Google Secret Manager:

```bash
# Create secret
echo -n "secret-value" | gcloud secrets create my-secret --data-file=-

# Grant Cloud Build access
gcloud secrets add-iam-policy-binding my-secret \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Use in Cloud Build
availableSecrets:
  secretManager:
  - versionName: projects/${PROJECT_ID}/secrets/my-secret/versions/latest
    env: 'MY_SECRET'
```

### Binary Authorization

For production, enable Binary Authorization to ensure only verified images deploy:

```bash
# Enable Binary Authorization
gcloud services enable binaryauthorization.googleapis.com

# Create policy requiring attestations
gcloud container binauthz policy import policy.yaml
```

## Cost Optimization

Cloud Build pricing:
- **First 120 build-minutes/day**: Free
- **After 120 minutes**: $0.003/build-minute

Tips to reduce costs:
1. Use path-based triggers (only build what changed)
2. Optimize Dockerfile (use multi-stage builds, layer caching)
3. Set appropriate machine types
4. Use build caching

## Support

- **Documentation**: See `docs/CLOUD_BUILD_TRIGGERS.md`
- **Cloud Build Docs**: https://cloud.google.com/build/docs
- **GKE Docs**: https://cloud.google.com/kubernetes-engine/docs
- **Troubleshooting**: Check logs in Cloud Console

## Related Scripts

- `scripts/setup-triggers.sh` - Set up all Cloud Build triggers
- `scripts/deploy.sh` - Manual deployment script (backup)
- `docs/CLOUD_BUILD_TRIGGERS.md` - Detailed trigger documentation
