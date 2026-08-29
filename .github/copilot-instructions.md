# GitHub Copilot Instructions

## System Architecture Overview

MizzouNewsCrawler is a **cloud-native news discovery and analysis pipeline** running on Google Kubernetes Engine (GKE) with microservices architecture.

### Core Services (Kubernetes Deployments)

1. **API Service** (`mizzou-api`): FastAPI backend exposing telemetry, admin endpoints, and web data (1 replica, LoadBalancer)
2. **Processor Service** (`mizzou-processor`): Continuous background processor for cleaning, ML analysis, and entity extraction (1 replica)
3. **Argo Workflows**: Orchestrates discovery, verification, and extraction jobs via CronWorkflow (every 6 hours)

### Data Pipeline Flow

```
RSS/Sitemaps → Discovery (Argo) → candidate_links (status='discovered')
              ↓
Verification (Argo) → StorySniffer validation → status='article'
              ↓
Extraction (Argo) → fetch article content → articles (status='extracted')
              ↓
Cleaning (Processor) → remove boilerplate → status='cleaned'
              ↓
ML Analysis (Processor) → CIN classification → status='labeled' + article_labels
              ↓
Entity Extraction (Processor) → gazetteer NER → locations table
              ↓
BigQuery Export → analytics datasets
```

### Infrastructure

- **Database**: Cloud SQL PostgreSQL (`mizzou-db-prod-ssd`) via Cloud SQL Connector (no proxy sidecar)
- **Container Registry**: Artifact Registry (`us-central1-docker.pkg.dev/mizzou-news-crawler`)
- **Build System**: Cloud Build with selective service detection (only rebuilds changed services)
- **Orchestration**: Argo Workflows with dataset-specific CronWorkflows

## Critical Rules - DO NOT VIOLATE

### 1. **NEVER look for production data in the local database**
- The local database is EMPTY or STALE
- Production data is ONLY in Cloud SQL (mizzou-db-prod-ssd)
- Always access production data via `kubectl exec` into a production pod
- If you try to test against local data, you're wasting everyone's time

### 2. **NEVER rebuild/deploy services manually**
- ALL deployments go through CI/CD ONLY (GitHub Actions → Cloud Build → Cloud Deploy)
- Do NOT run `./scripts/deploy-services.sh` from your machine
- Changes are deployed via PR merge to main branch
- Ask user to merge if they want deployment, don't assume you can deploy

### 3. **Always implement minimum code changes to accomplish the task**
- Each change should be surgical and focused
- No extraneous refactoring or "improvements"
- No removing unused code unless explicitly asked
- No reorganizing imports or formatting unless necessary for the feature

### 4. **NEVER disable, remove, or bypass a broken feature**
- If Selenium is broken → FIX the Chrome crash (diagnose why Chrome exits)
- If a method fails → DEBUG and fix it, don't remove it
- If a feature is slow → OPTIMIZE it, don't disable it
- Only disable/remove/bypass if explicitly requested by the user
- Workarounds hide bugs; fixes solve them

### 5. **NEVER push with --no-verify to bypass CI/CD checks**
- Pre-push hooks exist to prevent broken code from reaching the repository
- **NEVER** use `git push --no-verify` regardless of whether errors seem "unrelated"
- If linting/testing fails, fix the errors in the codebase BEFORE pushing
- Pre-existing errors in other files are NOT a reason to bypass CI/CD
- The pre-push hook checks ALL files, not just your changes - this is intentional
- Work with the user to fix root causes, don't hide problems with bypass flags
- If you can't fix an error, explain it to the user and ask for guidance

### 6. **ALWAYS use local Docker for local CI/CD validation**
- Docker is set up and running in the local environment
- When pushing code, the pre-push hook runs Docker-based tests locally (./scripts/test-production-readiness.sh)
- **NEVER skip Docker tests** with environment variables like `NO_DOCKER_BUILD=1` or `SKIP_DOCKER_TESTS=1`
- Docker containers ensure consistent test environment matching production
- If Docker tests fail locally, diagnose and fix the issue FIRST before pushing
- Local Docker validation catches issues before they reach GitHub CI
- Do NOT rely on "it will work in CI" - fix all Docker test failures locally

