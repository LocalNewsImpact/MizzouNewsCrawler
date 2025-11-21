# Selective Service Build - Detection Mapping

This document explains how the selective service build workflow (`selective-service-build.yml`) automatically determines which services need rebuilding based on file changes.

## How It Works

When you push to `main`, the workflow:

1. **Detects changed files** (from current commit vs previous)
2. **Maps files to services** using pattern matching (see below)
3. **Considers dependencies** (e.g., if base changed, rebuild all)
4. **Triggers only needed services** in parallel with correct ordering
5. **Reports build plan** to GitHub Actions summary

## Service Detection Map

### BASE IMAGE
**Triggers rebuild if ANY of these files change:**
- `Dockerfile.base` - Base image definition
- `requirements-base.txt` - Core Python dependencies
- `src/config.py` - Application configuration
- `pyproject.toml` - Project metadata (version, dependencies)
- `setup.py` - Installation configuration

**Why:** Base image contains all shared dependencies. If it changes, all downstream services are affected.

**Dependent services:** migrator, processor, api, crawler (all)

**NOTE:** `alembic/` is NOT included here. Database migrations trigger PROCESSOR rebuild only (see below).

---

### ML-BASE IMAGE
**Triggers rebuild if ANY of these files change:**
- `Dockerfile.ml-base` - ML-specific base image
- `requirements-ml.txt` - PyTorch, transformers, spaCy

**Why:** ML dependencies are large and slow to install. Isolated for faster rebuilds of other services.

**Dependent services:** processor (only)

---

### MIGRATOR
**Triggers rebuild if ANY of these files change:**
- `Dockerfile.migrator` - Migrator image definition
- `requirements-migrator.txt` - Migrator dependencies
- `alembic/versions/` - Database migration scripts

**ALWAYS rebuilt on main** (migrations must be applied before other services deploy)

**Why:** Database changes must be applied before services can run. Runs first in build pipeline.

**Dependent services:** None (blocking dependency for others)

---

### PROCESSOR
**Triggers rebuild if ANY of these files change:**
- `Dockerfile.processor` - Processor image definition
- `requirements-processor.txt` - Processor dependencies
- `src/pipeline/` - Entity extraction pipeline
- `src/ml/` - ML models and classification
- `src/services/classification_service.py` - Article classification logic
- `src/cli/commands/analysis.py` - Analysis command
- `src/cli/commands/entity_extraction.py` - Entity extraction command
- `alembic/versions/` - Database migration scripts

**Why:** Processor handles ML-based processing (entity extraction, classification) AND database migrations. Migrations are run during processor startup.

**Dependencies:** ml-base (if changed), migrator (must complete first)

---

### API
**Triggers rebuild if ANY of these files change:**
- `Dockerfile.api` - API image definition
- `requirements-api.txt` - API dependencies
- `backend/` - FastAPI backend implementation
- `src/models/api_backend.py` - API model definitions
- `src/cli/commands/cleaning.py` - Content cleaning command
- `src/cli/commands/reports.py` - Report generation command

**Why:** REST API endpoints, data models, and report generation. Changes affect API service.

**Dependencies:** base (if changed), migrator (must complete first)

---

### CRAWLER
**Triggers rebuild if ANY of these files change:**
- `Dockerfile.crawler` - Crawler image definition
- `requirements-crawler.txt` - Crawler dependencies
- `src/crawler/` - News discovery and extraction
- `src/services/` - Work queue, verification, URL services
- `src/utils/` - Utilities (byline cleaning, content cleaning, etc.)
- `src/cli/commands/discovery.py` - Discovery command
- `src/cli/commands/verification.py` - Verification command
- `src/cli/commands/extraction.py` - Article extraction command
- `src/cli/commands/content_cleaning.py` - Content cleaning command

**Why:** Crawler handles 90% of pipeline: discovery, verification, extraction, cleaning. Most changes affect this service.

**Dependencies:** base (if changed), migrator (must complete first)

---

## Build Order & Dependencies

```
BASE (if changed)
  ├─→ MIGRATOR (always on main)
  │    ├─→ PROCESSOR (if changed)
  │    ├─→ API (if changed)
  │    └─→ CRAWLER (if changed)
  │
  └─→ ML-BASE (if changed)
       └─→ PROCESSOR (if changed)
```

**Key rules:**
1. **Base runs first** (foundational dependency)
2. **ML-base runs after base** (also foundational)
3. **Migrator runs after base** (database must be ready)
4. **Processor waits for both ML-base and migrator**
5. **API & Crawler wait for base and migrator**
6. All remaining services run in **parallel** where possible

---

## Examples

### Example 1: Fix typo in byline cleaner
```
Changed file: src/utils/byline_cleaner.py

Detection:
  ✅ Matches CRAWLER pattern: src/utils/
  
Build plan:
  ✅ migrator (always on main)
  ✅ crawler (typo fix affects extraction)
  ⏭️  base, ml-base, processor, api (skipped)
```

### Example 2: Add ML classification feature
```
Changed files:
  - src/ml/article_classifier.py
  - src/services/classification_service.py
  - src/cli/commands/analysis.py
  - requirements-processor.txt

Detection:
  ✅ Matches PROCESSOR patterns: src/ml/, src/services/classification_service.py, src/cli/commands/analysis.py, requirements-processor.txt
  
Build plan:
  ✅ migrator (always on main)
  ✅ processor (all changed files match processor)
  ⏭️  base, ml-base, api, crawler (skipped)
```

