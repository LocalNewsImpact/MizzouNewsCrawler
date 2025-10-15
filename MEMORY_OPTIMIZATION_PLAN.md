# Memory Optimization Plan

**Date**: October 15, 2025  
**Context**: Processor pod using 2065Mi despite having extraction disabled  
**Root Causes Identified**:

## 1. Eager Module Imports (PRIMARY ISSUE)

### Problem
The `src.crawler` module (3015 lines) is imported at module load time in `extraction.py`:

```python
# src/cli/commands/extraction.py line 18
from src.crawler import ContentExtractor, NotFoundError  # ❌ EAGER IMPORT
```

This loads heavy dependencies even when extraction is disabled:
- **Selenium** (`selenium.webdriver`, `selenium.webdriver.chrome.*`)
- **Undetected ChromeDriver** (`undetected_chromedriver`)
- **Selenium Stealth** (`selenium_stealth`)
- **Newspaper** (`newspaper`)
- **CloudScraper** (`cloudscraper`)
- **BeautifulSoup** + massive regex patterns for subscription/CAPTCHA detection

**Memory Impact**: ~150-200Mi of unnecessary imports loaded in processor pod that only does cleaning/ML/entities

### Solution: Lazy Import Pattern

**Before** (extraction.py):
```python
from src.crawler import ContentExtractor, NotFoundError

def handle_extraction_command(args):
    extractor = ContentExtractor()
    # ... extraction logic
```

**After** (lazy loading):
```python
# No import at module level

def handle_extraction_command(args):
    # Lazy import - only load when extraction actually runs
    from src.crawler import ContentExtractor, NotFoundError
    
    extractor = ContentExtractor()
    # ... extraction logic
```

**Benefits**:
- Processor pod (no extraction): Crawler module NEVER loaded, saves ~150-200Mi
- Extraction jobs: Import happens on first use, no performance impact
- Cleaning/ML/Entity commands: Unaffected, never load crawler

---

## 2. CSV Test Data in Image (SECONDARY ISSUE)

### Problem
Repository root contains 36MB of CSV export data that gets copied into Docker image:

```bash
$ ls -lh *.csv
-rw-r--r-- penn_state_lehigh_all_articles.csv          3.1M
-rw-r--r-- penn_state_lehigh_all_articles_clean.csv    5.2M
-rw-r--r-- penn_state_lehigh_all_entity_types.csv     12M
-rw-r--r-- penn_state_lehigh_with_entities.csv        16M
Total: ~36MB
```

These are **test/export data**, not runtime dependencies, but `.dockerignore` doesn't exclude them.

**Memory Impact**: 36MB added to every pod/job container

### Solution: Update .dockerignore

**Add to `.dockerignore`**:
```
# Data exports and test files (not needed in runtime image)
*.csv
*.tsv
*.xlsx
*.json
!src/**/*.json  # Keep JSON in src/ (may have configs)
!k8s/**/*.json  # Keep JSON in k8s/ (may have configs)
```

**Benefits**:
- Image size: -36MB
- Container startup: Slightly faster (less to copy)
- Memory: -36MB per pod/job

---

## 3. Module Architecture (LONG-TERM)

### Current State ✅
- **Single shared image** (`processor:latest`) used by:
  - Continuous processor pod (cleaning/ML/entities only)
  - Extraction jobs (Mizzou, Lehigh)
  - Discovery cron jobs
  
**This is GOOD** - no code duplication, single source of truth

### Future Optimization (NOT URGENT)

Could split into specialized images:
1. **processor-light**: No crawler/selenium, only cleaning/ML/entities (saves ~300-400Mi)
2. **processor-full**: Everything (for extraction jobs)

But this adds complexity:
- Two Dockerfiles to maintain
- Two image builds
- More deployment config

**Recommendation**: NOT worth it yet. Lazy imports solve 80% of the problem.

---

## Implementation Priority

### Phase 1: Quick Wins (TODAY)

**1a. Add CSV exclusion to .dockerignore**
```bash
# Add these lines to .dockerignore
*.csv
*.tsv
```

**Expected savings**: -36MB image size, -36MB memory per pod

**1b. Lazy load crawler in extraction.py**

Change line 18 from:
```python
from src.crawler import ContentExtractor, NotFoundError
```

To (move inside function):
```python
# Remove top-level import
# Import moved to handle_extraction_command() function
```

**Expected savings**: ~150-200Mi in processor pod that doesn't extract

**Total Phase 1 savings**: ~186-236Mi
**Processor pod would use**: ~1800-1900Mi instead of 2065Mi (back under 2Gi!)

### Phase 2: Verify and Monitor (NEXT WEEK)

1. Deploy changes
2. Monitor memory usage:
   ```bash
   watch -n 60 'kubectl top pod -n production -l app=mizzou-processor'
   ```
3. Verify processor stable under 2Gi
4. Reduce memory limit back to 2Gi if stable

### Phase 3: Additional Lazy Loading (IF NEEDED)

Check other heavy imports that might not be needed:
- spaCy model loading (only for entity extraction)
- ML models (only for analysis)
- Newspaper library (only for extraction)

But these are likely already conditional since commands are subprocess-based.

---

## Risk Assessment

### Phase 1 Changes

**Risk Level**: ⚠️ LOW-MEDIUM

**Lazy Import Risk**:
- ✅ CLI is already lazy-loaded (cli_modular.py)
- ✅ Commands run as subprocesses (isolated)
- ⚠️ Need to verify no other code imports ContentExtractor at top level
- ⚠️ Test extraction jobs after change

**CSV Exclusion Risk**:
- ✅ Very safe - these are export files, not dependencies
- ✅ No code references these files
- ✅ Can verify with `git grep "\.csv"`

### Testing Required

1. **Extraction jobs** still work after lazy import
2. **Processor pod** memory drops after changes
3. **No import errors** in any command

---

## Measurement Plan

### Before Changes (Baseline)
```bash
# Current state
kubectl top pod -n production -l app=mizzou-processor
# Result: CPU=825m, MEMORY=2065Mi

docker inspect processor:322bb13 | jq '.[0].Size'
# Expected: ~2-2.5GB
```

### After Phase 1a (CSV exclusion)
```bash
# Build new image
gcloud builds triggers run build-processor-manual

# Check new image size
docker inspect processor:<NEW_COMMIT> | jq '.[0].Size'
# Expected: ~36MB smaller
```

### After Phase 1b (Lazy imports)
```bash
# Deploy and monitor
kubectl top pod -n production -l app=mizzou-processor
# Expected: MEMORY=1800-1900Mi (down from 2065Mi)

# Verify extraction jobs still work
kubectl apply -f k8s/mizzou-extraction-job.yaml
kubectl logs -n production -l dataset=Mizzou --follow
# Should see: "🚀 Starting extraction..."
```

---

## Decision

**Proceed with Phase 1?** 
- ✅ YES for CSV exclusion (.dockerignore) - zero risk
- ⚠️ REVIEW NEEDED for lazy imports - need to verify no other top-level imports

**Next Steps**:
1. Search codebase for other `from src.crawler import` at top level
2. Review verification.py, discovery.py for similar patterns
3. If clear, implement both changes
4. Build → Test → Deploy → Monitor
