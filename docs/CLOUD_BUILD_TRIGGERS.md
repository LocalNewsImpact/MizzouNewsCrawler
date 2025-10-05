# Cloud Build Triggers Setup for Automated Deployment

This document explains how to set up Cloud Build triggers with a safe deployment strategy:

## Deployment Strategy

**🚀 Main Branch (Production):**

- Automatic deployment when pushing to `main` branch
- Creates triggers that monitor `main` for changes
- Version tags use branch name + commit SHA
- Best for production releases

**🔧 Feature Branches:**

- Manual deployment only (no automatic triggers)
- Use `gcloud builds submit` to deploy when testing
- Prevents accidental deployment of work-in-progress
- Best for development and testing

## Overview

Cloud Build triggers on main branch automatically:

1. Monitor your GitHub repository for changes
2. Pull the code when you push to `main`
3. Build Docker images in the cloud
4. Deploy to GKE automatically

## Setup Instructions

### 1. Connect GitHub Repository to Cloud Build

First-time setup (only need to do this once):

```bash
# Connect your GitHub repository to Cloud Build
gcloud builds triggers create github \
  --repo-name=MizzouNewsCrawler \
  --repo-owner=LocalNewsImpact \
  --name=connect-github \
  --description="Initial GitHub connection" \
  --build-config=cloudbuild.yaml
```

Or use the Console:
1. Go to Cloud Build > Triggers
2. Click "Connect Repository"
3. Select GitHub
4. Authenticate and select LocalNewsImpact/MizzouNewsCrawler
5. Click "Connect"

### 2. Create Automated Deployment Triggers (Main Branch Only)

Run these commands to create triggers that auto-deploy on push to `main`:

#### Processor Trigger (Auto-deploy on main branch)

```bash
gcloud builds triggers create github \
  --name=processor-autodeploy-main \
  --repo-name=MizzouNewsCrawler \
  --repo-owner=LocalNewsImpact \
  --branch-pattern="^main$" \
  --build-config=cloudbuild-processor-autodeploy.yaml \
  --description="Auto-build and deploy processor when pushing to main branch" \
  --include-logs-with-status \
  --substitutions="_VERSION=\${BRANCH_NAME}-\${SHORT_SHA}"
```

#### API Trigger (Auto-deploy on main branch)

```bash
gcloud builds triggers create github \
  --name=api-autodeploy-main \
  --repo-name=MizzouNewsCrawler \
  --repo-owner=LocalNewsImpact \
  --branch-pattern="^main$" \
  --build-config=cloudbuild-api-autodeploy.yaml \
  --description="Auto-build and deploy API when pushing to main branch" \
  --include-logs-with-status \
  --substitutions="_VERSION=\${BRANCH_NAME}-\${SHORT_SHA}"
```

#### Crawler Trigger (Auto-deploy on main branch)

```bash
gcloud builds triggers create github \
  --name=crawler-autodeploy-main \
  --repo-name=MizzouNewsCrawler \
  --repo-owner=LocalNewsImpact \
  --branch-pattern="^main$" \
  --build-config=cloudbuild-crawler-autodeploy.yaml \
  --description="Auto-build and deploy crawler when pushing to main branch" \
  --include-logs-with-status \
  --substitutions="_VERSION=\${BRANCH_NAME}-\${SHORT_SHA}"
```

### 3. Manual Deployment from Feature Branches

Feature branches should NOT have automatic triggers. Instead, deploy manually:

**Option A: Use the setup script**

```bash
# This creates the main branch triggers and shows you how to deploy from features
./scripts/setup-triggers.sh
```

**Option B: Manual deployment with gcloud**

```bash
# Deploy from your current feature branch
gcloud builds submit \
  --config=cloudbuild-processor-autodeploy.yaml \
  --region=us-central1 \
  --substitutions="_VERSION=feature-test-v1"
```

**Option C: Use the helper script**

```bash
# Deploy processor from feature branch
./scripts/deploy.sh processor feature-v1.2.3 --auto-deploy

# Deploy all services
./scripts/deploy.sh all feature-v1.2.3 --auto-deploy
```

### 4. Smart Path-Based Triggers (Recommended)

**Only rebuild services when their files change!**

The setup script will ask if you want path-based filtering. If enabled, each service only builds when its relevant files are modified:

**Processor triggers on:**
- `Dockerfile.processor`
- `orchestration/**` (continuous processor code)
- `src/**` (shared source code)
- `requirements.txt`, `pyproject.toml`

**API triggers on:**
- `Dockerfile.api`
- `backend/**` (API backend code)
- `requirements.txt`

