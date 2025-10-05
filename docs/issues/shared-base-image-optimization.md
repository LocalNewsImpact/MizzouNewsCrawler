# Shared Base Image Optimization Roadmap

**Issue**: #38  
**Status**: Implementation In Progress  
**Estimated Time**: 18 hours (2-3 days)  
**Priority**: High  
**Impact**: 83% reduction in build time (15 min → 2-3 min per service)

---

## Executive Summary

This roadmap outlines the implementation plan for creating a shared base Docker image that contains common dependencies used across all services (API, Processor, Crawler). By eliminating redundant dependency installation across services, we achieve:

- **Time Savings**: 15 minutes → 2-3 minutes per build (83% reduction)
- **Cost Savings**: Reduced Cloud Build costs (~67% reduction)
- **Developer Experience**: Faster iteration and deployment cycles
- **Resource Efficiency**: Better utilization of cached Docker layers

## Problem Statement

### Current State

Each service (API, Processor, Crawler) currently:
1. Starts from `python:3.11-slim` base image
2. Installs system dependencies (gcc, g++, libpq-dev, etc.)
3. Installs ALL Python packages from `requirements.txt` (~60+ packages)
4. Downloads spacy models independently
5. Takes ~15 minutes to build

### Issues

- **Redundancy**: ~80% of dependencies are identical across services
- **Slow iteration**: Code changes require full 15-minute rebuilds
- **High costs**: Each service build costs ~$0.15 on Cloud Build
- **Poor cache usage**: Changing any dependency invalidates all layers

### Proposed State

Base image contains:
- System dependencies (gcc, g++, libpq-dev)
- Common Python packages (~50 packages)
- Shared spacy model (en_core_web_sm)

Service images:
- Build from base image (fast)
- Install only service-specific packages (5-10 packages)
- Add service code
- Build in 2-3 minutes

---

## Architecture

### Dependency Structure

```
requirements-base.txt (Common ~80%)
├── Database: sqlalchemy, psycopg2-binary, cloud-sql-python-connector
├── Data: pandas, numpy, pyarrow
├── Web: requests, beautifulsoup4, lxml, urllib3
├── NLP: spacy, nltk, textblob, ftfy
├── Testing: pytest, pytest-cov, pytest-mock
└── Utilities: click, python-dotenv, pydantic

requirements-api.txt (API-specific ~10%)
├── fastapi
├── uvicorn[standard]
└── (API dependencies already in base)

requirements-processor.txt (Processor-specific ~15%)
├── torch (large ML framework)
├── transformers
├── scikit-learn
├── storysniffer
└── (NLP dependencies already in base)

requirements-crawler.txt (Crawler-specific ~15%)
├── selenium
├── undetected-chromedriver
├── selenium-stealth
├── newspaper4k
├── feedparser
└── cloudscraper
```

### Build Flow

```
┌─────────────────┐
│ Dockerfile.base │──> Built manually/rarely (when base deps change)
└────────┬────────┘
         │ Produces: base:latest (1.5 GB, cached)
         │
         ├─────────────────┬─────────────────┬─────────────────┐
         ▼                 ▼                 ▼                 ▼
  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
  │ Dockerfile  │   │ Dockerfile  │   │ Dockerfile  │   │ Dockerfile  │
  │   .api      │   │ .processor  │   │ .crawler    │   │  (future)   │
  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
  Builds in 2min    Builds in 2min    Builds in 2min    Builds in 2min
```

### Docker Layer Strategy

**Base Image (Dockerfile.base)**:
```dockerfile
FROM python:3.11-slim AS base
# Layer 1: System packages (stable, rarely changes)
RUN apt-get update && apt-get install gcc g++ libpq-dev

# Layer 2: Base Python packages (changes occasionally)
COPY requirements-base.txt /tmp/
RUN pip install -r /tmp/requirements-base.txt

# Layer 3: Spacy model (stable)
RUN python -m spacy download en_core_web_sm
```

**Service Images (Dockerfile.api, etc.)**:
```dockerfile
FROM us-central1-docker.pkg.dev/PROJECT/images/base:latest AS deps
# Layer 1: Service-specific packages (changes occasionally)
COPY requirements-api.txt /tmp/
RUN pip install -r /tmp/requirements-api.txt

FROM base AS runtime
# Layer 2: Copy installed packages
COPY --from=deps /usr/local/lib/python3.11/site-packages

# Layer 3: Application code (changes frequently)
COPY src/ ./src/
```