### 7. **NEVER INTERRUPT LOCAL CI/CD PROCESSES**
- **NEVER** send Ctrl-C or interrupt `git push` while tests are running
- **NEVER** interrupt pre-push hooks, pre-commit hooks, or any test execution
- **NEVER** use background mode for git push (`isBackground: true`) - tests must complete
- Let ALL tests run to completion, even if they take 10+ minutes
- If tests are failing, wait for them to fail completely and show the errors
- Interrupting tests wastes time and forces re-running everything
- Be patient: local CI/CD is validating your changes before they hit GitHub
- If you need to stop a test run, tell the user first and explain why

### 8. **ALWAYS look up table schema before writing queries**
- **NEVER** assume column names exist - query `information_schema.columns` first
- Before writing ANY SQL query, verify the actual table structure:
  ```sql
  SELECT column_name FROM information_schema.columns 
  WHERE table_name = 'your_table' ORDER BY ordinal_position
  ```
- Column names change over time - don't rely on memory or assumptions
- This applies to ALL tables: `sources`, `candidate_links`, `articles`, etc.
- If a query fails with "column does not exist", you violated this rule

### 9. **ALWAYS use script files for database queries - NEVER heredoc or inline quotes**
- Heredoc (`<<EOF`) and complex quote escaping break the terminal
- Write queries to a script file first (e.g., `/tmp/query.py`), then `kubectl cp` and execute
- This prevents quote escaping hell and makes debugging easier
- Pattern:
  ```bash
  # 1. Create script locally
  cat > /tmp/my_query.py << 'EOF'
  from src.models.database import DatabaseManager
  ...
  EOF
  
  # 2. Copy to pod and execute
  kubectl cp /tmp/my_query.py production/$(kubectl get pod -n production -l app=mizzou-api -o jsonpath='{.items[0].metadata.name}'):/app/my_query.py
  kubectl exec -n production deployment/mizzou-api -- python /app/my_query.py
  ```

## Database Query Protocol

### Production Database Access (PostgreSQL via Cloud SQL)

**CRITICAL: ALWAYS use `kubectl exec` to query production data. The local environment DOES NOT connect to production.**

To query the production database, execute Python scripts inside a running pod (API or Processor) in the `production` namespace.

```bash
# Standard query pattern (USE THIS):
kubectl exec -n production deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('YOUR SQL HERE')).fetchall()
    for row in result:
        print(row)
"
```

**Common queries:**

```python
# Check unextracted articles for a source
result = session.execute(text('''
    SELECT COUNT(*) FROM candidate_links
    WHERE source = 'example.com'
    AND status = 'article'
    AND id NOT IN (SELECT candidate_link_id FROM articles WHERE candidate_link_id IS NOT NULL)
''')).scalar()

# Table counts
result = session.execute(text('''
    SELECT
        (SELECT COUNT(*) FROM candidate_links) as candidates,
        (SELECT COUNT(*) FROM articles) as articles,
        (SELECT COUNT(*) FROM sources) as sources
''')).fetchone()

# Recent articles by source (last 24h)
results = session.execute(text('''
    SELECT cl.source, COUNT(*) as cnt
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE a.extracted_at >= NOW() - INTERVAL '24 hours'
    GROUP BY cl.source ORDER BY cnt DESC LIMIT 10
''')).fetchall()
```

**Key Schema Reference:**

- `candidate_links`: Discovered URLs (id, url, source, status, discovered_at, source_id FK)
  - Status progression: `new` → `discovered` → `article` → article extraction
- `articles`: Extracted content (id, candidate_link_id FK, url, title, author, text, extracted_at)
  - Status progression: `extracted` → `cleaned` → `labeled`
- `sources`: Publishers (id, host, canonical_name, city, county, status)
- `article_entities`: NER results (article_id FK, entity_text, entity_type, extractor_version)
- `article_labels`: ML classifications (article_id FK, label, confidence, label_version)

**NEVER:**
- **NEVER** assume the local `venv` connects to production database (it uses local SQLite/empty Postgres)
- **NEVER** run local queries expecting production results
- Don't forget `text()` wrapper for raw SQL in SQLAlchemy

