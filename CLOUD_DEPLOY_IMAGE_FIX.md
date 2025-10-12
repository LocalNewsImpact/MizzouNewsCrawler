# Cloud Deploy Image Tag Substitution Fix

## Problem Statement

Cloud Deploy was reporting successful releases and rollouts, but production pods remained on previous image tags. The root cause was hard-coded image digests in Kubernetes manifests (e.g., `processor:0067e24`, `api:ab1178b`). Skaffold's `kubectl` deploy strategy does not replace these tags even when Cloud Deploy passes the `--images` flag during release creation.

### Symptoms
- Cloud Deploy releases show as successful
- Cloud Deploy rollouts show as successful
- Pods continue running old images
- Manual `kubectl set image` commands required after each deploy
- Bug fixes and updates stuck in CI/CD pipeline

## Solution

We implemented Kustomize-based manifest rendering to enable dynamic image tag substitution. This allows Cloud Deploy's `--images` flag to properly update container images during rollouts.

### Key Changes

1. **Created `k8s/kustomization.yaml`**
   - Defines base Kustomize configuration
   - Specifies image substitution rules
   - Sets namespace for all resources

2. **Updated Kubernetes Manifests**
   - Changed hard-coded image references to placeholders:
     - `processor:0067e24` → `processor`
     - `api:ab1178b` → `api`
     - `processor:d44fe7b` → `processor` (CLI deployment)
   - Manifests: `processor-deployment.yaml`, `api-deployment.yaml`, `cli-deployment.yaml`

3. **Updated `skaffold.yaml`**
   - Changed from `rawYaml` to `kustomize` for manifest rendering
   - Applied to both default and production profiles

### How It Works

1. **Build Phase** (Cloud Build):
   ```bash
   # Cloud Build creates images with SHORT_SHA tags
   us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/processor:${SHORT_SHA}
   us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/api:${SHORT_SHA}
   ```

2. **Release Phase** (Cloud Deploy):
   ```bash
   # Cloud Deploy creates release with --images flag
   gcloud deploy releases create release-${SHORT_SHA} \
     --delivery-pipeline=mizzou-news-crawler \
     --region=us-central1 \
     --images=processor=us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/processor:${SHORT_SHA},api=...
   ```

3. **Render Phase** (Skaffold + Kustomize):
   - Skaffold uses Kustomize to render manifests
   - Kustomize replaces placeholder image names with full references
   - Cloud Deploy's `--images` values override the default tags in `kustomization.yaml`

4. **Deploy Phase** (kubectl):
   - Rendered manifests with correct image tags applied to cluster
   - Kubernetes rolling update picks up new images automatically

## Verification

### Automated Verification Script

Use the provided script to verify deployments after a rollout:

```bash
# Check current deployment images
./scripts/verify_deployment_images.sh

# Check with expected tag (e.g., after release-abc123)
./scripts/verify_deployment_images.sh abc123
```

The script will:
- Show current images for processor, api, and cli deployments
- Verify running pods match deployment specs
- Compare against expected tag if provided
- Display rollout status

### Manual Verification

1. **Check Cloud Deploy Release**:
   ```bash
   gcloud deploy releases list \
     --delivery-pipeline=mizzou-news-crawler \
     --region=us-central1 \
     --limit=5
   ```

2. **Check Rollout Status**:
   ```bash
   gcloud deploy rollouts list \
     --delivery-pipeline=mizzou-news-crawler \
     --region=us-central1 \
     --release=RELEASE_NAME
   ```

3. **Verify Pod Images**:
   ```bash
   # Processor
   kubectl get deployment mizzou-processor -n production \
     -o jsonpath='{.spec.template.spec.containers[0].image}'
   
   # API
   kubectl get deployment mizzou-api -n production \
     -o jsonpath='{.spec.template.spec.containers[0].image}'
   ```

4. **Check Running Pods**:
   ```bash
   # Verify pods are running with new images
   kubectl get pods -n production -o wide
   
   # Describe a pod to see detailed image info
   kubectl describe pod -n production -l app=mizzou-processor
   ```

### Expected Behavior After Fix

✅ **Correct behavior**:
- Cloud Deploy release created with new image tags
- Skaffold renders manifests with new tags via Kustomize
- Rollout applies rendered manifests to cluster
- Pods automatically restart with new images
- `kubectl get deployment` shows new image tags
- No manual intervention required

