# CI/CD Service Detection & Triggering Strategy

## Overview

Your CI/CD pipeline uses **Cloud Build Triggers** to automatically detect which services need rebuilding based on **branch name** and **Dockerfile changes**, then communicates with `gcloud` via explicit triggers and artifact registry tagging.

## Architecture

```
GitHub Push to main
         ↓
Cloud Build Triggers activated (by branch: main)
         ↓
Each service trigger runs its specific cloudbuild-*.yaml
         ↓
Builds/pushes Docker images to Artifact Registry
         ↓
Cloud Deploy releases created (images used for K8s deployment)
         ↓
Argo Workflows updated (crawler image SHAs)
```

---

## How Service Detection Works

### 1. **Cloud Build Triggers** (Configuration-Based Detection)

You have **6 separate Cloud Build triggers** defined in `gcp/triggers/`:

```
trigger-base.yaml           → build-base-manual         (manual only)
trigger-ml-base.yaml        → build-ml-base-manual      (manual only)
trigger-migrator.yaml       → build-migrator-manual     (auto on main)
trigger-processor.yaml      → build-processor-manual    (auto on main)
trigger-api.yaml            → build-api-manual          (auto on main)
trigger-crawler.yaml        → build-crawler-manual      (auto on main)
```

**Key Configuration:**
```yaml
# Example: trigger-api.yaml
github:
  owner: LocalNewsImpact
  name: MizzouNewsCrawler
  push:
    branch: ^main$              # ONLY triggers on main branch
filename: gcp/cloudbuild/cloudbuild-api.yaml  # Which config to run
```

**Result:** When you push to `main`, ALL triggers activate automatically.

---

### 2. **Which Services Actually Build?**

Since all triggers activate on `main`, all services rebuild:

| Service | Trigger | Auto on main | Manual | Dockerfile |
|---------|---------|--------------|--------|-----------|
| base | trigger-base.yaml | ❌ | ✅ | Dockerfile.base |
| ml-base | trigger-ml-base.yaml | ❌ | ✅ | Dockerfile.ml-base |
| migrator | trigger-migrator.yaml | ✅ | ✅ | Dockerfile.migrator |
| processor | trigger-processor.yaml | ✅ | ✅ | Dockerfile.processor |
| api | trigger-api.yaml | ✅ | ✅ | Dockerfile.api |
| crawler | trigger-crawler.yaml | ✅ | ✅ | Dockerfile.crawler |

**Current behavior:** All 4 services (migrator, processor, api, crawler) rebuild on every main push.

---

## How gcloud Knows What to Build

### Step 1: Cloud Build Trigger Configuration
```bash
# Stored in GCP, defines trigger rules
gcloud builds triggers create github \
  --name="build-api-manual" \
  --repo-name="MizzouNewsCrawler" \
  --repo-owner="LocalNewsImpact" \
  --branch-pattern="^main$" \
  --build-config="gcp/cloudbuild/cloudbuild-api.yaml"
```

### Step 2: Trigger Activation
When you push to main, GCP **automatically matches** the branch pattern and:
1. Reads the trigger configuration
2. Finds the associated `cloudbuild-api.yaml` file
3. Executes that specific build configuration

### Step 3: Build Communication
The `cloudbuild-api.yaml` **explicitly tells gcloud** what to do:

```yaml
substitutions:
  _REGISTRY: us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler

steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'Dockerfile.api', ...]    # Build API image
  
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', '${_REGISTRY}/api']               # Push API to registry
```

**The communication mechanism:** The YAML file itself tells gcloud exactly what to build and where to push it.

---

## Current Implementation: All-or-Nothing Approach

**Current state:** When you push to `main`, **all services rebuild simultaneously**:

```
gcloud builds submit
  → Reads all trigger configurations
  → Activates ALL triggers that match branch ^main$
  → Runs all 4 cloudbuild-*.yaml files in parallel
  → Produces: migrator, processor, api, crawler images
  → Creates Cloud Deploy release with all images
  → Updates Argo Workflow template for crawler
```

**Pros:**
- ✅ Ensures all services stay in sync
- ✅ Simple, predictable behavior
- ✅ No complex branching logic needed

**Cons:**
- ❌ Rebuilds unchanged services (time/cost waste)
- ❌ Can't selectively deploy specific services from main

---

## Alternative: Smart Service Detection (If You Want It Later)

If you wanted **selective rebuilding** based on **which files changed**, you'd need:

### Option 1: GitHub Actions Pre-filter
```yaml
# .github/workflows/selective-build.yml
on:
  push:
    branches: [main]
    paths:
      - 'src/services/**'        # api changes
      - 'src/pipeline/**'        # processor changes
      - 'src/crawler/**'         # crawler changes
      - 'Dockerfile.api'
      - 'Dockerfile.processor'
      - 'Dockerfile.crawler'

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      build-api: ${{ steps.changes.outputs.api }}
      build-processor: ${{ steps.changes.outputs.processor }}
      build-crawler: ${{ steps.changes.outputs.crawler }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - id: changes
        run: |
          # Detect which services changed since last commit
          if git diff HEAD~1 -- src/services/** Dockerfile.api | grep -q .; then
            echo "api=true" >> $GITHUB_OUTPUT
          fi
          # ... repeat for other services
  
  trigger-builds:
    needs: detect-changes
    runs-on: ubuntu-latest
    steps:
      - if: needs.detect-changes.outputs.build-api == 'true'
        run: gcloud builds triggers run build-api-manual --branch=main
      
      - if: needs.detect-changes.outputs.build-processor == 'true'
        run: gcloud builds triggers run build-processor-manual --branch=main
```

