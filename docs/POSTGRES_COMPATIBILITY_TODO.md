# PostgreSQL Compatibility Issues - Remaining Work

## Status: CRITICAL - Multiple Production Failures Due to SQLite/PostgreSQL Gaps

### ✅ COMPLETED FIXES (Current Branch: fix/telemetrystring)

1. **SQLite Fallback Removed** (c66e9b4)
   - Removed `_SQLITE_FALLBACK_URL` constant
   - `_determine_default_database_url()` now raises error instead of falling back
   - Added validation that rejects non-PostgreSQL URLs

2. **TELEMETRY_DATABASE_URL Set in Kubernetes** (c538da0)
   - Added to `k8s/argo/base-pipeline-workflow.yaml` (3 steps)
   - Added to `k8s/processor-deployment.yaml`

3. **PRAGMA table_info Fixes**
   - `src/models/database.py`: 2 locations fixed with information_schema
   - `src/utils/comprehensive_telemetry.py`: Already had PostgreSQL branch

4. **INSERT OR IGNORE Fixes**
   - `scripts/populate_gazetteer.py`: Fixed with ON CONFLICT
   - `src/models/database.py`: Already had dialect detection

5. **Aggregate Type Conversions** (5e1402d)
   - `src/utils/telemetry.py` get_discovery_summary(): Fixed all aggregate results
   - Added int()/float() conversions for COUNT/SUM/AVG/ROUND results

6. **Helper Function Added** (f2748fb)
   - `src/cli/commands/pipeline_status.py`: Added `_to_int()` helper

### ❌ REMAINING ISSUES - HIGH PRIORITY

#### 1. Widespread `.scalar() or 0` Pattern (CRITICAL)

**Problem:** PostgreSQL returns aggregates as strings, so `result.scalar() or 0` returns the string instead of 0 when it should default.

**Impact:** All COUNT/SUM comparisons will fail or behave incorrectly.

**Locations to Fix:**
- `src/cli/commands/pipeline_status.py`: 22 locations
  ```python
  # BROKEN on PostgreSQL:
  total_sources = result.scalar() or 0  # Returns "42" not 42
  
  # FIX:
  total_sources = _to_int(result.scalar(), 0)
  ```

- `src/cli/commands/discovery_status.py`
- `src/cli/commands/extraction.py` 
- `src/cli/commands/background_processes.py`
- `src/services/url_verification.py`
- `src/services/url_verification_service.py`
- `src/utils/content_cleaning_telemetry.py`

**Action:** Apply `_to_int()` helper (or equivalent) to ALL `.scalar()` calls that expect int results.

#### 2. Row Tuple Indexing with Aggregate Results

**Problem:** `row[1]` returns string "42" on PostgreSQL when it's a COUNT/SUM result.

**Impact:** Printing works, but any arithmetic operations fail.

**Example Locations:**
- `src/cli/commands/pipeline_status.py` line 186:
  ```python
  print(f"    • {row[0]}: {row[1]} URLs")  # row[1] is string on PostgreSQL
  ```

**Action:** Add int() conversion when the column is an aggregate:
```python
print(f"    • {row[0]}: {int(row[1])} URLs")
```

#### 3. Aggregate Results in Status Displays

**Files with aggregate queries needing review:**
- `src/services/url_verification.py` line 714: `SELECT status, COUNT(*) as count`
- `src/cli/commands/extraction.py` line 150: `SELECT cl.status, COUNT(*) as count`
- `src/cli/commands/background_processes.py` lines 186, 203: status COUNT queries
- `src/utils/comprehensive_telemetry.py` line 401: `SELECT COALESCE(MAX(id), 0)`

**Action:** Audit each location and add type conversions where results are used in calculations.

#### 4. Telemetry Store DDL Adaptation

**Current:** `src/telemetry/store.py` `_adapt_ddl_for_dialect()` handles AUTOINCREMENT but NOT:
- `BOOLEAN DEFAULT 0` → Should probably stay as-is (PostgreSQL accepts 0 for FALSE)
- But we should verify INSERT statements also convert Python bool to appropriate value

**Action:** Audit all INSERT operations to ensure boolean values are handled correctly.

### 🔍 POTENTIAL ISSUES - MEDIUM PRIORITY

#### 5. COALESCE/NULLIF Usage

**Status:** COALESCE is standard SQL, works on both databases ✅

Confirmed working in:
- `src/utils/comprehensive_telemetry.py`
- `src/services/url_verification_service.py`
- `src/reporting/county_report.py`

**Action:** No changes needed, but monitor for edge cases.

#### 6. Date/Time Functions

**Status:** Using Python datetime.strftime() for formatting ✅

- `src/utils/telemetry.py` uses `.strftime()` correctly
- No SQLite-specific datetime() or strftime() SQL functions found

**Action:** No changes needed.

#### 7. Boolean Column Comparisons

**Status:** No direct `WHERE is_success = 1` patterns found ✅

Code uses proper boolean Python values in WHERE clauses.

**Action:** No changes needed currently, but add linting rule to prevent future issues.

### 🎯 RECOMMENDED ACTION PLAN

**Phase 1: Critical Fixes (Do Immediately)**
1. Add `_to_int()` helper to each CLI command file that uses aggregates
2. Update all `.scalar() or 0` patterns to `.scalar()` wrapped in `_to_int()`
3. Update row tuple indexing to convert aggregates: `int(row[1])` where applicable
4. Test with PostgreSQL locally before deploying

**Phase 2: Comprehensive Audit**
1. Search for all `SELECT COUNT`, `SELECT SUM`, `SELECT AVG`, `SELECT MAX`, `SELECT MIN`
2. Trace each result through the code to see how it's used
3. Add type conversions at point of use
4. Create unit tests that run against both SQLite and PostgreSQL

**Phase 3: Prevention**
1. Add linting rules to detect `.scalar() or 0` patterns
2. Create wrapper functions for common query patterns
3. Add comprehensive PostgreSQL integration tests for all CLI commands
4. Update copilot-instructions.md with these compatibility requirements

### 📊 ESTIMATED IMPACT

**Files Requiring Changes:** ~15-20 Python files
**Lines to Modify:** ~100-150 locations
**Estimated Time:** 4-6 hours for comprehensive fix
**Risk Level:** MEDIUM - All are non-breaking changes, just adding int() conversions

### ⚠️ CRITICAL WARNING

**DO NOT DEPLOY WITHOUT THESE FIXES**

Production will continue to experience intermittent failures when:
- Pipeline status commands are run
- Discovery summary is generated
- Verification telemetry is displayed
- Any aggregate query result is used in arithmetic

These failures manifest as:
- TypeError: unsupported operand type(s) for /: 'str' and 'int'
- Incorrect comparisons (string "0" > 0 evaluates differently than 0 > 0)
- Silent data corruption if strings are concatenated instead of summed

### 🏃 QUICK WIN: Test One Command End-to-End

Before massive refactor, test `pipeline-status` command thoroughly:
1. Apply `_to_int()` to all 22 locations in pipeline_status.py
2. Run against local PostgreSQL database
3. Verify all counts/sums display correctly
4. Use as template for other commands

### 📝 Notes

- SQLite is more forgiving with type coercion than PostgreSQL
- PostgreSQL's pg8000 driver returns numeric types as strings (not Decimal)
- SQLAlchemy doesn't auto-convert aggregate results
- The `_RowProxy` wrapper preserves both tuple and dict access but doesn't convert types
