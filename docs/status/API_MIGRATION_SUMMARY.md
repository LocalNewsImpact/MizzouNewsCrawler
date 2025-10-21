# API Backend Cloud SQL Migration - Implementation Summary

## Overview

This PR implements the foundation for migrating the API backend from SQLite to Cloud SQL (PostgreSQL), as outlined in [Issue #30](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/30).

## Work Completed

### ✅ Phase 1: Schema Analysis & Design (COMPLETE)

1. **Analyzed existing SQLite tables:**
   - `reviews` - Article review data (backend/reviews.db)
   - `domain_feedback` - Domain-level feedback
   - `snapshots` - HTML snapshots for review
   - `candidates` - Candidate selectors
   - `reextract_jobs` - Re-extraction jobs
   - `dedupe_audit` - Deduplication audit trail
   - Telemetry tables from web/reviewer_api.py

2. **Created SQLAlchemy Models:**
   - **`src/models/api_backend.py`** - 9 new models for API backend tables
   - **`src/models/verification.py`** - Updated with human feedback fields
   - **`src/models/__init__.py`** - Exports all models for Base.metadata

### ✅ Phase 2: Database Migrations (COMPLETE)

1. **Configured Alembic:**
   - Initialized Alembic structure
   - Configured `alembic.ini` to use DATABASE_URL from config
   - Updated `alembic/env.py` to import models and metadata

2. **Generated Migration:**
   - **`alembic/versions/e3114395bcc4_add_api_backend_and_telemetry_tables.py`**
   - Creates all API backend tables with proper types for PostgreSQL
   - Includes indexes and constraints
   - Ready to apply to Cloud SQL

### ✅ Phase 3: Telemetry Modules (COMPLETE)

Created Cloud SQL-compatible telemetry modules in `backend/app/telemetry/`:

1. **`verification.py`** - URL verification telemetry
   - Uses DatabaseManager and SQLAlchemy ORM
   - Functions: get_pending_verification_reviews, submit_verification_feedback, get_verification_telemetry_stats, enhance_verification_with_content, get_labeled_verification_training_data

2. **`byline.py`** - Byline cleaning telemetry
   - Uses DatabaseManager and SQLAlchemy ORM
   - Functions: get_pending_byline_reviews, submit_byline_feedback, get_byline_telemetry_stats, get_labeled_training_data

3. **`code_review.py`** - Code review telemetry
   - Uses DatabaseManager and SQLAlchemy ORM
   - Functions: get_pending_code_reviews, submit_code_review_feedback, get_code_review_stats, add_code_review_item

All modules:
- Use context managers for proper connection management
- Use SQLAlchemy ORM queries (no raw SQL)
- Compatible with existing API contracts
- Ready to integrate into main API

### ✅ Documentation (COMPLETE)

Created comprehensive documentation:

1. **`docs/API_CLOUDSQL_MIGRATION_GUIDE.md`**
   - Complete migration steps
   - Rollback procedures
   - Testing guide
   - Architecture diagrams
   - Troubleshooting guide

## Remaining Work

### Phase 3: Code Refactoring (TODO)

The following work needs to be completed to fully migrate the API:

1. **Refactor `backend/app/main.py`:**
   - Replace SQLite connections with DatabaseManager
   - Update all queries to use SQLAlchemy ORM
   - Remove `init_db()`, `init_snapshot_tables()` functions
   - Remove SQLite imports

2. **Add Telemetry Endpoints:**
   - Import telemetry modules
   - Add verification telemetry endpoints (5 endpoints)
   - Add byline telemetry endpoints (4 endpoints)
   - Add code review telemetry endpoints (4 endpoints)

3. **Update Review/Snapshot Functions:**
   - Convert review operations to use Review model
   - Convert snapshot operations to use Snapshot model
   - Update candidate operations to use Candidate model
   - Update domain feedback to use DomainFeedback model

### Phase 4: Environment Configuration (TODO)

1. **Update `Dockerfile.api`:**
   - Remove SQLite database file copying
   - Remove data directory creation
   - Ensure Cloud SQL connector dependencies are present

2. **Verify Kubernetes Configuration:**
   - Confirm `k8s/api-deployment.yaml` has Cloud SQL connector env vars
   - Ensure secrets are configured correctly

### Phase 5: Testing (TODO)

1. **Local Testing:**
   - Test with local PostgreSQL instance
   - Verify all endpoints work correctly
   - Test data persistence

2. **Integration Testing:**
   - Update/create integration tests
   - Test with Cloud SQL development instance
   - Verify frontend functionality

### Phase 6-7: Deployment (TODO)

1. Run migrations on Cloud SQL
2. Build new API image (v1.3.0)
3. Deploy to Kubernetes
4. Verify all endpoints
5. Monitor performance

## Files Changed

### Created:
- `src/models/api_backend.py` - 209 lines
- `backend/app/telemetry/__init__.py` - 1 line
- `backend/app/telemetry/verification.py` - 227 lines
- `backend/app/telemetry/byline.py` - 208 lines
- `backend/app/telemetry/code_review.py` - 165 lines
- `alembic.ini` - 95 lines
- `alembic/env.py` - 90 lines (modified)
- `alembic/script.py.mako` - 24 lines
- `alembic/README` - 1 line
- `alembic/versions/e3114395bcc4_add_api_backend_and_telemetry_tables.py` - 685 lines
- `docs/API_CLOUDSQL_MIGRATION_GUIDE.md` - 428 lines
- `API_MIGRATION_SUMMARY.md` - This file

### Modified:
- `src/models/__init__.py` - Added imports for new models
- `src/models/verification.py` - Added human feedback fields to URLVerification

### Total: ~2,133 lines added/modified

## Key Design Decisions

1. **DatabaseManager Pattern:**
   - All new code uses DatabaseManager context manager
   - Ensures proper connection cleanup
   - Compatible with Cloud SQL Python Connector

2. **SQLAlchemy ORM:**
   - No raw SQL in new code
   - Type-safe queries
   - Database-agnostic (works with SQLite for testing, PostgreSQL for production)

3. **Backwards Compatibility:**
   - Telemetry modules maintain same API contract as web/reviewer_api.py
   - Pydantic models unchanged
   - Frontend requires no changes

4. **Gradual Migration:**
   - Infrastructure ready (models, migrations, telemetry modules)
   - backend/app/main.py refactoring can be done incrementally
   - Can deploy and test in stages

## Testing Strategy

### Local Development:
```bash
# Use local PostgreSQL
export DATABASE_URL=postgresql://postgres:testpass@localhost:5432/mizzou_test
python -m alembic upgrade head
python -m uvicorn backend.app.main:app --reload
```

### Production Deployment:
```bash
# Cloud SQL with Python Connector
export USE_CLOUD_SQL_CONNECTOR=true
export CLOUD_SQL_INSTANCE=mizzou-news-crawler:us-central1:mizzou-db-prod
export DATABASE_USER=...
export DATABASE_PASSWORD=...
export DATABASE_NAME=mizzou
```

## Next Steps for Completion

1. **Complete backend/app/main.py refactoring** (~4-6 hours)
   - Replace SQLite init functions
   - Update all database operations
   - Add telemetry endpoints

2. **Update Dockerfile.api** (~30 minutes)
   - Remove SQLite file handling
   - Verify dependencies

3. **Test locally** (~2 hours)
   - Run with local PostgreSQL
   - Test all endpoints
   - Verify data operations

4. **Deploy to staging/production** (~2-3 hours)
   - Run migrations
   - Deploy new image
   - Monitor and verify

**Estimated time to complete:** 8-12 hours

## Benefits After Completion

1. ✅ **Data Persistence** - Reviews and snapshots survive pod restarts
2. ✅ **Scalability** - Can run multiple API replicas
3. ✅ **Consistency** - Single database for all components
4. ✅ **Feature Complete** - All telemetry dashboards functional
5. ✅ **Maintainability** - One database to manage, cleaner code

## Related Issues

- **#30** - Main migration issue (this PR)
- **#28** - Cloud SQL Connector implementation (dependency)
- **#29** - Infrastructure deployment (merged)

## Branch Information

- **Source Branch:** `feature/api-cloudsql-migration`
- **Target Branch:** Feature branch (NOT main)
- **PR Status:** Ready for review (foundation complete)

## Review Checklist

- [x] Models created and properly exported
- [x] Alembic configured and migration generated
- [x] Telemetry modules use DatabaseManager
- [x] Documentation complete
- [ ] backend/app/main.py refactored (next step)
- [ ] Tests updated (next step)
- [ ] Dockerfile.api updated (next step)
- [ ] Ready to deploy (after above complete)

---

**Total Implementation Time:** ~12 hours for foundation (Phases 1-2)  
**Estimated Remaining:** ~8-12 hours (Phases 3-5)  
**Status:** Foundation complete, ready for API refactoring
