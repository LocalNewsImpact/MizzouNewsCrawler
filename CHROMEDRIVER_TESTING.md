# ChromeDriver Installation Testing

## Problem

ChromeDriver installation was failing in production with version mismatches (v114 vs v142). Previous attempts to fix this involved pushing changes directly to production without proper testing.

## Solution: Test Before Deploy

We now have **automated testing** at multiple levels:

### 1. Local Testing (Before Commit)

Test the installation script locally:

```bash
# Quick test - just run the script
bash scripts/install-chromedriver.sh /tmp/test-chromedriver

# Full test - build Docker image
docker build -f Dockerfile.crawler -t test-crawler:local .
docker run --rm test-crawler:local bash -c "chromium --version && /app/bin/chromedriver --version"
```

### 2. CI Testing (On Pull Request)

**Workflow: `.github/workflows/test-chromedriver.yml`**

Automatically runs on PRs that change:
- `scripts/install-chromedriver.sh`
- `Dockerfile.crawler`
- The workflow file itself

**Two test jobs:**

#### Job 1: Script Test (Fast - ~2 minutes)
- Installs Chromium on Ubuntu runner
- Runs install-chromedriver.sh
- Verifies ChromeDriver is installed
- Checks version compatibility (within 5 major versions)

#### Job 2: Docker Build Test (Slower - ~5 minutes)
- Builds minimal Docker image with Chromium + ChromeDriver
- Verifies both are installed and versions match
- **Tests actual Selenium initialization** - proves it works end-to-end

### 3. Manual Docker Testing

Use the test script:

```bash
# Run full Docker build test
bash scripts/test-chromedriver-docker.sh
```

This creates a minimal test image and verifies:
- Chromium installs successfully
- ChromeDriver installs successfully
- Versions are compatible (within 5 major versions)
- Prints actual version numbers

## Version Compatibility Rules

**Acceptable:** ChromeDriver within ±5 major versions of Chrome
- Chrome 142 + ChromeDriver 138-147 ✅
- Chrome 142 + ChromeDriver 114 ❌ (28 versions apart!)

**Why?** ChromeDriver is typically backward and forward compatible within ~5 major versions. This handles:
- ChromeDriver releases lagging behind Chrome (common)
- ChromeDriver releases ahead of installed Chrome (rare but happens)

## Understanding the Script

`scripts/install-chromedriver.sh` has three download strategies:

### Strategy 1: Chrome for Testing (Preferred)
```bash
https://storage.googleapis.com/chrome-for-testing-public/${MAJOR}.0.0.0/linux64/chromedriver-linux64.zip
```
- Google's official ChromeDriver distribution
- Matches Chrome releases exactly when available
- **May not have bleeding-edge versions** (e.g., v142 not available yet)

### Strategy 2: Legacy ChromeDriver Storage
```bash
https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${MAJOR}
```
- Older ChromeDriver hosting
- More versions available
- Being phased out by Google

### Strategy 3: Latest Stable (Last Resort)
```bash
https://chromedriver.storage.googleapis.com/LATEST_RELEASE
```
- Gets the absolute latest stable release
- **May be very old** (e.g., v114 when Chrome is v142)
- Only used if strategies 1 and 2 fail

### Fallback Logic (NEW)

Each strategy now tries multiple versions:
1. Exact major version (e.g., 142)
2. N-1 version (141)
3. N-2 version (140)
4. N-3 version (139)
5. N-4 version (138)

This handles cases where ChromeDriver releases lag behind Chrome releases.

## Common Issues

### Issue: "403 Forbidden" from Chrome for Testing

**Symptom:**
```log
[INFO] Attempting Chrome for Testing download: .../142.0.0.0/...
[WARN] Chrome for Testing doesn't have v142, trying recent versions...
```

**Cause:** Google hasn't released ChromeDriver for this Chrome version yet.

**Solution:** Fallback logic tries recent versions (141, 140, 139, etc.)

### Issue: Network restrictions in CI/build environment