## Development Workflows

### Build & Deployment System

**Selective Service Builds**: The CI/CD pipeline intelligently rebuilds only changed services (60% faster, 50-83% cost reduction).

**Build dependency hierarchy:**
```
Dockerfile.base (Python, system deps) → ALL services depend on this
    ↓
Dockerfile.ml-base (PyTorch, transformers) → Only processor depends on this
    ↓
Service-specific Dockerfiles:
    - Dockerfile.api (FastAPI, backend dependencies)
    - Dockerfile.crawler (Selenium, ChromeDriver)
    - Dockerfile.processor (ML models, NER tools)
```

**Deployment commands (from local dev):**

```bash
# Deploy specific services to GKE (triggers Cloud Build + Cloud Deploy)
./scripts/deploy-services.sh main api processor

# Deploy all services (full rebuild: base → ml-base → api/crawler/processor)
./scripts/deploy-services.sh main all

# Deploy only CI/CD services (api, crawler, processor - skips base images)
./scripts/deploy-services.sh main ci

# Test what would be rebuilt from your current changes
./scripts/test-selective-build.sh origin/main HEAD
```

**VS Code tasks available** (see tasks in workspace):
- `GCP: Build & Deploy API/Crawler/Processor` - Individual service builds
- `GCP: Build & Deploy All Services` - Full rebuild
- `Argo: Submit Workflow` - Manually trigger pipeline

### Testing Strategy

**Three test environments:**
1. **Unit tests**: Fast, no database (`-m "not integration and not postgres"`)
2. **Integration tests (SQLite)**: In-memory SQLite, fast setup
3. **PostgreSQL integration tests**: Docker container with PostgreSQL 15

**Critical pytest markers:**
- `@pytest.mark.integration`: Runs in postgres-integration job (requires cloud_sql_session fixture)
- `@pytest.mark.postgres`: PostgreSQL-specific syntax (FOR UPDATE SKIP LOCKED, etc.)
- `@pytest.mark.e2e`: End-to-end smoke tests in production
- `@pytest.mark.slow`: Tests >5 seconds (deselected by default)

**Running tests locally:**

```bash
# Full CI suite (matches GitHub Actions exactly)
make test-ci

# Unit tests only (fast)
make test-unit

# PostgreSQL integration tests (requires Docker)
make test-postgres

# Run smoke tests against production
./scripts/run-production-smoke-tests.sh
```

### CLI Command Structure

**All pipeline commands use modular CLI** (`src/cli/cli_modular.py`):

```bash
# Discovery commands
python -m src.cli.cli_modular discover-urls [--force-all]
python -m src.cli.cli_modular discovery-status [--hours 24]

# Processing commands
python -m src.cli.cli_modular verify-urls --batch-size 10
python -m src.cli.cli_modular extract --limit 20
python -m src.cli.cli_modular clean-articles --batch-size 50
python -m src.cli.cli_modular analyze --batch-size 16
python -m src.cli.cli_modular extract-entities --batch-size 500

# Monitoring commands
python -m src.cli.cli_modular pipeline-status --hours 24
python -m src.cli.cli_modular telemetry --interval 60

# Source management
python -m src.cli.cli_modular load-sources --file sources/mizzou_sources.csv
python -m src.cli.cli_modular list-sources [--county Boone]
```

**Feature flags in processor** (`orchestration/continuous_processor.py`):
- `ENABLE_DISCOVERY=false` (default: Argo handles this)
- `ENABLE_VERIFICATION=false` (default: Argo handles this)
- `ENABLE_EXTRACTION=false` (default: Argo handles this)
- `ENABLE_CLEANING=true` (processor handles article cleaning)
- `ENABLE_ML_ANALYSIS=true` (processor handles CIN classification)
- `ENABLE_ENTITY_EXTRACTION=true` (processor handles gazetteer NER)
- `ENABLE_WIRE_DETECTION=true` (processor handles wire service detection)

### Extraction Site-Access Testing Protocol

