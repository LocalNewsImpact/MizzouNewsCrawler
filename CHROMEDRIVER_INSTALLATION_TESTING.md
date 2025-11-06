# ChromeDriver Installation Testing Guide

## Overview

This document provides step-by-step testing procedures for the ChromeDriver installation script (`scripts/install-chromedriver.sh`) to ensure it works correctly before deploying to production.

**Context:** Previous attempts at ChromeDriver installation failed. This testable approach allows validation at each stage.

**Related Issue:** #165 - Extraction Workflow Errors

---

## Testing Phases

### Phase 1: Local Script Testing (Completed ✅)

**Purpose:** Verify script logic and error handling

**Location:** Any environment with bash

**Commands:**
```bash
cd /path/to/MizzouNewsCrawler
bash scripts/test-chromedriver-install.sh
```

**Expected Outcome:**
- Script executes without syntax errors
- Proper error handling demonstrated
- Clear logging output

**Status:** ✅ Completed - Script logic verified

**Note:** Download may fail in restricted environments (sandbox, no internet). This is expected and doesn't indicate a problem with the script.

---

### Phase 2: Docker Build Testing (REQUIRED ⚠️)

**Purpose:** Verify ChromeDriver installation works in actual Docker build

**Prerequisites:**
- Docker installed locally OR access to Cloud Build
- Internet access for downloading ChromeDriver

#### Option A: Local Docker Build

**Commands:**
```bash
cd /path/to/MizzouNewsCrawler

# Build crawler image
docker build -f Dockerfile.crawler -t test-crawler:chromedriver-fix .

# Verify build succeeded
echo $?  # Should be 0

# Check ChromeDriver in container
docker run test-crawler:chromedriver-fix chromedriver --version
docker run test-crawler:chromedriver-fix ls -la /app/bin/chromedriver
docker run test-crawler:chromedriver-fix cat /etc/os-release
```

**Expected Output:**
```
ChromeDriver 130.x.x.x (or matching Chromium version)
-rwxr-xr-x 1 appuser appuser [size] [date] /app/bin/chromedriver
```

**Success Criteria:**
- ✅ Build completes without errors
- ✅ ChromeDriver binary exists at /app/bin/chromedriver
- ✅ Binary is executable (has execute permissions)
- ✅ `chromedriver --version` runs successfully

#### Option B: Cloud Build Testing

**Commands:**
```bash
# Trigger build on feature branch
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=BRANCH_NAME=copilot/fix-selenium-chromedriver-error \
  .

# Monitor build progress
gcloud builds list --ongoing

# Get build ID from output, then check logs
BUILD_ID="[your-build-id]"
gcloud builds log $BUILD_ID | grep -i chromedriver
```

**Expected Log Output:**
```log
Step #X: [INFO] ChromeDriver installation starting...
Step #X: [INFO] Install directory: /app/bin
Step #X: [INFO] Detected Chromium version: 130.x.x.x (major: 130)
Step #X: [INFO] Download attempt 1/3
Step #X: [INFO] Attempting Chrome for Testing download: https://storage.googleapis.com/...
Step #X: [INFO] Extracting ChromeDriver...
Step #X: [INFO] Extracted with subdirectory pattern
Step #X: [INFO] Installing ChromeDriver to /app/bin/chromedriver
Step #X: ✓ ChromeDriver installed successfully: ChromeDriver 130.x.x.x
Step #X: ✓ ChromeDriver installation complete
```

**Failure Indicators to Watch For:**
```log
[ERROR] Failed to download ChromeDriver after 3 attempts
[ERROR] ChromeDriver binary not found after extraction
[ERROR] ChromeDriver not executable
[ERROR] ChromeDriver fails to execute
```

**Success Criteria:**
- ✅ Build completes successfully
- ✅ No ERROR messages in ChromeDriver installation section
- ✅ See "✓ ChromeDriver installed successfully" message
- ✅ Image pushed to Artifact Registry

---

