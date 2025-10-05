# Automated Deployment Guide

## Overview

This project uses **Google Cloud Build triggers** for CI/CD with a safe deployment strategy:

### Deployment Strategy

**🚀 Main Branch (Production):**
- ✅ Automatic deployment on `git push`
- Triggers auto-deploy to GKE when code is merged to `main`
- Version tags use branch name + commit SHA

**🔧 Feature Branches:**
- ⚠️ Manual deployment only
- Use `gcloud builds submit` or helper script
- Prevents accidental deployment of unreviewed code

### Deployment Pipeline

1. 🔔 Receives webhook from GitHub (main branch only)
2. 📥 Pulls your code in the cloud
3. 🏗️ Builds Docker images
4. 📤 Pushes to Artifact Registry
5. 🚀 Deploys to GKE
6. ✅ Verifies deployment
7. 📊 Reports status

**Everything happens in Google Cloud - no local builds required!**

## Quick Start

### One-Time Setup

```bash
# Run the setup script to create auto-deploy triggers for main branch
./scripts/setup-triggers.sh
```

This creates triggers for all three services (processor, api, crawler) that automatically deploy when you push to the `main` branch.

### Production Deployment (Main Branch)

```bash
# 1. Create feature branch and make changes
git checkout -b feature/my-feature
git add .
git commit -m "feat: your feature"
git push origin feature/my-feature

# 2. Create PR and get reviews
# (Create PR on GitHub)

# 3. Merge to main - triggers automatic deployment
git checkout main
git pull origin main
git merge feature/my-feature
git push origin main  # ← This triggers auto-deploy!

# 4. Watch the magic happen in Cloud Console:
# https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler

# 5. Verify deployment
kubectl get pods -n production -w
```

### Feature Branch Deployment (Manual Testing)

```bash
# Option A: Use helper script
./scripts/deploy.sh processor feature-v1.2.3 --auto-deploy

# Option B: Use gcloud directly
gcloud builds submit \
  --config=cloudbuild-processor-autodeploy.yaml \
  --region=us-central1 \
  --substitutions="_VERSION=feature-test-v1"
```

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
