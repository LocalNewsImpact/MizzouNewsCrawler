# Base Image Maintenance Guide

This guide explains how to maintain the shared base Docker image used across all MizzouNewsCrawler services.

## Table of Contents

- [Overview](#overview)
- [When to Rebuild](#when-to-rebuild)
- [Local Rebuild Procedure](#local-rebuild-procedure)
- [Cloud Rebuild Procedure](#cloud-rebuild-procedure)
- [Testing](#testing)
- [Rollback Procedure](#rollback-procedure)
- [Version Strategy](#version-strategy)
- [Troubleshooting](#troubleshooting)

---

## Overview

The shared base image (`mizzou-base`) contains common dependencies used by all services:

**Contains:**
- System packages: gcc, g++, libpq-dev, wget, ca-certificates
- Common Python packages: pandas, sqlalchemy, spacy, pytest, etc. (~50 packages)
- Spacy model: en_core_web_sm
- Non-root user: appuser (UID 1000)

**Benefits:**
- Reduces build time from 15 minutes to 2-3 minutes per service (83% reduction)
- Eliminates redundant dependency installation
- Better Docker layer caching
- Lower Cloud Build costs

**Services using base image:**
- API (`Dockerfile.api`)
- Processor (`Dockerfile.processor`)
- Crawler (`Dockerfile.crawler`)

---

## When to Rebuild

Rebuild the base image when:

### Critical (Rebuild Immediately)
- [ ] Security vulnerabilities in base packages
- [ ] Database driver updates (psycopg2, sqlalchemy)
- [ ] Python version upgrade

### Important (Rebuild Soon)
- [ ] Adding new common dependencies to `requirements-base.txt`
- [ ] Removing obsolete packages from `requirements-base.txt`
- [ ] Spacy model version update
- [ ] System package updates

### Routine (Quarterly)
- [ ] Quarterly maintenance (every 3 months)
- [ ] Security patch updates
- [ ] Dependency version bumps

### Not Required
- ❌ Changes to service-specific requirements (api/processor/crawler)
- ❌ Application code changes
- ❌ Configuration changes

---

## Local Rebuild Procedure

### 1. Update Dependencies

Edit `requirements-base.txt`:

```bash
# Add or update packages
vim requirements-base.txt
```

**Example changes:**
```diff
# requirements-base.txt
- pandas>=2.0.0
+ pandas>=2.1.0  # Upgrade version
+ new-common-package>=1.0.0  # Add new package
```

### 2. Test Locally

Build the base image:

```bash
# Build base image
docker build -t mizzou-base:test -f Dockerfile.base .

# Verify packages installed
docker run --rm mizzou-base:test pip list | grep pandas

# Test spacy model
docker run --rm mizzou-base:test python -c "import spacy; nlp = spacy.load('en_core_web_sm'); print('Spacy OK')"

# Check image size
docker images | grep mizzou-base
# Expected: ~1.2-1.5 GB
```

### 3. Build Service Images

Test that services can build from the new base:

```bash
# Build all services
docker build -t mizzou-api:test -f Dockerfile.api .
docker build -t mizzou-processor:test -f Dockerfile.processor .
docker build -t mizzou-crawler:test -f Dockerfile.crawler .

# Verify build times
# Expected: ~2-3 minutes per service (first build)
# Expected: <1 minute (subsequent builds with cache)
```

### 4. Test Services

Run services locally:

```bash
# Build base first
docker-compose --profile base build base

# Build and run services
docker-compose build
docker-compose up -d

# Test API
curl http://localhost:8000/health

# Test crawler
docker-compose run --rm crawler python -m src.cli.main --help

# Test processor
docker-compose run --rm processor python -m src.cli.main --help
```

### 5. Commit Changes

If all tests pass:

```bash
git add requirements-base.txt Dockerfile.base
git commit -m "Update base image: [describe changes]"
git push
```

---

## Cloud Rebuild Procedure

### Prerequisites

- [ ] Changes committed and pushed to GitHub
- [ ] Local testing completed successfully
- [ ] Team notified of upcoming rebuild
- [ ] No active deployments in progress

### 1. Trigger Base Image Build

```bash
# Option 1: Manual trigger (recommended)
gcloud builds triggers run build-base-manual

# Option 2: Direct submit
gcloud builds submit --config=cloudbuild-base.yaml
```

### 2. Monitor Build

```bash
# Watch build progress
gcloud builds list --ongoing

# Or view in console
# https://console.cloud.google.com/cloud-build/builds
```

**Expected duration:**
- First build: 10-15 minutes
- Subsequent builds (with cache): 5-8 minutes

### 3. Verify Base Image

```bash
# List available base images
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base

# Expected output:
# base:latest
# base:<git-sha>
```

### 4. Rebuild Services

After base image completes, rebuild all services:

```bash
# Trigger service builds
gcloud builds triggers run build-api-manual
gcloud builds triggers run build-processor-manual
gcloud builds triggers run build-crawler-manual
```

**Expected duration:** 2-3 minutes per service

### 5. Monitor Deployment

```bash
# Check Cloud Deploy releases
gcloud deploy releases list \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1

# Monitor pod rollout
kubectl get pods -n production -w
```

### 6. Verify Services

```bash
# Check pod status
kubectl get pods -n production

# Test API
kubectl port-forward -n production svc/mizzou-api 8000:8000
curl http://localhost:8000/health

# Check logs
kubectl logs -n production -l app=mizzou-api --tail=50
kubectl logs -n production -l app=mizzou-processor --tail=50
kubectl logs -n production -l app=mizzou-crawler --tail=50
```

---

## Testing

### Unit Tests

No specific unit tests for base image. Verify by:

1. **Import Test**: All packages can be imported
   ```bash
   docker run --rm mizzou-base:test python -c "
   import pandas
   import sqlalchemy
   import spacy
   import pytest
   print('All imports OK')
   "
   ```

2. **Spacy Model Test**:
   ```bash
   docker run --rm mizzou-base:test python -c "
   import spacy
   nlp = spacy.load('en_core_web_sm')
   doc = nlp('This is a test.')
   assert len(doc) == 5
   print('Spacy OK')
   "
   ```

### Integration Tests

Run full test suite with new base image:

```bash
# Build all images
docker-compose build

# Run tests
docker-compose run --rm api pytest tests/ -v

# Or run specific test categories
pytest tests/test_actual_telemetry.py -v
pytest tests/crawler/ -v
```

### Performance Tests

Measure build times:

```bash
# Clear Docker cache
docker system prune -af

# Time base build
time docker build -t mizzou-base:perf -f Dockerfile.base .
# Expected: 5-10 minutes

# Time service builds (with base cached)
time docker build -t mizzou-api:perf -f Dockerfile.api .
# Expected: 2-3 minutes

time docker build -t mizzou-processor:perf -f Dockerfile.processor .
# Expected: 2-3 minutes

time docker build -t mizzou-crawler:perf -f Dockerfile.crawler .
# Expected: 2-3 minutes
```

---

## Rollback Procedure

If the new base image causes issues:

### Quick Rollback (5 minutes)

Revert to previous base image tag:

```bash
# 1. Find previous working version
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base \
  --format="table(IMAGE,TAGS,CREATE_TIME)" \
  --sort-by=~CREATE_TIME

# 2. Tag old version as latest
OLD_SHA="<previous-working-sha>"
gcloud artifacts docker tags add \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base:${OLD_SHA} \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base:latest

# 3. Rebuild services with old base
gcloud builds triggers run build-api-manual
gcloud builds triggers run build-processor-manual
gcloud builds triggers run build-crawler-manual

# 4. Monitor deployment
kubectl get pods -n production -w
```

### Code Rollback (15 minutes)

Revert code changes and rebuild:

```bash
# 1. Find commit to revert
git log --oneline Dockerfile.base requirements-base.txt

# 2. Revert changes
git revert <commit-hash>
git push

# 3. Rebuild base image
gcloud builds triggers run build-base-manual

# 4. Wait for base build (~10 minutes)
gcloud builds list --ongoing

# 5. Rebuild services
gcloud builds triggers run build-api-manual
gcloud builds triggers run build-processor-manual
gcloud builds triggers run build-crawler-manual
```

### Emergency Rollback (2 minutes)

Deploy previous service versions directly:

```bash
# Find previous working release
gcloud deploy releases list \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --filter="state=SUCCEEDED" \
  --limit=5

# Promote previous release
gcloud deploy releases promote \
  --release=<previous-release-name> \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --to-target=production
```

---

## Version Strategy

### Tagging

Base images are tagged with:

| Tag | Purpose | Example | Mutable |
|-----|---------|---------|---------|
| `latest` | Current production version | `base:latest` | Yes |
| `<git-sha>` | Specific commit version | `base:39b1f08` | No |
| `<version>` | Semantic version | `base:v1.2` | No |

### Service References

**Local Development:**
```dockerfile
ARG BASE_IMAGE=mizzou-base:latest
FROM ${BASE_IMAGE}
```

**Production (Cloud Build):**
```yaml
substitutions:
  _BASE_IMAGE: us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/base:latest
```

**Pinned Version (optional):**
```yaml
substitutions:
  _BASE_IMAGE: us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/base:39b1f08
```

### Version Numbering

Use semantic versioning for major changes:

- **v1.0**: Initial base image
- **v1.1**: Minor updates (package version bumps)
- **v1.2**: New packages added
- **v2.0**: Breaking changes (Python version, major refactor)

```bash
# Tag version after successful build
docker tag mizzou-base:latest mizzou-base:v1.2

# Or in Cloud Build
gcloud artifacts docker tags add \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base:latest \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base:v1.2
```

---

## Troubleshooting

### Issue: Base image not found

**Symptoms:**
```
Error: base:latest not found
```

**Solutions:**

1. **Build locally:**
   ```bash
   docker build -t mizzou-base:latest -f Dockerfile.base .
   ```

2. **Pull from Artifact Registry:**
   ```bash
   gcloud auth configure-docker us-central1-docker.pkg.dev
   docker pull us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base:latest
   docker tag us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/base:latest mizzou-base:latest
   ```

### Issue: Package conflicts

**Symptoms:**
```
ERROR: Cannot install package-a and package-b because these package versions have conflicting dependencies
```

**Solutions:**

1. **Check version constraints:**
   ```bash
   # Review requirements-base.txt
   vim requirements-base.txt
   
   # Loosen version constraints
   # Bad: package==1.2.3
   # Good: package>=1.2.0,<2.0.0
   ```

2. **Test dependency resolution:**
   ```bash
   python -m venv test-env
   source test-env/bin/activate
   pip install -r requirements-base.txt
   ```

3. **Remove conflicting package** from base and move to service-specific requirements

### Issue: Base image too large

**Symptoms:**
```
Image size: 2.5 GB (expected: 1.2-1.5 GB)
```

**Solutions:**

1. **Check installed packages:**
   ```bash
   docker run --rm mizzou-base:test pip list | wc -l
   # Expected: ~50-60 packages
   ```

2. **Remove unnecessary packages:**
   ```bash
   # Move large service-specific packages to service requirements
   # e.g., torch, transformers -> requirements-processor.txt
   ```

3. **Clean up build artifacts:**
   ```dockerfile
   # In Dockerfile.base, add cleanup
   RUN pip install --no-cache-dir -r requirements-base.txt && \
       rm -rf /root/.cache /tmp/*
   ```

### Issue: Slow base image builds

**Symptoms:**
```
Base image takes 20+ minutes to build
```

**Solutions:**

1. **Use Cloud Build machine type:**
   ```yaml
   # cloudbuild-base.yaml
   options:
     machineType: 'N1_HIGHCPU_8'  # More CPU = faster pip installs
   ```

2. **Optimize Dockerfile layer caching:**
   ```dockerfile
   # Copy requirements first (changes rarely)
   COPY requirements-base.txt .
   RUN pip install -r requirements-base.txt
   
   # Copy code last (changes frequently)
   COPY src/ ./src/
   ```

3. **Build locally and push:**
   ```bash
   docker build -t mizzou-base:local -f Dockerfile.base .
   docker tag mizzou-base:local us-central1-docker.pkg.dev/.../base:latest
   docker push us-central1-docker.pkg.dev/.../base:latest
   ```

### Issue: Service build fails with base image

**Symptoms:**
```
Error: module 'numpy' has no attribute 'something'
```

**Solutions:**

1. **Clear Docker cache:**
   ```bash
   docker system prune -af
   docker volume prune -f
   ```

2. **Rebuild base image:**
   ```bash
   docker build --no-cache -t mizzou-base:latest -f Dockerfile.base .
   ```

3. **Check package versions:**
   ```bash
   docker run --rm mizzou-base:latest pip list | grep numpy
   ```

---

## Maintenance Checklist

### Monthly
- [ ] Review security advisories for base packages
- [ ] Check for critical dependency updates

### Quarterly
- [ ] Review and update `requirements-base.txt`
- [ ] Test base image rebuild locally
- [ ] Update Python security patches
- [ ] Update spacy model if new version available
- [ ] Rebuild base image in Cloud
- [ ] Test all services with new base
- [ ] Document any issues encountered

### Annually
- [ ] Review base image architecture
- [ ] Consider Python version upgrade
- [ ] Evaluate new common dependencies
- [ ] Performance benchmark comparison
- [ ] Update this documentation

---

## Resources

- **Base Image Optimization Roadmap**: [docs/issues/shared-base-image-optimization.md](./issues/shared-base-image-optimization.md)
- **Docker Guide**: [docs/DOCKER_GUIDE.md](./DOCKER_GUIDE.md)
- **GitHub Issue**: [#38](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/38)
- **Cloud Build Docs**: https://cloud.google.com/build/docs
- **Docker Multi-stage Builds**: https://docs.docker.com/build/building/multi-stage/

---

## Contact

For questions or issues:
1. Open a GitHub issue
2. Contact DevOps team
3. Refer to troubleshooting section above

---

*Last updated: October 2025*
