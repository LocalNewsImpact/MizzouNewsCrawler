# Comment for PR #99: Incorrect Database Default Assumption

## Issue with PR Description

This PR states: **"Since SQLite is the default database, this caused silent query failures with no error visibility."**

However, this assumption is **incorrect for the deployment context** of this PR.

## Evidence

### 1. Target Branch Context

This PR targets the `feature/gcp-kubernetes-deployment` branch, which is specifically for Google Cloud Platform Kubernetes deployment, not local development.

### 2. Environment Configuration

According to `.env.example`:

```env
# Database configuration
# Option A: use a full database URL (default for local development)
DATABASE_URL=sqlite:///data/mizzou.db
# Option B: compose a URL automatically from discrete settings (recommended for Kubernetes)
DATABASE_ENGINE=postgresql+psycopg2
DATABASE_HOST=
DATABASE_PORT=5432
...
```

The file explicitly states:
- **Local development**: SQLite is the default
- **Kubernetes deployment** (the context of this PR): PostgreSQL is **recommended**

### 3. README Documentation

The README.md states:
> "A CSV-to-Database-driven production version of MizzouNewsCrawler with **SQLite backend**."
> 
> "**Phase 1 — Script-based**: CSV-to-Database-driven crawler with CLI interface and SQLite backend"
> 
> "**Phase 2 — Production**: Deploy on GKE with **Postgres**, orchestrate with Kubernetes jobs"

This clearly indicates SQLite is for Phase 1 (local/script-based), while PostgreSQL is for Phase 2 (production/GKE deployment).

## Implications

Since this PR is being merged into the `feature/gcp-kubernetes-deployment` branch (Phase 2), the correct statement should be:

> "Since **PostgreSQL** is the expected database for production Kubernetes deployment, the use of PostgreSQL-specific SQL syntax (`DISTINCT ON`) is actually **appropriate** for this deployment context."

## Impact on the Fixes

While the PR correctly adds database compatibility to support **both** SQLite and PostgreSQL (which is good for development and testing), the narrative that frames this as "fixing SQLite compatibility because SQLite is the default" is misleading in the production/Kubernetes context.

### Correct Framing

The fixes should be described as:
1. **Primary goal**: Ensure the code works in the production PostgreSQL environment
2. **Secondary benefit**: Add SQLite compatibility for local development and testing

Not the other way around.

## Recommendation

The PR description and related documentation should be updated to reflect the correct database hierarchy:
- **Production/Kubernetes (this branch)**: PostgreSQL is the primary/default database
- **Local development**: SQLite is supported for convenience
- **Compatibility layer**: Supports both databases for flexibility

The current framing implies SQLite is the default across all contexts, which is inaccurate for the production deployment this branch targets.

---

**References**:
- `.env.example` lines 8-18: Explicitly designates SQLite for local dev, PostgreSQL for Kubernetes
- `README.md` lines 5, 11-13: Phase 1 uses SQLite, Phase 2 (production) uses Postgres
- Target branch: `feature/gcp-kubernetes-deployment` (production context)