### Phase 3: Container Verification (REQUIRED ⚠️)

**Purpose:** Verify ChromeDriver works in actual container environment

**Prerequisites:**
- Successfully built Docker image from Phase 2

#### Local Container Testing

**Commands:**
```bash
# Start interactive shell in container
docker run -it test-crawler:chromedriver-fix /bin/bash

# Inside container, run these commands:
$ whoami  # Should be: appuser
$ ls -la /app/bin/chromedriver
$ chromedriver --version
$ chromium --version
$ echo $CHROMEDRIVER_PATH
$ echo $CHROME_BIN
$ python3 -c "import os; print('CHROMEDRIVER_PATH:', os.environ.get('CHROMEDRIVER_PATH'))"
```

**Expected Output:**
```
appuser
-rwxr-xr-x 1 appuser appuser [size] /app/bin/chromedriver
ChromeDriver 130.x.x.x
Chromium 130.x.x.x
/app/bin/chromedriver
/usr/bin/chromium
CHROMEDRIVER_PATH: /app/bin/chromedriver
```

#### GKE Pod Testing (After Deployment)

**Commands:**
```bash
# Find a crawler pod
kubectl get pods -l app=crawler -n production

# Exec into pod
kubectl exec -it [pod-name] -n production -- /bin/bash

# Run same verification commands as above
```

---

### Phase 4: Selenium Integration Testing (POST-DEPLOYMENT)

**Purpose:** Verify Selenium actually uses the installed ChromeDriver

**Location:** Production/Staging Argo workflows

**Monitoring Commands:**
```bash
# Watch Selenium extraction attempts
kubectl logs -f -l workflow=extraction -n production | grep -i "selenium\|chromedriver"

# Check for successful Selenium extractions
kubectl logs -l workflow=extraction -n production --tail=1000 | grep "Selenium extraction succeeded"

# Check for ChromeDriver errors
kubectl logs -l workflow=extraction -n production --tail=1000 | grep -i "no such file or directory.*chromedriver"
```

**Expected Logs (Success):**
```log
2025-11-06 18:00:00 - Creating new persistent ChromeDriver for reuse
2025-11-06 18:00:01 - patching driver executable /app/bin/chromedriver
2025-11-06 18:00:05 - ✅ Selenium extraction succeeded for [URL]
```

**Failure Logs (If Still Broken):**
```log
2025-11-06 18:00:00 - Failed to create undetected driver: [Errno 2] No such file or directory: '/app/bin/chromedriver'
2025-11-06 18:00:00 - ERROR - Selenium extraction failed
```

**Success Criteria:**
- ✅ See "patching driver executable /app/bin/chromedriver" messages
- ✅ No "[Errno 2] No such file or directory" errors
- ✅ Some successful Selenium extractions (✅ messages)
- ✅ Extraction success rate increases from ~83% to ~95%

---

## Troubleshooting Guide

### Issue: Build Fails at ChromeDriver Installation

**Symptoms:**
```log
[ERROR] Failed to download ChromeDriver after 3 attempts
```

**Possible Causes:**
1. Network connectivity issues in build environment
2. Chrome for Testing URLs changed
3. ChromeDriver version not available

**Debugging Steps:**
```bash
# Test download manually
wget --spider "https://storage.googleapis.com/chrome-for-testing-public/130.0.0.0/linux64/chromedriver-linux64.zip"

# Try legacy URL
wget --spider "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_130"

# Check if Chromium version is too new
chromium --version
```

**Solution:**
- Update script URLs if Chrome for Testing structure changed
- Add more fallback URLs
- Use known working version if latest is broken

### Issue: ChromeDriver Downloaded but Not Executable

**Symptoms:**
```log
[ERROR] ChromeDriver not executable: /app/bin/chromedriver
```

**Possible Causes:**
1. Permissions not set correctly
2. Binary corrupted during download
3. Wrong architecture (e.g., ARM vs x86_64)