### Option 2: Commit Message Triggers
```bash
# User pushes with: git commit -m "build: api processor" 
# GitHub Actions detects keywords and triggers only those services

if git log -1 --oneline | grep -i "api"; then
  gcloud builds triggers run build-api-manual --branch=main
fi
```

### Option 3: Separate Branches
```bash
# Push to feature branches for specific services
git push origin feature/api-changes    # Auto-build only API
git push origin feature/crawler-fix    # Auto-build only crawler
git push origin main                   # Auto-build everything
```

---

## Your Deployment Flow (Current)

```
1. You push to main
   └─ Triggers 4 Cloud Build jobs:
      ├─ build-api-manual → cloudbuild-api.yaml
      ├─ build-crawler-manual → cloudbuild-crawler.yaml
      ├─ build-processor-manual → cloudbuild-processor-v1.2.2.yaml
      └─ build-migrator-manual → cloudbuild-migrator.yaml

2. Each build:
   ├─ Runs migrations (migrator only)
   ├─ Builds Docker image for that service
   ├─ Pushes to Artifact Registry (us-central1-docker.pkg.dev/...)
   └─ Exports image SHA for deployment

3. Cloud Deploy release created
   └─ References all 4 image SHAs
   └─ Deploys to production GKE

4. Argo Workflow template updated
   └─ New crawler image SHA
   └─ Next scheduled run uses new version
```

---

## Communication Flow: GitHub → gcloud → GKE

```
GitHub Push (main branch)
  ↓ [Branch matches ^main$ pattern]
  ↓
Cloud Build Triggers (GCP)
  ├─ Reads trigger config
  ├─ Determines which cloudbuild-*.yaml files to run
  ↓
Cloud Build Executor
  ├─ Reads cloudbuild-*.yaml file
  ├─ Executes each step (build, push, deploy)
  ├─ Uses substitutions: ${PROJECT_ID}, ${SHORT_SHA}, etc.
  ↓
Artifact Registry
  ├─ Stores image: us-central1-docker.pkg.dev/.../api:${SHORT_SHA}
  ├─ Tags with: latest, v1.3.1
  ↓
Cloud Deploy
  ├─ Creates release with image SHAs
  ├─ References delivery pipeline: mizzou-news-crawler
  ↓
GKE Deployment
  ├─ Pulls images from Artifact Registry
  ├─ Updates Kubernetes Deployments
  ↓
Argo Workflows
  └─ Updates WorkflowTemplate with crawler image SHA
```

---

## Key Mechanisms: How gcloud Knows

### 1. **Branch Pattern Matching**
```yaml
# GCP evaluates: Does this push match?
push:
  branch: ^main$

# Result: YES → activate trigger → run cloudbuild-api.yaml
```

### 2. **Explicit YAML Configuration**
```yaml
# The YAML file tells gcloud EXACTLY what to do
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'Dockerfile.api', '-t', '${_REGISTRY}/api:${SHORT_SHA}']
```

### 3. **Substitutions (Environment Variables)**
```yaml
# gcloud injects these automatically:
${PROJECT_ID}   # mizzou-news-crawler
${SHORT_SHA}    # 7-char git commit SHA
${BRANCH_NAME}  # main
${REVISION_ID}  # full git commit SHA
```

### 4. **Service Account Authorization**
```yaml
# Each trigger has a service account:
serviceAccount: projects/mizzou-news-crawler/serviceAccounts/145096615031-compute@developer.gserviceaccount.com

# This account has permissions to:
# ✅ Push to Artifact Registry
# ✅ Create Cloud Deploy releases
# ✅ Update Kubernetes resources
# ✅ Access GKE cluster
```

---

## Summary Table

| Aspect | Mechanism | Configuration |
|--------|-----------|----------------|
| **Which services?** | All 4 triggers activate on `main` push | `gcp/triggers/*.yaml` files |
| **How detected?** | Branch pattern regex matching | `push.branch: ^main$` |
| **Communication to gcloud** | Trigger configuration + YAML file | Cloud Build trigger configs |
| **What to build?** | Specified in cloudbuild-*.yaml | `Dockerfile.X`, build steps |
| **Where to push?** | Artifact Registry URL | `${_REGISTRY}/service:${SHORT_SHA}` |
| **Deployment info?** | Image SHAs + metadata | Cloud Deploy release creation |
| **K8s updates?** | Automatic pull + deployment | Kubernetes controllers |

---

## Next Steps (Optional)

If you want to **optimize** this later:

1. **Reduce rebuild time**: Implement selective triggering (Option 1 above)
2. **Add staging deployments**: Create separate triggers for feature branches
3. **Add approval gates**: Require manual approval before production deployment
4. **Implement canary deployments**: Use Cloud Deploy traffic splitting

But for now, **the current all-or-nothing approach is solid and reliable** ✅