**CRITICAL:** When debugging extraction-path site access (PerimeterX, Akamai, captcha loops, etc.), run HTTP/S tests from an active extraction pod, never from the processor or API deployments. Only extraction pods faithfully reproduce crawler behavior (ChromeDriver, stealth headers, proxy wiring); other services are fine for unit/integration testing but will give misleading results for extraction diagnostics.

1. Locate a running extraction pod (names start with `extraction-`) via `kubectl get pods -n production | grep extraction-`.
2. Exec into that pod/container and run your `curl`, Python, or Selenium snippet there:

  ```bash
  kubectl exec -n production extraction-abcdef-12345 -- bash -c "python /app/scripts/debug_request.py"
  ```

3. Capture the exact response (status, headers, challenge HTML) before switching proxies or adjusting retry budgets.

**Never** run site-access diagnostics from processor or API pods—add any temporary tooling directly to the extraction image if needed.

## Integration Points & Cross-Component Patterns

### MediaCloud Wire Detection

**Purpose**: Identify syndicated/wire service content to exclude from local news analysis.

**Integration flow:**
```python
# In processor (orchestration/continuous_processor.py)
from src.services.wire_detection import MediaCloudDetector

detector = MediaCloudDetector.from_token(
    os.getenv("MEDIACLOUD_API_TOKEN"),
    rate_per_minute=2.0  # Rate limiting
)

# Check article for wire service match
result = detector.search_headline(article.title, article.url)
if result.is_wire:
    article.wire_check_status = "wire"
    article.wire_service_name = result.wire_service_name
else:
    article.wire_check_status = "local"
```

**Key configuration:**
- `MEDIACLOUD_API_TOKEN`: Stored in GCP Secret Manager, auto-resolved from environment
- Rate limiting: Default 2 requests/minute (configurable via `MEDIACLOUD_RATE_PER_MINUTE`)
- Only processes articles with status: `cleaned`, `local`, `labeled`, `classified`

### BigQuery Export Integration

**Architecture**: Uses Google Cloud Datastream for CDC (Change Data Capture) replication, NOT manual export code.

**Schema location**: `bigquery/schema.sql` (reference documentation)

**Export criteria:**
- Only exports articles with `status='labeled'` AND `wire_check_status IN ('local', 'complete')`
- Excludes wire service content automatically
- Partitioned by `published_date` for query efficiency

**Tables exported:**
- `articles`: Main fact table with content, classifications, entities
- `cin_labels`: CIN classification results (nested in articles)
- `entities`: Geographic entities and locations (nested in articles)

**Manual removal workflow** (if needed):
```bash
# Generate removal CSV
python scripts/backfill_wire_status.py

# Remove from BigQuery
python scripts/remove_wire_from_bigquery.py wire_articles.csv
```

### Argo Workflow Management

**Workflow structure:**
- `base-pipeline-workflow.yaml`: Reusable WorkflowTemplate (dataset-agnostic)
- `mizzou-pipeline-cronworkflow.yaml`: Mizzou-specific CronWorkflow (runs every 6 hours)
- `rbac.yaml`: ServiceAccount permissions

**Common operations:**

```bash
# Deploy all workflows
./scripts/deploy_argo_workflows.sh

# Manually trigger a workflow run
argo submit --from cronwf/mizzou-news-pipeline -n production

# Check workflow status
argo list -n production

# View workflow logs
argo logs -n production <workflow-name>

# Delete failed workflows
argo delete -n production <workflow-name>

# Port-forward Argo UI (opens on localhost:2746)
kubectl port-forward -n production svc/argo-server 2746:2746
# Or use VS Code task: "Argo: Port Forward UI"
```

**Workflow parameters** (in CronWorkflow):
- `max-articles`: Articles to discover per source (default: 50)
- `days-back`: How far back to scan feeds (default: 7)
- `verify-batch-size`: URLs verified per batch (default: 50)
- `extract-limit`: Max articles per extraction batch (default: 3)
- `extract-batches`: Number of extraction batches (default: 667)
- `inter-request-min/max`: Rate limiting delays (5-15s)

### Cloud Deploy Release Process

**Architecture**: Cloud Build → Cloud Deploy → GKE rollout