❌ **Old behavior (before fix)**:
- Cloud Deploy release created
- Manifests applied with hard-coded old tags
- Pods remain on old images
- Manual `kubectl set image` required

## Testing

### Local Testing with Kustomize

Test the Kustomize configuration locally:

```bash
# Build manifests with Kustomize
cd k8s
kustomize build .

# Verify image substitution
kustomize build . | grep "image:"

# Test with custom image tags
kustomize build . | kustomize edit set image \
  processor=registry/processor:test123 \
  api=registry/api:test123
```

### Lab Environment Testing (Recommended)

Before deploying to production, test in an isolated namespace:

1. **Create Lab Namespace**:
   ```bash
   kubectl create namespace ci-cd-lab
   ```

2. **Copy and Modify Kustomize Config**:
   ```bash
   cp -r k8s k8s-lab
   cd k8s-lab
   # Update kustomization.yaml namespace to "ci-cd-lab"
   ```

3. **Create Test Pipeline**:
   - Duplicate Cloud Deploy pipeline config
   - Point to lab namespace
   - Deploy and verify image updates

4. **Validate**:
   ```bash
   # Check lab deployment
   kubectl get deployments -n ci-cd-lab
   
   # Verify image tags
   ./scripts/verify_deployment_images.sh
   export NAMESPACE=ci-cd-lab
   ./scripts/verify_deployment_images.sh abc123
   ```

## Deployment Steps

### 1. Merge Changes
```bash
# Review PR with these changes
# Merge to main branch
```

### 2. Trigger Build
```bash
# Manual trigger or wait for automatic trigger
gcloud builds submit --config=cloudbuild.yaml
```

### 3. Monitor Release
```bash
# Watch for automatic release creation
gcloud deploy releases list \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1

# Monitor rollout
gcloud deploy rollouts list \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --release=release-XXXXXX
```

### 4. Verify Deployment
```bash
# Run verification script
./scripts/verify_deployment_images.sh SHORT_SHA

# Check pod status
kubectl get pods -n production -w
```

## Rollback Plan

If issues occur after deployment:

### Quick Rollback
```bash
# Option 1: Rollback via Cloud Deploy
gcloud deploy targets rollback production \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1

# Option 2: Manual image update (temporary)
kubectl set image deployment/mizzou-processor \
  processor=us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/processor:OLD_TAG \
  -n production

kubectl set image deployment/mizzou-api \
  api=us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/api:OLD_TAG \
  -n production
```

### Revert Changes
```bash
# Revert commits if needed
git revert <commit-hash>
git push origin main

# Redeploy old configuration
gcloud builds submit --config=cloudbuild.yaml
```

## Troubleshooting

### Issue: Pods Still on Old Images After Rollout

**Diagnosis**:
```bash
# Check deployment spec
kubectl get deployment mizzou-processor -n production -o yaml | grep image:

# Check actual pod images
kubectl get pods -n production -o yaml | grep image:

# Check rollout history
kubectl rollout history deployment/mizzou-processor -n production
```

**Fix**:
```bash
# Force rollout restart
kubectl rollout restart deployment/mizzou-processor -n production
kubectl rollout restart deployment/mizzou-api -n production
```

### Issue: Kustomize Build Fails

**Diagnosis**:
```bash
# Test Kustomize locally
cd k8s
kustomize build .
```

**Common causes**:
- Invalid YAML syntax in manifests
- Missing referenced files in `kustomization.yaml`
- Incorrect image name format

### Issue: Cloud Deploy Release Fails

**Diagnosis**:
```bash
# Check release details
gcloud deploy releases describe RELEASE_NAME \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1

# Check build logs
gcloud builds log BUILD_ID
```

**Common causes**:
- Skaffold configuration errors
- Kustomize rendering issues
- Permission/RBAC problems

## Additional Notes

### Namespace Considerations
- All resources deploy to `production` namespace (defined in `kustomization.yaml`)
- Can be overridden with `kustomize edit set namespace`

### Image Pull Policy
- All deployments use `imagePullPolicy: Always`
- Ensures latest image is pulled even if tag matches

### Future Enhancements
- Add environment-specific overlays (staging, production)
- Implement canary deployments via Cloud Deploy
- Add automated smoke tests post-deployment

## References

- [GitHub Issue #72](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/72)
- [Skaffold Documentation](https://skaffold.dev/docs/)
- [Kustomize Documentation](https://kustomize.io/)
- [Cloud Deploy Documentation](https://cloud.google.com/deploy/docs)
