# Selective Service Build Testing Guide

This directory contains tools to test and validate the selective build system before pushing to main.

## Quick Start

### Test Against Real Git Commits

Test what services would rebuild for a specific commit range:

```bash
# Compare HEAD~1 with HEAD (last 2 commits)
./scripts/test-selective-build.sh

# Compare a branch with main
./scripts/test-selective-build.sh origin/main HEAD

# Compare specific commits
./scripts/test-selective-build.sh abc123 def456
```

### Simulate File Changes (No Git Changes Required)

Test various scenarios without modifying your actual repo:

```bash
./scripts/simulate-selective-build.sh
```

This opens an interactive menu with pre-defined scenarios:
1. **crawler_only** - Changes to `src/crawler/` (Crawler only)
2. **ml_feature** - Changes to `src/ml/` and `analysis.py` (Processor only)
3. **pytorch_upgrade** - Changes to `requirements-ml.txt` (ML-base → Processor)
4. **db_migration** - Changes to `alembic/versions/` (Migrator → All)
5. **api_endpoint** - Changes to `backend/` and `reports.py` (API only)
6. **docs_only** - Changes to `README.md` and docs (Migrator only, no services)
7. **base_upgrade** - Changes to `requirements-base.txt` (Base → All services)
8. **full_rebuild** - Multiple Dockerfile changes (All services)
9. **custom** - Specify your own files

## Understanding Output

### Example 1: Crawler-Only Change

```
📝 Changed Files:
   src/crawler/link_extractor.py

🔍 Analyzing changes...

✅ BASE - No base image changes
⏭️  ML-BASE - No ML-base changes
⏭️  MIGRATOR - No migration changes
⏭️  PROCESSOR - No processor changes
⏭️  API - No API changes
✅ CRAWLER - Discovery/verification/extraction changes detected

═══════════════════════════════════════════════════════
🚀 SERVICE BUILD PLAN
═══════════════════════════════════════════════════════
  ⏭️  base (skipped)
  ⏭️  ml-base (skipped)
  ✅ migrator
  ⏭️  processor (skipped)
  ⏭️  api (skipped)
  ✅ crawler

📦 Summary: Building 2 service(s)
   Services: migrator crawler
```

**What happened?**
- Detected change in `src/crawler/` → triggers CRAWLER rebuild
- Migrator always rebuilds on main (mandatory for database safety)
- Other services skipped because they weren't affected

### Example 2: Base Dependency Change

```
📝 Changed Files:
   requirements-base.txt

🔍 Analyzing changes...

✅ BASE - Base image changes detected
⏭️  ML-BASE - No ML-base changes
🔗 BASE changed → rebuilding all dependent services

═══════════════════════════════════════════════════════
🚀 SERVICE BUILD PLAN
═══════════════════════════════════════════════════════
  ✅ base
  ⏭️  ml-base (skipped)
  ✅ migrator
  ✅ processor
  ✅ api
  ✅ crawler

📦 Summary: Building 5 service(s)
```

**What happened?**
- Detected change in `requirements-base.txt` → triggers BASE rebuild
- BASE is a foundational dependency
- All other services automatically rebuild because they depend on BASE
- This is the most expensive scenario (full rebuild)

### Example 3: ML Dependencies Change

```
📝 Changed Files:
   requirements-ml.txt

🔍 Analyzing changes...

⏭️  BASE - No base image changes
✅ ML-BASE - ML dependencies changes detected
🔗 ML-BASE changed → rebuilding processor

═══════════════════════════════════════════════════════
🚀 SERVICE BUILD PLAN
═══════════════════════════════════════════════════════
  ⏭️  base (skipped)
  ✅ ml-base
  ✅ migrator
  ✅ processor
  ⏭️  api (skipped)
  ⏭️  crawler (skipped)

📦 Summary: Building 3 service(s)
```

