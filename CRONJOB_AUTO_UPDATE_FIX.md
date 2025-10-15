# Auto-Update CronJob Images on Build

**Date**: October 15, 2025  
**Issue**: CronJobs were pinned to old SHA tags and not updating when new images were built  
**Status**: ✅ **FIXED**

---

## Problem

When building new crawler images, the Kubernetes CronJobs (`mizzou-crawler`, `mizzou-discovery`) were stuck using old image tags (e.g., `crawler:7f172f9`) instead of automatically using the newly built images.

### Root Cause

1. **Deployments** (API, Processor) have `kubectl set image` steps in their Cloud Build configs
2. **CronJobs** (Crawler) did NOT have these steps
3. Result: Manual intervention required to update cronjob images after every build

---

## Solution

Added automatic image update steps to `cloudbuild-crawler.yaml` that mirror the pattern used by API and Processor builds.

### Changes Made

**File**: `cloudbuild-crawler.yaml`

Added three new build steps:

1. **Get GKE Credentials**: Authenticate kubectl to the cluster
2. **Update mizzou-crawler cronjob**: Set image to new SHA tag
3. **Update mizzou-discovery cronjob**: Set image to new SHA tag (if exists)

```yaml
# Get GKE credentials for kubectl commands
- name: 'gcr.io/cloud-builders/gcloud'
  id: 'get-gke-credentials'
  args:
    - 'container'
    - 'clusters'
    - 'get-credentials'
    - 'mizzou-cluster'
    - '--zone=us-central1-a'

# Update crawler cronjob to use new image
- name: 'gcr.io/cloud-builders/kubectl'
  id: 'update-crawler-cronjob'
  env:
    - 'CLOUDSDK_COMPUTE_ZONE=us-central1-a'
    - 'CLOUDSDK_CONTAINER_CLUSTER=mizzou-cluster'
  args:
    - 'set'
    - 'image'
    - 'cronjob/mizzou-crawler'
    - 'crawler=${_REGISTRY}/crawler:${SHORT_SHA}'
    - '--namespace=production'
  waitFor: ['get-gke-credentials']

# Update discovery cronjob to use new image (if it exists)
- name: 'gcr.io/cloud-builders/kubectl'
  id: 'update-discovery-cronjob'
  env:
    - 'CLOUDSDK_COMPUTE_ZONE=us-central1-a'
    - 'CLOUDSDK_CONTAINER_CLUSTER=mizzou-cluster'
  entrypoint: 'bash'
  args:
    - '-c'
    - |
      if kubectl get cronjob mizzou-discovery -n production &>/dev/null; then
        kubectl set image cronjob/mizzou-discovery \
          discovery=${_REGISTRY}/crawler:${SHORT_SHA} \
          --namespace=production
        echo "✅ Updated mizzou-discovery cronjob"
      else
        echo "ℹ️  mizzou-discovery cronjob not found, skipping"
      fi
  waitFor: ['get-gke-credentials']
```

**File**: `k8s/crawler-cronjob.yaml`

Fixed the image reference to use full registry path:

```yaml
# OLD:
image: crawler

# NEW:
image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/crawler:latest
```

---

## How It Works

### Build Flow

```
1. Cloud Build triggered (manual or CI/CD)
   ↓
2. Build crawler image with tags:
   - crawler:${SHORT_SHA}  (e.g., crawler:abc123f)
   - crawler:v1.3.1
   - crawler:latest  (NOT used in production, only for dev)
   ↓
3. Push images to Artifact Registry
   ↓
4. Get GKE cluster credentials
   ↓
5. kubectl set image cronjob/mizzou-crawler crawler=${_REGISTRY}/crawler:${SHORT_SHA}
   ↓
6. kubectl set image cronjob/mizzou-discovery discovery=${_REGISTRY}/crawler:${SHORT_SHA}
   ↓
7. ✅ Next cronjob run uses new image!
```

### Why SHA Tags Instead of :latest