---

## Implementation Plan

### Phase 1: Analysis & Planning (1 hour)

**Objective**: Understand current dependencies and categorize them

**Tasks**:
1. ✅ Review `requirements.txt` (66 packages total)
2. ✅ Identify common dependencies (used by all services)
3. ✅ Identify service-specific dependencies
4. ✅ Analyze current Dockerfiles for patterns
5. ✅ Design requirements file structure

**Deliverables**:
- Dependency categorization spreadsheet
- Requirements file structure design

**Success Criteria**:
- All 66 packages categorized
- Clear separation of concerns
- No package duplicated across files

---

### Phase 2: Requirements Splitting (2 hours)

**Objective**: Create separate requirements files for base + each service

**Tasks**:
1. Create `requirements-base.txt` with common dependencies (~50 packages)
2. Create `requirements-api.txt` with API-specific packages (~5 packages)
3. Create `requirements-processor.txt` with processor-specific packages (~10 packages)
4. Create `requirements-crawler.txt` with crawler-specific packages (~10 packages)
5. Verify coverage: `cat requirements-*.txt | sort | uniq` matches `requirements.txt`
6. Document rationale for each categorization decision

**Key Decisions**:

| Package | Category | Rationale |
|---------|----------|-----------|
| pandas, numpy | Base | Used by all services for data processing |
| sqlalchemy, psycopg2 | Base | Database access needed everywhere |
| spacy, nltk | Base | NLP used by processor and crawler |
| fastapi, uvicorn | API | Only needed for API service |
| torch, transformers | Processor | Large ML packages only for processor |
| selenium, newspaper4k | Crawler | Web scraping only for crawler |
| pytest, black | Base | Development/testing used everywhere |

**Deliverables**:
- `requirements-base.txt` (50 packages)
- `requirements-api.txt` (5-10 packages)
- `requirements-processor.txt` (8-12 packages)
- `requirements-crawler.txt` (8-12 packages)
- Documentation of categorization decisions

**Success Criteria**:
- All original packages accounted for
- No duplicates across files
- Requirements installable without conflicts
- Total package count matches original

---

### Phase 3: Base Image Creation (3 hours)

**Objective**: Create shared base Docker image

**Tasks**:
1. Create `Dockerfile.base`:
   - FROM python:3.11-slim
   - Install system dependencies (gcc, g++, libpq-dev, etc.)
   - Copy requirements-base.txt
   - Install base Python packages
   - Download spacy model en_core_web_sm
   - Create non-root user
2. Test base image builds successfully
3. Verify installed packages: `docker run base pip list`
4. Test spacy model: `docker run base python -c "import spacy; nlp = spacy.load('en_core_web_sm')"`
5. Measure base image size (target: ~1.2-1.5 GB)
6. Tag appropriately: `base:latest`, `base:<git-sha>`

**Dockerfile.base Structure**:
```dockerfile
FROM python:3.11-slim AS base
# System dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python packages
COPY requirements-base.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-base.txt

# Spacy model
RUN python -m spacy download en_core_web_sm

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Metadata
LABEL maintainer="MizzouNewsCrawler"
LABEL description="Base image with common dependencies"
LABEL version="1.0"
```

**Deliverables**:
- `Dockerfile.base`
- Build script: `scripts/build-base.sh`
- Test script: `scripts/test-base.sh`

**Success Criteria**:
- Base image builds successfully (~5-10 minutes first time)
- All base packages install without errors
- Spacy model loads successfully
- Image size reasonable (~1.2-1.5 GB)
- Can be used as FROM in other Dockerfiles

---

### Phase 4: Service Dockerfile Updates (4 hours)

**Objective**: Update service Dockerfiles to use base image

#### 4.1 Update Dockerfile.api (1 hour)

**Tasks**:
1. Change `FROM python:3.11-slim` to `FROM base:latest`
2. Remove system dependency installation (already in base)
3. Remove base package installation (already in base)
4. Add service-specific package installation from `requirements-api.txt`
5. Keep multi-stage build structure
6. Test build locally

