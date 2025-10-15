# Phases 1-5 Implementation Guide

This document describes the implementation of Phases 1-5 from the architecture migration plan outlined in `docs/reference/PROPOSAL.md` and `docs/reference/ROADMAP.md`.

## Overview

Phases 1-5 focus on hardening the foundation of the MizzouNewsCrawler system by:
1. Centralizing configuration
2. Adding comprehensive tests and CI
3. Implementing proper database layering
4. Integrating telemetry and job tracking
5. Providing Docker-based local development environment

## Phase 1: Foundation (PR-001) ✅

**Objective**: Centralize environment configuration and set up development infrastructure.

### Implemented Components

- **`src/config.py`**: Centralized configuration module
  - Reads environment variables with optional `.env` file support
  - Provides `DATABASE_URL`, `LOG_LEVEL`, `TELEMETRY_URL` and other config values
  - Constructs PostgreSQL URLs from component environment variables
  - Supports Kubernetes and Cloud SQL Connector configurations

- **`.env.example`**: Template for local development environment variables
  - Documents all available configuration options
  - Provides sensible defaults for local development

### Usage

```bash
# Copy example to create your local config
cp .env.example .env

# Edit .env with your settings
nano .env
```

```python
# In your code, import config values
from src.config import DATABASE_URL, LOG_LEVEL, TELEMETRY_URL

print(f"Connecting to: {DATABASE_URL}")
```

## Phase 2: Tests & CI (PR-002) ✅

**Objective**: Add comprehensive unit tests and continuous integration.

### Implemented Components

- **`tests/test_crawler.py`**: Tests for crawler functionality
  - `test_is_valid_url()` - URL validation
  - `test_is_likely_article()` - Article detection heuristics

- **`tests/models/test_database_manager.py`**: Comprehensive database tests
  - Upsert operations for candidate links and articles
  - Bulk insert operations
  - Transaction retry logic
  - SQLite lock handling
  - Content hash deduplication

- **`.github/workflows/ci.yml`**: GitHub Actions CI pipeline
  - Linting (ruff, black, isort)
  - Unit tests (fast tests without integration markers)
  - Integration tests with coverage (80% threshold)
  - Security scanning (bandit, safety - scheduled)
  - Stress tests (concurrent operations - scheduled)

### Running Tests

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run unit tests only (fast)
pytest -k "not integration and not e2e and not slow"

# Run all tests with coverage
pytest --cov=src --cov-report=html --cov-report=term

# Run specific test file
pytest tests/test_crawler.py -v
```

## Phase 3: Config & DB Layering (PR-003) ✅

**Objective**: Implement clean database engine creation from environment configuration.

### Implemented Components

- **`src/models/__init__.py`**: Added `create_engine_from_env()` function
  ```python
  def create_engine_from_env():
      """Create SQLAlchemy engine from DATABASE_URL environment variable.
      
      This is the recommended way to create database engines in the application,
      as it respects the centralized configuration in src/config.py.
      
      Returns:
          Engine: Configured SQLAlchemy engine
      """
  ```

- **`tests/test_config_db_layering.py`**: Tests for configuration and DB layering
  - Test `create_engine_from_env()` reads from config
  - Test default SQLite fallback
  - Test PostgreSQL URL construction from components
  - Test DatabaseManager accepts both engine and URL
  - Test connection string parsing

### Usage

```python
from src.models import create_engine_from_env, create_tables, get_session

# Create engine from environment config
engine = create_engine_from_env()

# Create all tables
create_tables(engine)

# Get a session
session = get_session(engine)

# Use the session
# ... your database operations ...

session.close()
```

### Environment Variables

```bash
# Option 1: Single DATABASE_URL
DATABASE_URL=postgresql://user:pass@localhost:5432/mizzou

# Option 2: Component-based (will be constructed automatically)
DATABASE_ENGINE=postgresql+psycopg2
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=mizzou
DATABASE_USER=myuser
DATABASE_PASSWORD=mypass
DATABASE_SSLMODE=require