**Trigger deployment:**
```bash
# From local machine (triggers Cloud Build)
./scripts/deploy-services.sh main api processor

# From GitHub Actions (automatic on PR merge)
# - Detects changed services
# - Triggers only affected builds
# - Creates Cloud Deploy release
# - GKE rollout happens automatically
```

**Monitor deployment:**
```bash
# Check Cloud Deploy release status
gcloud deploy releases list --delivery-pipeline=mizzou-news-crawler

# Check GKE rollout status
kubectl rollout status deployment/mizzou-api -n production
kubectl rollout status deployment/mizzou-processor -n production

# View recent rollout history
kubectl rollout history deployment/mizzou-processor -n production
```

**Rollback procedure:**
```bash
# Rollback to previous revision
kubectl rollout undo deployment/mizzou-processor -n production

# Rollback to specific revision
kubectl rollout undo deployment/mizzou-processor -n production --to-revision=5
```

## Debugging Workflows

### Pod Won't Start / CrashLoopBackOff

**Diagnosis steps:**
```bash
# 1. Check pod status
kubectl get pods -n production -l app=mizzou-processor

# 2. Describe pod for events
kubectl describe pod -n production <pod-name>

# 3. Check logs (if container started at all)
kubectl logs -n production <pod-name> --previous  # Previous crashed container
kubectl logs -n production <pod-name>  # Current container

# 4. Check image pull status
kubectl get events -n production --sort-by='.lastTimestamp' | grep <pod-name>
```

**Common issues:**
- **ImagePullBackOff**: Image tag doesn't exist in Artifact Registry → Check Cloud Build status
- **ConfigMapNotFound**: Missing ConfigMap → Apply: `kubectl apply -f k8s/origin-sitecustomize-configmap.yaml`
- **Cloud SQL connection failed**: Workload Identity not configured → Check service account IAM bindings
- **OOMKilled**: Memory limit too low → Increase in deployment YAML

### Migration Failed

**Diagnosis:**
```bash
# Run migration manually in pod
kubectl exec -n production deployment/mizzou-api -- alembic upgrade head

# Check current migration version
kubectl exec -n production deployment/mizzou-api -- alembic current

# View migration history
kubectl exec -n production deployment/mizzou-api -- alembic history

# Downgrade one revision
kubectl exec -n production deployment/mizzou-api -- alembic downgrade -1
```

**Common issues:**
- **Revision not found**: Alembic version table out of sync → Check `alembic_version` table
- **Column already exists**: Migration ran partially → Manual schema inspection needed
- **Connection timeout**: Cloud SQL connector issue → Check IAM permissions

### Database Connection Issues

**Test connection from pod:**
```bash
# Test raw PostgreSQL connection
kubectl exec -n production deployment/mizzou-api -- python -c "
import psycopg2
conn = psycopg2.connect(
    host='127.0.0.1',
    port=5432,
    user='mizzou_user',
    password='PASSWORD_FROM_SECRET',
    database='mizzou_production'
)
print('Connection successful!')
conn.close()
"

# Test Cloud SQL Connector
kubectl exec -n production deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('SELECT 1')).scalar()
    print(f'Query result: {result}')
"
```

### Workflow Stuck / Not Progressing

**Diagnosis:**
```bash
# Check workflow status
argo get -n production <workflow-name>

# View step logs
argo logs -n production <workflow-name> -c <step-name>

# Check if waiting for resources
kubectl describe workflow -n production <workflow-name>

# Check pending pods
kubectl get pods -n production --field-selector=status.phase=Pending
```

**Common issues:**
- **Pending indefinitely**: Resource limits exceeded → Check cluster capacity
- **Step failed silently**: Check container logs for the specific step
- **Verification/extraction idle**: No work available → Expected behavior, workflow will timeout gracefully

### High Error Rate / Performance Issues

**Check metrics:**
```bash
# Pipeline status (last 24 hours)
kubectl exec -n production deployment/mizzou-processor -- \
  python -m src.cli.cli_modular pipeline-status --hours 24

# Check error logs
kubectl logs -n production -l app=mizzou-processor --tail=500 | grep ERROR

# Check pod resource usage
kubectl top pods -n production

# Check database connection pool
kubectl exec -n production deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
db = DatabaseManager()
print(db.engine.pool.status())
"
```