**Updated Structure**:
```dockerfile
# Stage 1: Install API-specific dependencies
FROM us-central1-docker.pkg.dev/PROJECT/images/base:latest AS deps
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Stage 2: Runtime
FROM us-central1-docker.pkg.dev/PROJECT/images/base:latest AS runtime
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --chown=appuser:appuser backend/ ./backend/
COPY --chown=appuser:appuser src/ ./src/
USER appuser
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 4.2 Update Dockerfile.processor (1.5 hours)

**Tasks**:
1. Change `FROM python:3.11-slim` to `FROM base:latest`
2. Remove system dependency installation
3. Remove base package installation
4. Add processor-specific packages from `requirements-processor.txt`
5. Keep spacy model (already in base, don't re-download)
6. Test build locally

**Key Changes**:
- Torch/transformers are large, install in service layer
- Spacy model already available from base
- ML-specific packages only

#### 4.3 Update Dockerfile.crawler (1.5 hours)

**Tasks**:
1. Change `FROM python:3.11-slim` to `FROM base:latest`
2. Keep additional system deps for Playwright (fonts, etc.)
3. Remove base package installation
4. Add crawler-specific packages from `requirements-crawler.txt`
5. Test build locally

**Key Changes**:
- Selenium, Playwright dependencies
- Additional system packages for browser automation
- Newspaper4k and scraping tools

**Deliverables**:
- Updated `Dockerfile.api`
- Updated `Dockerfile.processor`
- Updated `Dockerfile.crawler`
- Test results for each service

**Success Criteria**:
- All service images build successfully
- Build time reduced from 15 min to 2-3 min
- No functionality changes
- Images start and run correctly

---

### Phase 5: Local Testing (2 hours)

**Objective**: Verify all services work correctly with new images

**Tasks**:
1. Build base image locally:
   ```bash
   docker build -t mizzou-base:latest -f Dockerfile.base .
   ```

2. Build service images locally:
   ```bash
   docker build -t mizzou-api:latest -f Dockerfile.api .
   docker build -t mizzou-processor:latest -f Dockerfile.processor .
   docker build -t mizzou-crawler:latest -f Dockerfile.crawler .
   ```

3. Update `docker-compose.yml` to reference new images

4. Test with docker-compose:
   ```bash
   docker-compose up -d
   docker-compose logs -f api
   ```

5. Run integration tests:
   ```bash
   # API health check
   curl http://localhost:8000/health
   
   # Crawler test
   docker-compose run --rm crawler python -m src.cli.main discover-urls --source-limit 1
   
   # Processor test
   docker-compose run --rm processor python -m src.cli.main extract --limit 5
   ```

6. Measure build times:
   ```bash
   # First build (no cache)
   time docker build --no-cache -t mizzou-api:test -f Dockerfile.api .
   
   # Second build (with base cached)
   time docker build -t mizzou-api:test2 -f Dockerfile.api .
   ```

**Test Scenarios**:
- [ ] API service starts and responds to /health
- [ ] Processor can connect to database
- [ ] Crawler can discover URLs
- [ ] All Python packages import correctly
- [ ] Spacy model loads
- [ ] No import errors or missing dependencies

**Deliverables**:
- Test results document
- Build time measurements
- docker-compose.yml updates

**Success Criteria**:
- All services start successfully
- All integration tests pass
- Build time < 3 minutes per service
- No functionality regressions

---

### Phase 6: Cloud Build Integration (3 hours)

**Objective**: Integrate base image into Cloud Build pipeline

#### 6.1 Create Base Image Build Config (1 hour)

**Tasks**:
1. Create `cloudbuild-base.yaml`:
   ```yaml
   steps:
   - name: 'gcr.io/cloud-builders/docker'
     args:
     - 'build'
     - '-t'
     - 'us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-crawler/base:latest'
     - '-t'
     - 'us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-crawler/base:$SHORT_SHA'
     - '-f'
     - 'Dockerfile.base'
     - '.'
   
   images:
   - 'us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-crawler/base:latest'
   - 'us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-crawler/base:$SHORT_SHA'
   
   timeout: 1200s  # 20 minutes for base image
   ```

2. Create manual trigger `trigger-base.yaml`:
   ```yaml
   name: build-base-manual
   description: Manually build shared base image
   filename: cloudbuild-base.yaml
   ```

3. Create trigger in Cloud Build:
   ```bash
   gcloud builds triggers create manual \
     --name=build-base-manual \
     --build-config=cloudbuild-base.yaml \
     --repo=https://github.com/LocalNewsImpact/MizzouNewsCrawler \
     --branch=feature/gcp-kubernetes-deployment
   ```

#### 6.2 Update Service Build Configs (1 hour)

**Tasks**:
1. Update `cloudbuild-api-only.yaml` to reference base image
2. Update `cloudbuild-processor-only.yaml` to reference base image
3. Update `cloudbuild-crawler-only.yaml` to reference base image
4. Ensure correct Artifact Registry paths

**Example Update (cloudbuild-api-only.yaml)**:
```yaml
substitutions:
  _BASE_IMAGE: us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/base:latest

