# SQLite Code Remaining in Codebase - Comprehensive Audit

**Date**: October 11, 2025  
**Status**: 🔴 **MIGRATION INCOMPLETE**

## Executive Summary

The Cloud SQL migration is **NOT complete**. While main query paths were migrated, many helper methods and utility files still use SQLite cursor API (`cursor.execute()`, `conn.commit()`). This creates technical debt and potential runtime errors.

## ✅ Just Fixed (Commit 540ec17)

Fixed 4 critical methods in `src/utils/content_cleaner_balanced.py`:
- `_clear_wire_classification()` - line 1319
- `_get_article_authors()` - line 1339  
- `_get_article_source_context()` - line 1641
- `_mark_article_as_wire()` - line 1879

All converted from `cursor.execute()` → `session.execute(sql_text())`

---

## 🔴 ACTIVE FILES STILL USING SQLITE

### 1. **src/cli/commands/content_cleaning.py** - CRITICAL
**Status**: 🔴 **ACTIVE** - CLI commands used in production  
**SQLite Usage**: 5 locations
- Line 184: `sqlite3.connect(db_path)` in helper function
- Line 428: `sqlite3.connect(db_path)` in helper function
- Line 524: `sqlite3.connect(db_path)` in helper function
- Line 647: `sqlite3.connect("mizzou.db")` in helper function
- Line 716: `sqlite3.connect("mizzou.db")` in helper function

**Impact**: These are CLI utility functions. May fail if called on Cloud SQL.  
**Priority**: 🔴 **HIGH** - Active CLI commands

---

### 2. **src/pipeline/io_utils.py** - CRITICAL
**Status**: 🔴 **ACTIVE** - I/O utilities used across pipeline  
**SQLite Usage**: 1 location
- Line 231: `sqlite3.connect(db_path)`

**Impact**: Pipeline operations may fail on Cloud SQL.  
**Priority**: 🔴 **HIGH** - Core pipeline infrastructure

---

### 3. **src/utils/telemetry.py** - CRITICAL
**Status**: 🔴 **ACTIVE** - Telemetry system (1691 lines)  
**SQLite Usage**: Entire file uses SQLite
- Line 19: `import sqlite3`
- Line 255: `def _apply_schema(conn: sqlite3.Connection, ...)`
- Line 678: `def writer(conn: sqlite3.Connection)`
- Line 1026: `def writer(conn: sqlite3.Connection)`
- Line 1546: `def writer(conn: sqlite3.Connection)`
- Line 1690: `def writer(conn: sqlite3.Connection)`

**Impact**: All telemetry writes use SQLite. Telemetry probably failing on Cloud SQL.  
**Priority**: 🔴 **HIGH** - Important for observability

**Note**: There's already a `src/telemetry/store.py` that wraps SQLAlchemy connections with SQLite-compatible API. This file may need similar treatment.

---

### 4. **src/utils/extraction_telemetry.py**
**Status**: 🔴 **ACTIVE** - Extraction-specific telemetry  
**SQLite Usage**: 
- Line 6: `import sqlite3`
- Line 182: `def writer(conn: sqlite3.Connection)`

**Impact**: Extraction telemetry may be failing silently.  
**Priority**: 🟡 **MEDIUM** - Extraction works without it, but we lose observability

---

### 5. **src/utils/content_cleaning_telemetry.py**
**Status**: 🔴 **ACTIVE** - Cleaning-specific telemetry  
**SQLite Usage**:
- Line 9: `import sqlite3`
- Line 279: `def writer(conn: sqlite3.Connection)`
- Line 312: `conn: sqlite3.Connection`
- Line 411: `conn: sqlite3.Connection`
- Line 630: `conn: sqlite3.Connection`
- Line 766: `def _ensure_tables_exist(self, conn: sqlite3.Connection)`

**Impact**: Cleaning telemetry may be failing silently.  
**Priority**: 🟡 **MEDIUM** - Cleaning works without it, but we lose observability

---

### 6. **src/utils/byline_cleaner.py**
**Status**: 🔴 **ACTIVE** - Byline cleaning utilities  
**SQLite Usage**:
- Line 1740: `import sqlite3`
- Line 1745: `conn = sqlite3.connect(db_path)`

**Impact**: Byline cleaning operations may fail.  
**Priority**: 🟡 **MEDIUM** - Part of content cleaning pipeline

---

### 7. **src/models/database.py**
**Status**: 🔴 **ACTIVE** - Core database module  
**SQLite Usage**:
- Line 256: `import sqlite3 as _sqlite`

**Impact**: Imported but may not be used. Need to verify.  
**Priority**: 🟢 **LOW** - Likely just for type hints or fallback

---

## 🟡 LEGACY CLEANER VARIANTS (Probably Unused)

These are old content cleaner implementations, likely superseded by `content_cleaner_balanced.py`:

1. **src/utils/content_cleaner_final.py**
   - Line 11: `import sqlite3`
   - Line 146: `sqlite3.connect(self.db_path)`