## Local Development with Docker Compose

### Quick Start

```bash
# Build base image once
docker-compose --profile base build base

# Start PostgreSQL + API
docker-compose up -d postgres api

# Start with all services
docker-compose up -d

# Start specific profiles
docker-compose --profile crawler up -d  # Postgres + Crawler
docker-compose --profile processor up -d  # Postgres + Processor
docker-compose --profile work-queue up -d  # Postgres + Work Queue
docker-compose --profile tools up -d  # Postgres + Adminer (DB UI)
```

### Database Management

```bash
# Access Adminer UI (database web interface)
docker-compose --profile tools up -d adminer
# Open http://localhost:8080
# Server: postgres, User: mizzou_user, Password: mizzou_pass, DB: mizzou

# Run migrations locally
docker-compose exec api alembic upgrade head

# Reset database (DESTRUCTIVE)
docker-compose down -v  # Removes postgres_data volume
docker-compose up -d postgres
docker-compose exec api alembic upgrade head
```

### Testing Workflows Locally

```bash
# Run discovery locally
docker-compose run --rm crawler python -m src.cli.cli_modular discover-urls --max-articles 10

# Run extraction locally
docker-compose run --rm processor python -m src.cli.cli_modular extract --limit 5

# Run full pipeline locally (orchestration script)
docker-compose run --rm processor python orchestration/continuous_processor.py
```

### Volume Mounts & Hot Reload

**API service has hot reload enabled** (uvicorn --reload):
- Edit files in `backend/`, `src/` → Changes apply immediately
- No rebuild needed for Python code changes

**Processor/Crawler services do NOT auto-reload**:
- Code changes require container restart: `docker-compose restart processor`
- Or rebuild: `docker-compose build processor && docker-compose up -d processor`

### Environment Variables

Override in `docker-compose.yml` or create `.env` file:

```bash
# .env file example
DATABASE_URL=postgresql://mizzou_user:mizzou_pass@postgres:5432/mizzou
LOG_LEVEL=DEBUG
MAX_ARTICLES=20
ENABLE_WIRE_DETECTION=false  # Disable wire detection locally
```

## Test Development Protocol

When creating new test coverage (unit, integration, or postgres tests), follow this mandatory pre-implementation checklist:

### 1. Database Schema Analysis
- **Grep for model definitions**: Find the SQLAlchemy model class(es) being tested
- **Identify ALL constraints**:
  - NOT NULL columns that require values
  - Foreign key relationships and their target tables
  - Unique constraints that could cause collisions
  - Default values and their behavior
- **Check dependent models**: If creating objects with FKs, understand the parent table requirements

### 2. Production Code Analysis
- **Find real usage**: Locate where the function/method is called in production code
- **Match parameter signatures exactly**:
  - Parameter order (positional vs keyword)
  - Required vs optional parameters
  - Default values and their types
- **Understand data flow**: What values does production code pass? What transformations occur?

### 3. Test Infrastructure Analysis
- **Identify relevant fixtures**:
  - `cloud_sql_session`: PostgreSQL integration tests with automatic rollback
  - Database engines and their configuration
  - Mocking utilities and their behavior
- **Understand cleanup behavior**:
  - Does the fixture handle rollback automatically?
  - Are there unique constraints that require unique test data?
  - Do tests need explicit cleanup code?

### 4. CI/CD Configuration
- **Determine test execution environment**:
  - **Integration tests run in Docker** (uses PostgreSQL 15 container)
  - `postgres-integration` job: Has PostgreSQL 15 service, runs `-m integration`
  - `integration` job: Uses SQLite in-memory, runs default tests (excludes `-m "not integration"`)
  - Unit tests: Fast, no database dependencies
  - **Local integration testing**: Use `./scripts/test-local.sh` or similar Docker-based test runner
- **Apply correct pytest markers**:
  - `@pytest.mark.postgres`: Requires PostgreSQL-specific features (FOR UPDATE SKIP LOCKED, etc.)
  - `@pytest.mark.integration`: Runs in postgres-integration job, excluded from SQLite job
  - `@pytest.mark.parallel`: Custom marker for parallel processing tests
  - `@pytest.mark.slow`: For tests that take >5 seconds