**What happened?**
- Detected change in `requirements-ml.txt` → triggers ML-BASE rebuild
- ML-BASE only affects PROCESSOR (which uses PyTorch/Transformers)
- Migrator always rebuilds
- API and Crawler unaffected (they don't use ML dependencies)

## File Patterns Reference

Here's what triggers each service:

### BASE (Foundational - triggers all others if changed)
```
Dockerfile.base
requirements-base.txt
src/config.py
pyproject.toml
alembic/                    (any migration files)
setup.py
```

### ML-BASE (Machine Learning foundation)
```
Dockerfile.ml-base
requirements-ml.txt
```

### MIGRATOR (Database - always rebuilds on main)
```
Dockerfile.migrator
requirements-migrator.txt
alembic/versions/           (specific migration versions)
```

### PROCESSOR (ML/Entity Extraction)
```
Dockerfile.processor
requirements-processor.txt
src/pipeline/               (any pipeline changes)
src/ml/                     (any ML changes)
src/services/classification_service.py
src/cli/commands/analysis.py
src/cli/commands/entity_extraction.py
```

### API (Web Backend)
```
Dockerfile.api
requirements-api.txt
backend/                    (any backend changes)
src/models/api_backend.py
src/cli/commands/cleaning.py
src/cli/commands/reports.py
```

### CRAWLER (URL Discovery/Content Extraction)
```
Dockerfile.crawler
requirements-crawler.txt
src/crawler/                (any crawler changes)
src/services/               (shared services)
src/utils/                  (shared utilities)
src/cli/commands/discovery.py
src/cli/commands/verification.py
src/cli/commands/extraction.py
src/cli/commands/content_cleaning.py
```

## Debugging

### See detailed git diff
```bash
# Show which files changed
git diff --name-only origin/main HEAD

# Show summary of changes
git diff --stat origin/main HEAD

# Show full diff
git diff origin/main HEAD
```

### Enable debug output
```bash
DEBUG=true ./scripts/test-selective-build.sh
```

This shows regex pattern matches for troubleshooting.

### Test a specific file pattern
```bash
# Check if a file would trigger a specific service
git diff origin/main HEAD | grep -E "(src/crawler/|src/utils/)"

# Get exact files matching a pattern
git diff --name-only origin/main HEAD | grep -E "requirements-(base|ml|processor)"
```

## Common Scenarios

### Scenario 1: Routine Bugfix (Crawler Only)
```bash
# Modified: src/crawler/link_extractor.py
# Expected rebuild: migrator, crawler
# Time saving: ~5 minutes (skip base, ml-base, processor, api)
```

### Scenario 2: ML Feature Addition
```bash
# Modified: src/ml/new_classifier.py
#          src/cli/commands/analysis.py
# Expected rebuild: migrator, processor
# Time saving: ~10 minutes (skip base, ml-base, api, crawler)
```

### Scenario 3: Dependency Upgrade
```bash
# Modified: requirements-ml.txt
# Expected rebuild: migrator, ml-base, processor
# Time saving: ~5 minutes (base is unchanged, so api/crawler skip)
```

### Scenario 4: Database Migration
```bash
# Modified: alembic/versions/001_add_new_column.py
# Expected rebuild: migrator (only)
# Time saving: ~15 minutes (entire rebuild skipped, only schema updated)
```

### Scenario 5: Documentation
```bash
# Modified: README.md, docs/API.md
# Expected rebuild: migrator (only - mandatory on main)
# Time saving: ~15 minutes (no service images built, only schema check)
```

## When Workflows Trigger

The selective build workflow runs on **every push to main**:

```
Developer push to main
        ↓
GitHub Actions: selective-service-build.yml
        ↓
detect-changes job (analyzes git diff)
        ↓
Conditional service builds (only affected services)
        ↓
Cloud Build Triggers called via gcloud CLI
        ↓
Services rebuild in Artifact Registry
        ↓
Cloud Deploy release created
        ↓
GKE deployment updated
```

### Pre-Push Testing

Before pushing to main:

```bash
# 1. Create your feature branch locally
git checkout -b feature/my-feature

# 2. Make your changes
# ... edit files ...
git add .
git commit -m "Feature: my feature"

# 3. Test what would rebuild
git checkout -b test/selective-build
./scripts/test-selective-build.sh origin/main HEAD
git checkout -

# 4. When satisfied, push to main
git push origin feature/my-feature
# Create PR → Review → Merge to main
```

## Troubleshooting Build Detection

### Issue: A file should trigger a service but doesn't

1. **Check the pattern** - Look at "File Patterns Reference" above
2. **Test the pattern locally**:
   ```bash
   # Does this file match the processor pattern?
   echo "src/ml/new_feature.py" | grep -E "(src/pipeline/|src/ml/)"
   # Output: src/ml/new_feature.py (matches!)
   ```

3. **Verify git is reporting the file**:
   ```bash
   git diff --name-only origin/main HEAD | grep "src/ml/"
   ```

### Issue: Too many services are rebuilding

This usually means:
1. **BASE was changed** - Check `requirements-base.txt`, `Dockerfile.base`, etc. (triggers all)
2. **Pattern is too broad** - File pattern might match unintended files
3. **Dependency rules** - ML-BASE changes always rebuild processor

### Issue: Too few services are rebuilding

This usually means:
1. **File pattern doesn't match** - Check exact file path spelling
2. **File not in changed set** - Verify with `git diff --name-only`
3. **Wrong ref comparison** - Use correct branches for comparison

## Next Steps

After verifying service detection:

1. **Push to main** and watch GitHub Actions
   ```bash
   # In GitHub Actions Workflow:
   # Check the "Detect Changes" job output
   # Verify the build plan matches your expectation
   ```

2. **Monitor Cloud Build**
   - Go to GCP Console → Cloud Build
   - Watch builds for affected services
   - Verify builds only for changed services

3. **Validate Cloud Deploy**
   - Go to GCP Console → Cloud Deploy
   - New release should only include changed services
   - Check Argo Workflow for pod rollouts

4. **Performance Improvement**
   - Compare build times
   - Docs-only changes should build in ~2 minutes
   - Single service changes should build in ~5-10 minutes
   - Full rebuilds should build in ~30-40 minutes