2. **src/utils/content_cleaner_improved.py**
   - Line 7: `import sqlite3`
   - Line 212: `sqlite3.connect(self.db_path)`

3. **src/utils/content_cleaner_strict.py**
   - Line 5: `import sqlite3`
   - Line 51: `sqlite3.connect(self.db_path)`

4. **src/utils/content_cleaner_fast.py**
   - Line 5: `import sqlite3`
   - Line 50: `sqlite3.connect(self.db_path)`
   - Line 178: `sqlite3.connect(self.db_path)`

5. **src/utils/content_cleaner_exact.py**
   - Line 5: `import sqlite3`
   - Line 52: `sqlite3.connect(self.db_path)`

6. **src/utils/content_cleaner_twophase.py**
   - Line 5: `import sqlite3`
   - Line 54: `sqlite3.connect(self.db_path)`

7. **src/utils/content_cleaner_proper_boundaries.py**
   - Line 5: `import sqlite3`
   - Line 55: `sqlite3.connect(self.db_path)`
   - Line 229: `sqlite3.connect(self.db_path)`

**Recommendation**: Verify these are unused, then DELETE them to avoid confusion.

---

## 🔵 MAINTENANCE SCRIPTS (Non-Production)

### src/scripts/maintenance/clean_authors.py
**Status**: 🔵 **MAINTENANCE SCRIPT** - Not used in production pipeline  
**SQLite Usage**:
- Line 7: `import sqlite3`
- Line 17: `def get_database_connection(db_path: str) -> sqlite3.Connection`
- Line 19: `conn = sqlite3.connect(db_path)`

**Priority**: 🟢 **LOW** - Only used for one-off maintenance tasks

---

## 📄 DOCUMENTATION (No Action Needed)

These are just documentation files with example code:
- `CLOUD_SQL_MIGRATION_COMPLETION_SUMMARY.md`
- `API_CLOUDSQL_MIGRATION_STATUS.md`
- `CUSTOM_SOURCELIST_WORKFLOW.md`
- `CRON_ENABLED_FLAG.md`
- etc.

---

## 🎯 Recommended Action Plan

### Phase 1: Critical Fixes (This Week)
1. ✅ **DONE**: content_cleaner_balanced.py (4 methods)
2. 🔴 **TODO**: src/cli/commands/content_cleaning.py (5 functions)
3. 🔴 **TODO**: src/pipeline/io_utils.py (1 function)
4. 🔴 **TODO**: src/utils/telemetry.py (entire file - big job)

### Phase 2: Medium Priority (Next Week)
5. 🟡 **TODO**: src/utils/extraction_telemetry.py
6. 🟡 **TODO**: src/utils/content_cleaning_telemetry.py
7. 🟡 **TODO**: src/utils/byline_cleaner.py

### Phase 3: Cleanup (When Time Permits)
8. 🟢 **TODO**: Delete legacy content_cleaner_*.py variants
9. 🟢 **TODO**: Audit src/models/database.py sqlite3 import

---

## Why This Happened

The migration focused on **main query paths** (discovery, extraction, cleaning, analysis) but **missed helper methods**:

1. **Helper methods in content_cleaner_balanced.py**: Domain analysis, wire detection, author fetching used old cursor API
2. **Telemetry systems**: Entire telemetry stack still expects SQLite
3. **CLI utilities**: CLI helper functions still use sqlite3.connect()
4. **Legacy variants**: Old content cleaner implementations never cleaned up

**Root Cause**: Incomplete code review during migration. Focused on "does it work?" instead of "is every SQLite reference gone?"

---

## Impact Assessment

### Currently Working ✅
- Main article pipeline (discovery, extraction, cleaning, analysis)
- API endpoints
- Cron jobs
- Most CLI commands

### Potentially Broken ❌
- Telemetry collection (silently failing?)
- Some CLI utility functions
- Domain analysis (just fixed!)
- Wire detection persistence (just fixed!)
- Byline cleaning edge cases

### Technical Debt 📊
- ~10 active files still using SQLite
- ~7 legacy files that should be deleted
- Mixed codebase (some SQLAlchemy, some cursor API)
- Confusing for developers

---

## Testing Recommendations

After fixing each file:
1. **Unit tests**: Verify functions work with DatabaseManager
2. **Integration tests**: Run full pipeline on test dataset
3. **Telemetry validation**: Confirm telemetry writes to Cloud SQL
4. **CLI testing**: Test all CLI commands against Cloud SQL

---

## Questions for User

1. **Telemetry Priority**: How important is telemetry? Should this be Phase 1?
2. **Legacy Cleaners**: Can I delete the 7 old content_cleaner_*.py variants?
3. **Testing**: Do you want me to fix these incrementally with tests, or bulk fix?
4. **Timeframe**: What's the urgency? This week? Next sprint?

---

**Bottom Line**: The migration touched ~70% of SQLite code but left ~30% untouched. Most critical paths work, but edge cases and observability are compromised.