Using `:latest` tag in production causes issues:
- **Namespace collisions**: Multiple services pulling `:latest` simultaneously
- **No rollback capability**: Can't revert to previous version easily
- **Unclear versioning**: Don't know which SHA is actually running
- **Cache issues**: Kubernetes may not pull if tag hasn't changed

**SHA tags solve this**:
- ✅ Unique per build (no collisions)
- ✅ Immutable (same SHA = same image)
- ✅ Easy rollback (just set image to previous SHA)
- ✅ Clear audit trail (know exactly what's running)

---

## Verification

### Check Current CronJob Images

```bash
kubectl get cronjobs -n production -o wide
```

**Before fix**:
```
mizzou-crawler    crawler:7f172f9  (old, stuck)
mizzou-discovery  crawler:7f172f9  (old, stuck)
```

**After next build**:
```
mizzou-crawler    crawler:abc123f  (new SHA from latest build)
mizzou-discovery  crawler:abc123f  (new SHA from latest build)
```

### Verify Image Update

After triggering a crawler build:

```bash
# Check the build output
gcloud builds list --limit=1

# Verify cronjob image was updated
kubectl get cronjob mizzou-crawler -n production -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'

# Should output: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/crawler:<NEW_SHA>
```

---

## Architecture Pattern

This matches the pattern used by other services:

| Service | Build Config | Deployment Method | Auto-Update |
|---------|-------------|-------------------|-------------|
| API | `cloudbuild-api.yaml` | Deployment + kubectl set image | ✅ Yes |
| Processor | `cloudbuild-processor.yaml` | Deployment + kubectl set image | ✅ Yes |
| **Crawler** | `cloudbuild-crawler.yaml` | CronJob + kubectl set image | ✅ **NOW FIXED** |

---

## Benefits

1. ✅ **No manual intervention**: CronJobs update automatically on build
2. ✅ **Consistent with other services**: Uses same pattern as API/Processor
3. ✅ **Audit trail**: Each build's SHA is tracked in cronjob spec
4. ✅ **Graceful handling**: Discovery cronjob update is conditional (won't fail if missing)
5. ✅ **Next run uses new code**: No need to wait for manual update

---

## Testing

### Before Deploying Fix

```bash
# Note current image SHA
kubectl get cronjob mizzou-crawler -n production -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'
# Output: crawler:7f172f9
```

### After Deploying Fix

```bash
# Trigger a new crawler build
gcloud builds triggers run build-crawler-manual --branch=feature/gcp-kubernetes-deployment

# Wait for build to complete (~2-3 minutes)

# Check if cronjob image was updated
kubectl get cronjob mizzou-crawler -n production -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'
# Output: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/crawler:<NEW_SHA>
```

---

## Rollback

If an issue occurs with the new image, rollback is simple:

```bash
# Find previous working SHA
kubectl rollout history cronjob/mizzou-crawler -n production

# Set image back to previous SHA
kubectl set image cronjob/mizzou-crawler \
  crawler=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/crawler:<OLD_SHA> \
  --namespace=production
```

---

## Future Improvements

1. **Add to processor cronjob**: Apply same pattern to `mizzou-processor` cronjob
2. **Automated testing**: Run smoke tests after image update before next cronjob
3. **Slack notifications**: Alert when cronjobs are updated with new images
4. **Version tracking**: Store SHA tags in ConfigMap for easy reference

---

## Files Modified

1. `cloudbuild-crawler.yaml` - Added kubectl set image steps
2. `k8s/crawler-cronjob.yaml` - Fixed image reference to use full registry path

---

## Related Documentation

- `DATASET_RENAME_COMPLETE.md` - Dataset rename that triggered this discovery
- `cloudbuild-processor.yaml` - Reference implementation for deployment pattern
- `cloudbuild-api.yaml` - Another reference for kubectl set image pattern

---

**Issue Resolved**: CronJobs now automatically update to use newly built images without manual intervention! 🎉