# Option 3: Default (SQLite for local development)
# No DATABASE_URL or components set -> sqlite:///data/mizzou.db
```

## Phase 4: Telemetry & Jobs (PR-004) ✅

**Objective**: Wire operation tracking into CLI commands and scripts for observability.

### Implemented Components

- **`src/utils/telemetry.py`**: Operation tracking system
  - `OperationTracker` class for tracking operations
  - `OperationType` enum (LOAD_SOURCES, CRAWL_DISCOVERY, etc.)
  - `OperationMetrics` for progress tracking
  - Integration with jobs table for persistence

- **`src/cli/commands/load_sources.py`**: Integrated OperationTracker
  - Tracks load-sources operations from start to completion
  - Updates progress metrics periodically
  - Records operation details in jobs table
  - Handles failures gracefully

- **`scripts/crawl.py`**: Integrated OperationTracker
  - Tracks crawl discovery operations
  - Reports progress for each site processed
  - Links telemetry to job records

- **`tests/test_telemetry_integration.py`**: Tests for telemetry integration
  - Test operation tracking lifecycle
  - Test progress updates
  - Test failure handling
  - Test job record persistence

### Usage

```python
from src.utils.telemetry import OperationTracker, OperationType, OperationMetrics

# Create tracker
tracker = OperationTracker()

# Track an operation
with tracker.track_operation(
    OperationType.LOAD_SOURCES,
    source_file="publinks.csv",
    total_rows=100
) as operation:
    # Your operation code here
    for i in range(100):
        # ... process item ...
        
        # Update progress
        if i % 10 == 0:
            metrics = OperationMetrics(
                total_items=100,
                processed_items=i
            )
            operation.update_progress(metrics)
```

### CLI Integration

```bash
# Load sources with automatic telemetry tracking
python -m src.cli.main load-sources --csv sources/publinks.csv

# Crawl sites with telemetry tracking
python scripts/crawl.py --sources sources/mizzou_sites.json --output-db data/mizzou.db
```

### Environment Variables

```bash
# Optional: Send telemetry to external endpoint
TELEMETRY_URL=https://telemetry.example.com/api/events

# Or configure components
TELEMETRY_HOST=telemetry.example.com
TELEMETRY_PORT=443
TELEMETRY_SCHEME=https
TELEMETRY_USE_TLS=1
```

## Phase 5: Docker + Local Compose (PR-005) ✅

**Objective**: Provide Docker-based local development environment with PostgreSQL.

### Implemented Components

- **`Dockerfile.base`**: Base image with common dependencies
- **`Dockerfile.api`**: FastAPI backend container
- **`Dockerfile.crawler`**: Crawler service container
- **`Dockerfile.processor`**: Background processor container
- **`docker-compose.yml`**: Multi-service local development environment

### Services

1. **postgres**: PostgreSQL 16 database
   - Port 5432 exposed to host
   - Persistent volume for data
   - Health checks enabled

2. **api**: FastAPI backend
   - Port 8000 exposed to host
   - Hot reload enabled for development
   - Connected to postgres

3. **crawler**: Discovery service
   - Runs URL discovery operations
   - Optional profile (start with `--profile crawler`)

4. **processor**: Article extraction service
   - Runs article extraction
   - Optional profile (start with `--profile processor`)

5. **adminer**: Database management UI
   - Port 8080 exposed to host
   - Optional profile (start with `--profile tools`)

### Usage

```bash
# Start core services (postgres + api)
docker-compose up

# Start with crawler service
docker-compose --profile crawler up

# Start all services including database tools
docker-compose --profile crawler --profile processor --profile tools up

# Build base image first (recommended)
docker-compose --profile base build base

# Build all images
docker-compose build

# Start services in background
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop services
docker-compose down

# Stop and remove volumes (WARNING: deletes database)
docker-compose down -v
```

### Connecting to Services

```bash
# API endpoint
curl http://localhost:8000/health