- **Test marker rules**:
  - If test uses PostgreSQL-specific syntax → needs both `@pytest.mark.postgres` AND `@pytest.mark.integration`
  - If test uses cloud_sql_session fixture → needs `@pytest.mark.integration`
  - SQLite tests should NOT be marked with `integration` (they run in default job)

### 5. Test Isolation & Data Management
- **Session management**:
  - Understand which session to use (fixture vs creating new sessions)
  - Know when transactions commit vs rollback
  - Handle connection cleanup in finally blocks
- **Unique data generation**:
  - Use timestamps for unique URLs/identifiers if needed
  - Understand if test data persists across test runs
  - Check for potential race conditions in parallel test execution

### 6. Pre-Implementation Checklist
Before writing ANY test code, create a checklist of ALL potential failure points:
- [ ] Missing foreign key dependencies
- [ ] Wrong parameter order or types
- [ ] Missing required NOT NULL fields
- [ ] Incorrect test markers for CI job routing
- [ ] Unique constraint violations
- [ ] Session/transaction isolation issues
- [ ] PostgreSQL vs SQLite compatibility
- [ ] Connection cleanup and resource leaks
- [ ] Test data cleanup (if not automatic)

### 7. Implementation Approach
**Present analysis FIRST, then implement:**
1. Show your discovery findings (schema, production usage, fixtures, CI config)
2. List all identified failure points
3. Propose test structure addressing each issue
4. **Wait for approval before writing test code**
5. Implement tests with all issues addressed upfront

### Example Workflow

**Good Request:**
```
User: "Write tests for the new parallel entity extraction feature"

Copilot Response:
"Let me analyze the requirements first:

1. Database Schema Analysis:
   - Article model (src/models/__init__.py lines 128-165):
     * candidate_link_id: ForeignKey, NOT NULL, required
     * text, content: Required for entity extraction
   - CandidateLink model: Required parent table
     * url: NOT NULL, UNIQUE
     * source: NOT NULL

2. Production Usage:
   - src/cli/commands/entity_extraction.py line 202:
     * Calls save_article_entities(session, article_id, entities, extractor_version, text_hash, autocommit=False)
     * Note: text_hash is 5th positional parameter

3. Test Infrastructure:
   - cloud_sql_session fixture (tests/backend/conftest.py line 387):
     * Provides PostgreSQL session with automatic rollback cleanup
     * No need for explicit test data deletion
   - Requires @pytest.mark.integration to run in postgres-integration job

4. CI Configuration:
   - postgres-integration job: Has PostgreSQL 15, runs `-m integration`
   - integration job: SQLite only, will fail on FOR UPDATE SKIP LOCKED
   - Need both @pytest.mark.postgres AND @pytest.mark.integration

5. Potential Failure Points:
   [ ] Missing candidate_link_id in Article creation
   [ ] Wrong parameter order for save_article_entities (text_hash missing)
   [ ] Missing @pytest.mark.integration (would run in SQLite job and hang)
   [ ] Unique constraint violation on CandidateLink.url
   [ ] Session isolation issues with multiple sessions

Proposed test structure:
- Create CandidateLink first with unique URL
- Create Article with candidate_link_id reference
- Call save_article_entities with all 6 parameters (including text_hash)
- Use cloud_sql_session fixture (handles cleanup)
- Mark with @pytest.mark.postgres AND @pytest.mark.integration

Shall I proceed with implementation?"
```

**Bad Request (what NOT to do):**
```
User: "Write tests for the new parallel entity extraction feature"

Copilot Response: [immediately writes test code without analysis]
↓
Result: Missing candidate_link_id, test fails in CI
↓
Result: Missing @pytest.mark.integration, test hangs in SQLite job
↓
Result: Multiple CI failures, wasted time
```

## Key Principles

1. **Discovery before implementation**: Understand the full context before writing code
2. **Match production exactly**: Test code should mirror production usage patterns
3. **Consider the CI environment**: Tests must work in the actual CI job configuration
4. **Anticipate failures**: Think through all potential issues before first attempt
5. **Get approval first**: Present analysis and approach, wait for confirmation