**Symptom:**
```log
[ERROR] Failed to download ChromeDriver after 3 attempts
```

**Cause:** Build environment blocks external downloads

**Solution:** 
- Pre-cache ChromeDriver in base image
- Use organization's artifact registry
- Allow download domains in firewall

### Issue: Docker layer caching causes stale ChromeDriver

**Symptom:** Old ChromeDriver version despite script changes

**Cause:** Docker cached the RUN layer with old download

**Solution:**
```bash
# Force rebuild without cache
docker build --no-cache -f Dockerfile.crawler -t crawler:test .

# Or in Cloud Build, trigger with --no-cache flag
gcloud builds submit --config=cloudbuild.yaml --no-cache
```

## Deployment Process (NEW - Test First!)

### Step 1: Make Changes
```bash
# Edit the script
vi scripts/install-chromedriver.sh

# Edit Dockerfile if needed
vi Dockerfile.crawler
```

### Step 2: Test Locally
```bash
# Quick test
bash scripts/install-chromedriver.sh /tmp/test

# Docker test
bash scripts/test-chromedriver-docker.sh
```

### Step 3: Create PR
```bash
git checkout -b fix/chromedriver-issue
git add scripts/install-chromedriver.sh
git commit -m "Fix ChromeDriver installation"
git push origin fix/chromedriver-issue
# Create PR on GitHub
```

### Step 4: Wait for CI
- GitHub Actions runs test-chromedriver.yml
- Both jobs must pass (script test + Docker test)
- Review test logs to see actual versions installed

### Step 5: Merge and Deploy
```bash
# After PR approval and CI passing
git checkout main
git pull

# Trigger Cloud Build
gcloud builds triggers run build-crawler-manual --branch=main

# Monitor build
gcloud builds list --ongoing

# Check build logs for ChromeDriver version
BUILD_ID="<your-build-id>"
gcloud builds log $BUILD_ID | grep -A5 "ChromeDriver"
```

### Step 6: Verify in Production
```bash
# Exec into crawler pod
POD=$(kubectl get pod -l app=crawler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $POD -- bash

# Inside pod:
chromium --version
/app/bin/chromedriver --version

# Check they're compatible (within 5 major versions)
```

## Monitoring

After deployment, monitor for these errors:

### ✅ Good Signs
```log
Creating new persistent ChromeDriver for reuse
patching driver executable /app/bin/chromedriver
✅ Selenium extraction succeeded for <URL>
```

### ❌ Bad Signs
```log
This version of ChromeDriver only supports Chrome version X
Current browser version is Y
Failed to create undetected driver
Selenium extraction failed
```

## Rollback Plan

If ChromeDriver issues appear in production:

```bash
# Option 1: Rollback crawler deployment
kubectl rollout undo deployment/crawler

# Option 2: Use previous image tag
kubectl set image deployment/crawler \
  crawler=us-central1-docker.pkg.dev/.../crawler:<previous-tag>

# Option 3: Quick fix - disable Selenium in Argo workflows
# Edit extraction step environment variables:
- name: DISABLE_SELENIUM
  value: "true"
```

## Future Improvements

1. **Cache ChromeDriver binaries** in GCS bucket
   - Faster builds
   - Reliable even when Google's CDN is slow
   - Version pinning for reproducibility

2. **Version compatibility matrix** in CI
   - Test multiple Chrome + ChromeDriver combinations
   - Document which versions work together

3. **Automated version detection** from production
   - Script that checks production pods
   - Reports version mismatches
   - Sends alerts if difference >5 major versions

4. **Pre-deployment validation** job
   - Runs before promoting to production
   - Verifies ChromeDriver works with actual extraction code
   - Tests on sample URLs

## Summary

**Old workflow:** Change script → Push to production → Hope it works → Debug in production

**New workflow:** Change script → Test locally → CI validates → Review logs → Merge → Monitor production

The key: **Never push ChromeDriver changes without seeing them work in Docker first.**