# Adminer (database UI)
# Open browser to http://localhost:8080
# System: PostgreSQL
# Server: postgres
# Username: mizzou_user
# Password: mizzou_pass
# Database: mizzou

# PostgreSQL (direct connection)
psql -h localhost -U mizzou_user -d mizzou
# Password: mizzou_pass
```

### Environment Customization

Create a `.env` file in the project root:

```bash
# Database credentials
POSTGRES_DB=mizzou
POSTGRES_USER=mizzou_user
POSTGRES_PASSWORD=mizzou_pass

# Application configuration
LOG_LEVEL=DEBUG
SOURCE_LIMIT=50
MAX_ARTICLES=100
```

Docker Compose will automatically load these variables.

## Testing the Full Stack

### Integration Test

```bash
# 1. Start services
docker-compose up -d

# 2. Wait for postgres to be healthy
docker-compose ps

# 3. Load sources
docker-compose exec api python -m src.cli.main load-sources \
  --csv /app/sources/publinks.csv

# 4. Run discovery
docker-compose exec api python scripts/crawl.py \
  --sources /app/sources/mizzou_sites.json \
  --output-db /app/data/mizzou.db

# 5. Check results
docker-compose exec postgres psql -U mizzou_user -d mizzou \
  -c "SELECT COUNT(*) FROM candidate_links;"

# 6. View telemetry
docker-compose exec postgres psql -U mizzou_user -d mizzou \
  -c "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 5;"
```

## Quality Gates

Before merging PRs, run:

```bash
# 1. Linting
python -m ruff check .
python -m black --check src/ tests/
python -m isort --check-only --profile black src/ tests/

# 2. Unit tests with coverage
pytest --cov=src --cov-report=term --cov-fail-under=80

# 3. Integration smoke test
docker-compose up -d
docker-compose exec api pytest tests/integration/
docker-compose down
```

## Architecture Benefits

The implementation of Phases 1-5 provides:

1. **Reproducibility**: Environment variables and Docker ensure consistent behavior
2. **Testability**: Comprehensive test suite with 80%+ coverage
3. **Observability**: Operation tracking and job records for debugging
4. **Maintainability**: Clean separation of concerns and configuration
5. **Scalability**: Ready for production deployment with PostgreSQL
6. **Developer Experience**: Fast local setup with Docker Compose

## Next Steps

With Phases 1-5 complete, the foundation is ready for:

- **Phase 6**: Crawler refactor (split into discovery/fetch/parse/storage layers)
- **Phase 7**: ML pipeline scaffolding (classifier and NER interfaces)
- **Phase 8+**: Advanced features and optimizations

See `docs/reference/PROPOSAL.md` for the complete roadmap.

## Troubleshooting

### Docker Issues

```bash
# Rebuild images after code changes
docker-compose build --no-cache

# Reset database
docker-compose down -v
docker-compose up -d postgres
docker-compose exec postgres psql -U mizzou_user -d mizzou -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# View container logs
docker-compose logs -f [service-name]
```

### Database Connection Issues

```bash
# Test connection
docker-compose exec postgres pg_isready -U mizzou_user

# Check environment variables
docker-compose exec api env | grep DATABASE

# Verify tables exist
docker-compose exec postgres psql -U mizzou_user -d mizzou -c "\dt"
```

### Test Failures

```bash
# Run specific test with verbose output
pytest tests/test_crawler.py::test_is_valid_url -vv

# Run tests without coverage (faster)
pytest --no-cov

# Run with debug output
pytest --log-cli-level=DEBUG
```

## References

- [PROPOSAL.md](../reference/PROPOSAL.md) - Full architecture proposal
- [ROADMAP.md](../reference/ROADMAP.md) - Implementation roadmap
- [GCP_KUBERNETES_ROADMAP.md](../GCP_KUBERNETES_ROADMAP.md) - Production deployment plan