**Crawler triggers on:**
- `Dockerfile.crawler`
- `src/**` (crawler source code)
- `requirements.txt`, `pyproject.toml`

**Benefits:**
- ✅ Faster deployments (only build what changed)
- ✅ Less cloud build time (saves costs)
- ✅ Fewer unnecessary deployments
- ✅ Easier to track what actually deployed

**Example:**
```bash
# You only modified backend/app/routers/articles.py
git push origin main
# → Only the API rebuilds and deploys
# → Processor and crawler are unchanged ✓ \
  --build-config=cloudbuild-api-autodeploy.yaml \
  --included-files="Dockerfile.api,backend/**,src/models/**,requirements.txt" \
  --description="Smart API deployment - only on relevant file changes"
```

## How It Works

### When You Push to GitHub:

1. **GitHub webhook** notifies Cloud Build
2. **Cloud Build** clones your repo in the cloud
3. **Docker images** are built in Cloud Build (not locally)
4. **Images** are pushed to Artifact Registry
5. **kubectl** commands update your GKE deployments
6. **Rollout** happens automatically with health checks

### Example Workflow:

```bash
# On your local machine:
git add .
git commit -m "fix: Remove --limit from populate-gazetteer"
git push origin feature/gcp-kubernetes-deployment

# Automatically in Google Cloud:
# ✅ Cloud Build receives webhook from GitHub
# ✅ Clones repository
# ✅ Builds processor image
# ✅ Pushes to Artifact Registry
# ✅ Updates GKE deployment
# ✅ Waits for rollout
# ✅ Verifies pods are running
# ✅ Sends you a notification
```

## View Trigger Status

```bash
# List all triggers
gcloud builds triggers list

# View trigger details
gcloud builds triggers describe processor-autodeploy-feature

# View recent builds
gcloud builds list --limit=10

# Stream logs for a specific build
gcloud builds log <BUILD_ID> --stream
```

## Trigger Configuration Files

The triggers use these Cloud Build config files:
- `cloudbuild-processor-autodeploy.yaml` - Processor build + deploy
- `cloudbuild-api-autodeploy.yaml` - API build + deploy
- `cloudbuild-crawler-autodeploy.yaml` - Crawler build + deploy

## Notifications (Optional)

Set up Slack/Email notifications for build results:

```bash
# Install Cloud Build Notifier
# See: https://github.com/GoogleCloudPlatform/cloud-build-notifiers

# Create a Slack webhook secret
echo -n "YOUR_SLACK_WEBHOOK_URL" | gcloud secrets create slack-webhook --data-file=-

# Update trigger with notification
gcloud builds triggers update processor-autodeploy-feature \
  --subscription=projects/mizzou-news-crawler/topics/cloud-builds
```

## Testing the Trigger

To test without pushing:

```bash
# Manually run a trigger
gcloud builds triggers run processor-autodeploy-feature \
  --branch=feature/gcp-kubernetes-deployment

# Watch the build
gcloud builds list --ongoing --limit=1
```

## Rollback

If a deployment fails, rollback is easy:

```bash
# Rollback to previous deployment
kubectl rollout undo deployment/mizzou-processor -n production

# Rollback to specific revision
kubectl rollout undo deployment/mizzou-processor --to-revision=2 -n production

# View rollout history
kubectl rollout history deployment/mizzou-processor -n production
```

## Security Best Practices

1. **Use separate triggers for feature/main branches**
2. **Require approval for production deployments**
3. **Use service accounts with minimal permissions**
4. **Enable Binary Authorization for image verification**
5. **Use secrets for sensitive data**

## Permissions Required

The Cloud Build service account needs:

```bash
PROJECT_ID="mizzou-news-crawler"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

# Grant Kubernetes Engine Developer role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/container.developer"

# Grant Service Account User role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

## Troubleshooting

### Build fails with permission error:
```bash
# Check service account permissions
gcloud projects get-iam-policy mizzou-news-crawler \
  --flatten="bindings[].members" \
  --filter="bindings.members:*cloudbuild*"
```

### Deployment times out:
- Check GKE cluster has enough resources
- Increase timeout in cloudbuild YAML
- Check pod logs: `kubectl logs -n production -l app=mizzou-processor`

### Trigger doesn't fire:
- Verify webhook in GitHub repo settings
- Check trigger included/ignored files patterns
- View trigger logs in Cloud Console

## Next Steps

After setting up triggers:

1. ✅ Push a commit to test the automation
2. ✅ Monitor the build in Cloud Console
3. ✅ Verify deployment in GKE
4. ✅ Set up notifications
5. ✅ Create triggers for main branch (with approval)
6. ✅ Document the CI/CD pipeline for your team