### Example 3: Upgrade PyTorch version
```
Changed file: requirements-ml.txt

Detection:
  ✅ Matches ML-BASE: requirements-ml.txt
  ✅ Processor depends on ML-BASE
  
Build plan:
  ✅ ml-base (PyTorch upgrade)
  ✅ migrator (always on main)
  ✅ processor (depends on ml-base)
  ⏭️  base, api, crawler (skipped)
```

### Example 4: Database migration (now processor-scoped)
```
Changed file: alembic/versions/001_add_new_table.py

Detection:
  ✅ Matches PROCESSOR: alembic/versions/
  
Build plan:
  ✅ migrator (always on main)
  ✅ processor (contains migration script)
  ⏭️  base, ml-base, api, crawler (skipped)
  
Result: Only processor and migrator rebuild (migrations run via processor lifecycle)
```

### Example 5: Database migration + API endpoint
```
Changed files:
  - alembic/versions/001_add_new_table.py
  - backend/app/main.py

Detection:
  ✅ Matches PROCESSOR: alembic/versions/
  ✅ Matches API: backend/app/main.py
  
Build plan:
  ✅ migrator (always on main)
  ✅ processor (migration script)
  ✅ api (new endpoint)
  ⏭️  base, ml-base, crawler (skipped)
```

### Example 6: Core dependency update (worst case)
```
Changed file: requirements-base.txt (upgrade to major Python version)

Detection:
  ✅ Matches BASE: requirements-base.txt
  ✅ All services depend on BASE
  
Build plan:
  ✅ base (core dependency)
  ✅ ml-base (depends on base)
  ✅ migrator (always on main, depends on base)
  ✅ processor (depends on base and ml-base)
  ✅ api (depends on base)
  ✅ crawler (depends on base)
  
Result: Full rebuild (all 6 services)
```

---

## Special Cases

### Case 1: Documentation-only changes
```
Changed file: docs/README.md

Detection:
  ❌ No service patterns match
  
Build plan:
  ✅ migrator (always on main - mandatory)
  ⏭️  base, ml-base, processor, api, crawler (skipped)
```

### Case 2: Configuration changes
```
Changed file: k8s/deployment.yaml (K8s config)

Detection:
  ❌ K8s configs don't affect service code
  
Build plan:
  ✅ migrator (always on main)
  ⏭️  base, ml-base, processor, api, crawler (skipped)
  
Note: To deploy config changes without rebuilding, use manual K8s apply
```

### Case 3: Multiple services changed
```
Changed files:
  - src/crawler/__init__.py (discovery changes)
  - src/services/classification_service.py (processor changes)
  - backend/app/main.py (API changes)

Detection:
  ✅ Matches CRAWLER: src/crawler/
  ✅ Matches PROCESSOR: src/services/classification_service.py
  ✅ Matches API: backend/app/main.py
  
Build plan:
  ✅ migrator (always on main)
  ✅ processor (classification service changed)
  ✅ api (API endpoint changed)
  ✅ crawler (discovery changed)
  ⏭️  base, ml-base (skipped)
```

---

## Adding New File Patterns

If you add a new file/service in the future, update the patterns:

```bash
# Example: Add support for new "recommender" service
# Edit .github/workflows/selective-service-build.yml

# Find: # CRAWLER: Discovery, verification, extraction
# Add before it:

# RECOMMENDER: Recommendation engine
if echo "$CHANGED_FILES" | grep -qE '(Dockerfile\.recommender|requirements-recommender\.txt|src/recommender/)'; then
  echo "✅ RECOMMENDER changes detected"
  REBUILD_RECOMMENDER="true"
fi
```

---

## Workflow Outputs

The workflow generates a report in GitHub Actions that shows:

1. **Changed files** - Exact files that triggered changes
2. **Build plan** - Which services will build
3. **Rebuild status** - Table showing each service and why it rebuilds or not

**Example report:**
```
## 🚀 Selective Service Build Report

### Build Plan
Building 3 services: migrator processor crawler

### Changed Files
src/crawler/__init__.py
src/services/classification_service.py

### Service Rebuild Status
| Service | Rebuild | Reason |
|---------|---------|--------|
| base | false | Base image changes |
| ml-base | false | ML dependencies changed |
| migrator | true | Always rebuild on main + schema changes |
| processor | true | ML/entity extraction changes |
| api | false | API/backend changes |
| crawler | true | Discovery/verification/extraction changes |
```

---

## Gotchas & Notes

1. **Migrator always rebuilds** - Database migrations must always be applied on main, even if migrations folder hasn't changed
2. **Git diff compares** - Must have 2 commits to compare. First push to new branch may have edge cases
3. **Pattern matching is greedy** - `src/` catches everything under src/, including core utilities that affect multiple services
4. **Dependencies are conservative** - If base changes, ALL services rebuild (safest approach)
5. **Manual overrides** - Can still manually trigger `gcloud builds triggers run` if needed

---

## Debugging

If you think the wrong services are being rebuilt:

1. **Check GitHub Actions logs** - "Detect changed files and determine services" step shows:
   - What files changed
   - Which patterns matched
   - Reasoning for each service

2. **Test locally:**
   ```bash
   # Get files that would change
   git diff --name-only HEAD~1 HEAD
   
   # Test pattern matching manually
   echo "src/crawler/__init__.py" | grep -qE '(Dockerfile\.crawler|requirements-crawler\.txt|src/crawler/)' && echo "MATCHES" || echo "NO MATCH"
   ```

3. **Review patterns** - Open `.github/workflows/selective-service-build.yml` and verify regex patterns