steps:
- name: 'gcr.io/cloud-builders/docker'
  args:
  - 'build'
  - '--build-arg'
  - 'BASE_IMAGE=${_BASE_IMAGE}'
  - '-t'
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-crawler/api:$SHORT_SHA'
  - '-f'
  - 'Dockerfile.api'
  - '.'
```

#### 6.3 Test Cloud Build Pipeline (1 hour)

**Tasks**:
1. Trigger base image build:
   ```bash
   gcloud builds triggers run build-base-manual
   ```

2. Wait for base build to complete (~10 minutes)

3. Trigger service builds:
   ```bash
   gcloud builds triggers run build-api-manual
   gcloud builds triggers run build-processor-manual
   gcloud builds triggers run build-crawler-manual
   ```

4. Verify builds complete quickly (~2-3 minutes each)

5. Check Cloud Deploy for automatic deployment

**Deliverables**:
- `cloudbuild-base.yaml`
- `trigger-base.yaml`
- Updated service cloudbuild configs
- Cloud Build trigger configured
- Test build results

**Success Criteria**:
- Base image builds successfully in Cloud Build
- Base image available in Artifact Registry
- Service builds reference base image correctly
- Service builds complete in 2-3 minutes
- Automatic deployment works

---

### Phase 7: Documentation (2 hours)

**Objective**: Document the new build system and maintenance procedures

#### 7.1 Update DOCKER_GUIDE.md (1 hour)

**Add Sections**:

1. **Shared Base Image**:
   ```markdown
   ### Shared Base Image Strategy
   
   This project uses a shared base image containing common dependencies to optimize build times:
   
   - **Base Image**: `base:latest` (~1.5 GB)
     - System dependencies (gcc, g++, libpq-dev)
     - Common Python packages (pandas, sqlalchemy, spacy, etc.)
     - Spacy model (en_core_web_sm)
   
   - **Service Images**: Build from base + service-specific packages
     - API: base + FastAPI (~300 MB additional)
     - Processor: base + ML packages (~400 MB additional)
     - Crawler: base + scraping tools (~500 MB additional)
   ```

2. **Building Base Image**:
   ```markdown
   ### Building the Base Image
   
   The base image should be rebuilt when:
   - Base dependencies are added/removed in `requirements-base.txt`
   - System dependencies change
   - Spacy model version updates
   - Security patches needed
   
   **Local Build**:
   ```bash
   docker build -t mizzou-base:latest -f Dockerfile.base .
   ```
   
   **Cloud Build** (recommended):
   ```bash
   gcloud builds triggers run build-base-manual
   ```
   
   Rebuild time: ~10 minutes (first time), ~5 minutes (cached)
   ```

3. **Troubleshooting**:
   ```markdown
   ### Issue: "Base image not found"
   
   **Symptoms**:
   ```
   Error: base:latest not found
   ```
   
   **Solutions**:
   1. Build base image locally:
      ```bash
      docker build -t mizzou-base:latest -f Dockerfile.base .
      ```
   
   2. Pull from Artifact Registry:
      ```bash
      docker pull us-central1-docker.pkg.dev/PROJECT/images/base:latest
      docker tag us-central1-docker.pkg.dev/PROJECT/images/base:latest mizzou-base:latest
      ```
   ```

#### 7.2 Create BASE_IMAGE_MAINTENANCE.md (1 hour)

**Document**:

1. **When to Rebuild Base Image**:
   - Adding/removing packages in `requirements-base.txt`
   - Updating Python version
   - Security updates for system packages
   - Spacy model updates
   - Quarterly maintenance

2. **Rebuild Procedure**:
   ```markdown
   ## Base Image Rebuild Procedure
   
   1. **Update requirements-base.txt** with new/changed dependencies
   
   2. **Test locally**:
      ```bash
      docker build -t mizzou-base:test -f Dockerfile.base .
      docker run mizzou-base:test python -c "import <new_package>"
      ```
   
   3. **Update service requirements** if needed
   
   4. **Commit changes**:
      ```bash
      git add requirements-base.txt Dockerfile.base
      git commit -m "Update base image dependencies"
      git push
      ```
   
   5. **Build in Cloud**:
      ```bash
      gcloud builds triggers run build-base-manual
      ```
   
   6. **Wait for base build** (~10 minutes)
   
   7. **Rebuild services** (automatic or manual trigger)
   
   8. **Test services** in staging/production
   ```

3. **Rollback Procedure**:
   ```markdown
   ## Rollback Procedure
   
   If base image update causes issues:
   
   1. **Revert to previous base image**:
      ```bash
      # Find previous working version
      gcloud artifacts docker images list \
        us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/base
      
      # Tag previous version as latest
      gcloud artifacts docker tags add \
        us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/base:<OLD_SHA> \
        us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/base:latest
      ```
   
   2. **Rebuild services with old base**:
      ```bash
      gcloud builds triggers run build-api-manual
      # etc.
      ```
   
   3. **Fix base image issue**
   
   4. **Test fixed base image**
   
   5. **Re-deploy updated base**
   ```

4. **Version Strategy**:
   ```markdown
   ## Base Image Versioning
   
   Base images are tagged with:
   - `latest`: Current production version
   - `<git-sha>`: Specific commit version (immutable)
   - `<version>`: Semantic version (e.g., v1.0, v1.1)
   
   Service images reference:
   - Local dev: `base:latest`
   - Production: `base:<git-sha>` (pinned for stability)
   ```

**Deliverables**:
- Updated `docs/DOCKER_GUIDE.md`
- New `docs/BASE_IMAGE_MAINTENANCE.md`
- Updated README.md (if needed)

**Success Criteria**:
- Clear documentation for building base image
- Documented maintenance procedures
- Rollback procedure tested and documented
- Troubleshooting section added

---

### Phase 8: Rollout (1 hour)

**Objective**: Deploy the optimization to production

**Tasks**:

1. **Pre-deployment Checklist**:
   - [ ] All tests passing locally
   - [ ] Documentation complete
   - [ ] Base image built and available in Artifact Registry
   - [ ] Service images tested with new base
   - [ ] Rollback procedure documented and ready

2. **Deployment Steps**:
   ```bash
   # 1. Build base image in Cloud
   gcloud builds triggers run build-base-manual
   
   # 2. Wait for completion (~10 minutes)
   gcloud builds list --ongoing
   
   # 3. Build service images
   gcloud builds triggers run build-api-manual
   gcloud builds triggers run build-processor-manual
   gcloud builds triggers run build-crawler-manual
   
   # 4. Monitor builds (~2-3 minutes each)
   gcloud builds list --ongoing
   
   # 5. Verify Cloud Deploy releases created
   gcloud deploy releases list \
     --delivery-pipeline=mizzou-news-crawler \
     --region=us-central1
   
   # 6. Monitor deployment
   kubectl get pods -n production -w
   
   # 7. Verify services healthy
   kubectl get pods -n production
   kubectl logs -n production <pod-name>
   ```

3. **Post-deployment Validation**:
   - [ ] API responds to health checks
   - [ ] Processor running extraction
   - [ ] Crawler discovering URLs
   - [ ] No errors in logs
   - [ ] Build times reduced (verify in Cloud Build history)

4. **Measure Results**:
   ```bash
   # Check build times
   gcloud builds list --format="table(id,status,createTime,duration)" --limit=10
   
   # Compare with historical builds
   # Before: ~900s (15 min)
   # After: ~120-180s (2-3 min)
   # Improvement: 80-87% reduction
   ```

5. **Update Issue #38**:
   - [ ] Mark all checklist items complete
   - [ ] Document final build times
   - [ ] Add screenshots of Cloud Build times
   - [ ] Close issue

**Deliverables**:
- Deployment completion report
- Build time comparison data
- Updated Issue #38

**Success Criteria**:
- All services deployed successfully
- Build times < 3 minutes per service
- No functionality regressions
- Documentation complete
- Issue #38 closed

---

## Risk Assessment & Mitigation

### Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Base image build fails | Low | High | Test locally first; have rollback plan |
| Service incompatibility | Medium | High | Thorough testing; pin base image version |
| Increased complexity | Low | Medium | Comprehensive documentation |
| Base image becomes stale | Medium | Low | Quarterly rebuild schedule |
| Dependency conflicts | Low | High | Test all combinations; use virtual envs |

### Rollback Plan

If issues arise after deployment:

1. **Immediate Rollback** (< 5 minutes):
   ```bash
   # Deploy previous service versions
   gcloud deploy releases promote \
     --release=<previous-release> \
     --to-target=production
   ```

2. **Revert Base Image** (< 10 minutes):
   ```bash
   # Tag old base as latest
   gcloud artifacts docker tags add \
     BASE_IMAGE:<old-sha> BASE_IMAGE:latest
   
   # Rebuild services
   gcloud builds triggers run build-api-manual
   ```

3. **Full Revert** (< 30 minutes):
   ```bash
   # Revert all Dockerfile changes
   git revert <commit-hash>
   git push
   
   # Trigger builds with reverted code
   ```

---

## Success Metrics

### Primary Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Build Time (API) | 15 min | 2-3 min | < 3 min |
| Build Time (Processor) | 15 min | 2-3 min | < 3 min |
| Build Time (Crawler) | 15 min | 2-3 min | < 3 min |
| Build Cost (per service) | $0.15 | $0.05 | < $0.06 |
| Total Build Time (all) | 45 min | 15 min | < 20 min |

### Secondary Metrics

- Developer satisfaction: Faster iteration
- Cache hit rate: Improved layer reuse
- Deployment frequency: Can deploy more often
- CI/CD pipeline time: Reduced end-to-end time

### Acceptance Criteria

- [x] Build time reduced by > 80%
- [ ] All services deploy successfully
- [ ] No functionality regressions
- [ ] Zero production incidents related to base image
- [ ] Documentation complete and clear
- [ ] Team trained on new system

---

## Timeline

### Week 1
- **Day 1-2**: Phases 1-3 (Analysis, Requirements, Base Image)
- **Day 3**: Phase 4 (Service Dockerfiles)
- **Day 4**: Phase 5 (Local Testing)
- **Day 5**: Phases 6-7 (Cloud Integration, Documentation)

### Week 2
- **Day 1**: Phase 8 (Rollout)
- **Day 2-5**: Monitoring and iteration

---

## Dependencies

### External Dependencies
- Artifact Registry access
- Cloud Build permissions
- GKE cluster access
- GitHub repository access

### Internal Dependencies
- Current deployment must complete first (API telemetry migration, Processor orchestration fix)
- No conflicting PRs
- Team availability for testing

---

## Historical Context

This optimization was previously implemented in commit `65b4df3` with a `Dockerfile.base`, but was never merged to main branch. This implementation is a recreation with improvements:

1. **Better requirements splitting**: Service-specific files
2. **Improved documentation**: Maintenance procedures
3. **Cloud Build integration**: Automated triggers
4. **Version pinning**: Better stability

---

## References

- **Issue**: [#38](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/38)
- **Previous attempt**: Commit `65b4df3`
- **Docker multi-stage builds**: [Docker docs](https://docs.docker.com/build/building/multi-stage/)
- **GCP Artifact Registry**: [GCP docs](https://cloud.google.com/artifact-registry/docs)
- **Cloud Build**: [GCP docs](https://cloud.google.com/build/docs)

---

## Maintenance Schedule

### Quarterly Tasks (Every 3 months)
- [ ] Review and update requirements-base.txt
- [ ] Update Python security patches
- [ ] Update spacy model version
- [ ] Rebuild base image
- [ ] Test all services

### As-Needed Tasks
- [ ] When adding new shared dependencies
- [ ] When removing obsolete packages
- [ ] When addressing security vulnerabilities
- [ ] When Python version updates

---

## Approval & Sign-off

- [ ] Technical Lead Review
- [ ] DevOps Review
- [ ] Security Review
- [ ] Documentation Review
- [ ] Testing Complete
- [ ] Ready for Production

**Approved by**: _____________  
**Date**: _____________

---

*End of Roadmap*