**Debugging Steps:**
```bash
# Check permissions
ls -la /app/bin/chromedriver

# Check file type
file /app/bin/chromedriver

# Try to run
/app/bin/chromedriver --version
```

**Solution:**
- Add explicit `chmod +x` in script
- Verify download integrity (checksum)
- Ensure downloading linux64 version

### Issue: ChromeDriver Installed but Selenium Fails

**Symptoms:**
- ChromeDriver binary exists and is executable
- Selenium still fails with "Unable to obtain driver"

**Possible Causes:**
1. Chrome/ChromeDriver version mismatch
2. Missing Chrome binary
3. Chrome requires libraries not in container

**Debugging Steps:**
```bash
# Check versions match
chromium --version
chromedriver --version

# Check Chrome location
which chromium
echo $CHROME_BIN

# Try running Chrome
chromium --version --no-sandbox
```

**Solution:**
- Ensure ChromeDriver major version matches Chrome major version
- Verify CHROME_BIN environment variable is set correctly
- Check Chromium dependencies are installed

---

## Test Results Log

### Test Run 1: Local Script Testing

**Date:** 2025-11-06  
**Environment:** Sandbox (limited internet)  
**Result:** ⚠️ Download failed (expected - network restrictions)  
**Status:** Script logic verified ✅

**Notes:**
- Script executed without syntax errors
- Error handling worked correctly
- Proper fallback and retry logic observed

### Test Run 2: Docker Build Testing

**Date:** [To be filled]  
**Environment:** [Local Docker / Cloud Build]  
**Result:** [Success / Failure]  
**Status:** [Pending]

**Notes:**
[To be filled after testing]

### Test Run 3: Container Verification

**Date:** [To be filled]  
**Environment:** [Local container / GKE pod]  
**Result:** [Success / Failure]  
**Status:** [Pending]

**Notes:**
[To be filled after testing]

### Test Run 4: Production Selenium Testing

**Date:** [To be filled]  
**Environment:** Production Argo workflows  
**Result:** [Success / Failure]  
**Status:** [Pending]

**Metrics:**
- Extraction success rate before: ~83%
- Extraction success rate after: [To be measured]
- Selenium extractions per run: [To be measured]

---

## Approval Checklist

Before merging this PR, ensure:

- [ ] Phase 2: Docker build completes successfully
- [ ] Phase 3: ChromeDriver binary verified in container
- [ ] ChromeDriver version matches Chromium version
- [ ] Binary is owned by appuser with execute permissions
- [ ] Environment variables are set correctly
- [ ] Optional: Local Selenium test passes (if Chrome available)
- [ ] Code review approved
- [ ] Test results documented above

**Sign-off:**
- Developer: [Your name]
- Reviewer: @dkiesow
- Date: [Date of approval]

---

## Related Documentation

- [Issue #165](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/165) - Original issue
- [ISSUE_165_FIX_SUMMARY.md](ISSUE_165_FIX_SUMMARY.md) - Comprehensive fix documentation
- [COPILOT_SESSION_SUMMARY.md](COPILOT_SESSION_SUMMARY.md) - Session details
- [docs/troubleshooting/CHROME_CONTAINER_FIX.md](docs/troubleshooting/CHROME_CONTAINER_FIX.md) - Previous Chrome fixes
- [docs/troubleshooting/SELENIUM_FALLBACK_FIX.md](docs/troubleshooting/SELENIUM_FALLBACK_FIX.md) - Selenium configuration

---

## Summary

This testing guide provides a comprehensive framework for validating the ChromeDriver installation fix. The key innovation is the testable script approach, which allows validation at each stage rather than discovering failures only after full deployment.

**Critical Success Factor:** Phase 2 (Docker Build Testing) MUST pass before merging to main.

**Next Steps:**
1. Run Phase 2 testing in environment with internet access
2. Document results in this file
3. Address any issues found
4. Get code review approval
5. Merge and deploy
6. Monitor Phase 4 production metrics
