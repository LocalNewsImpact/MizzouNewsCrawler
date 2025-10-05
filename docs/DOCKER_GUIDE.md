# Docker Guide for MizzouNewsCrawler

This guide covers building and running the MizzouNewsCrawler application using Docker and Docker Compose.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Building Images](#building-images)
- [Running with Docker Compose](#running-with-docker-compose)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Production Deployment](#production-deployment)

---

## Prerequisites

### Required Software

- **Docker**: 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose**: 2.0+ (included with Docker Desktop)
- **Git**: For cloning the repository

### Verify Installation

```bash
docker --version
# Docker version 24.0.0 or higher

docker compose version
# Docker Compose version v2.20.0 or higher
```

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/LocalNewsImpact/MizzouNewsCrawler.git
cd MizzouNewsCrawler-Scripts
```

### 2. Start the Stack

```bash
# Start API and database only
docker compose up -d

# View logs
docker compose logs -f api

# Access API at http://localhost:8000
# Access database UI at http://localhost:8080 (adminer)
```

### 3. Run the Crawler

```bash
# Run crawler (one-time)
docker compose --profile crawler up crawler

# Or run interactively
docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 5
```

### 4. Run the Processor

```bash
# Run processor (one-time)
docker compose --profile processor up processor

# Or run interactively
docker compose run --rm processor python -m src.cli.main extract --limit 10
```

### 5. Stop Everything

```bash
docker compose down

# Remove volumes (deletes database data)
docker compose down -v
```

---

## Building Images

### Shared Base Image Strategy

**This project uses a shared base image** to optimize build times and reduce redundancy:

- **Base Image** (`mizzou-base:latest`): ~1.2-1.5 GB
  - Contains common dependencies used by all services
  - System packages: gcc, g++, libpq-dev
  - Python packages: pandas, sqlalchemy, spacy, pytest, etc.
  - Spacy model: en_core_web_sm
  
- **Service Images**: Build from base + service-specific packages
  - API: base + FastAPI (~300 MB additional)
  - Processor: base + ML packages (~400 MB additional)
  - Crawler: base + scraping tools (~500 MB additional)

**Benefits:**
- Build time: 15 minutes → 2-3 minutes per service (83% reduction)
- Eliminates redundant dependency installation
- Better Docker layer caching

### Build Base Image First

Build the shared base image once:

```bash
# Using the build script (recommended)
./scripts/build-base.sh

# Or manually
docker build -t mizzou-base:latest -f Dockerfile.base .

# Or with docker-compose
docker compose --profile base build base
```

**Time:** First build takes 5-10 minutes, subsequent builds ~3-5 minutes with cache.

### Build All Images

```bash
# Build all images defined in docker-compose.yml
docker compose build

# Build with no cache (force rebuild)
docker compose build --no-cache
```

### Build Individual Images

```bash
# Ensure base image exists first
docker build -t mizzou-base:latest -f Dockerfile.base .

# Then build services
# API only
docker build -t mizzou-api:latest -f Dockerfile.api .

# Crawler only
docker build -t mizzou-crawler:latest -f Dockerfile.crawler .

# Processor only
docker build -t mizzou-processor:latest -f Dockerfile.processor .
```

**Time:** Each service builds in 2-3 minutes (80%+ faster than before).

### Check Image Sizes

```bash
docker images | grep mizzou
```

**Expected sizes:**
- `mizzou-base`: ~1.2-1.5 GB (shared base)
- `mizzou-api`: ~1.5-1.7 GB (base + API packages)
- `mizzou-crawler`: ~2.0-2.3 GB (base + scraping + browsers)
- `mizzou-processor`: ~1.8-2.0 GB (base + ML models)

---

## Running with Docker Compose

### Service Profiles

Docker Compose uses **profiles** to control which services start:

- **Default** (no profile): API + Postgres + Adminer
- **crawler**: Crawler service
- **processor**: Background processor
- **tools**: Additional tools (Adminer)

### Common Commands

```bash
# Start API only
docker compose up -d

# Start with crawler
docker compose --profile crawler up -d

# Start with processor
docker compose --profile processor up -d

# Start everything
docker compose --profile crawler --profile processor --profile tools up -d

# View logs
docker compose logs -f api
docker compose logs -f crawler
docker compose logs -f processor

# Restart a service
docker compose restart api

# Execute command in running container
docker compose exec api bash
docker compose exec postgres psql -U mizzou_user -d mizzou

# Run one-off command
docker compose run --rm crawler python -m src.cli.main --help
```

### Development Workflow

```bash
# 1. Start API and database
docker compose up -d

# 2. Make code changes (volumes mounted for hot reload)
# API will auto-reload when you edit backend/ or src/ files

# 3. Test your changes
curl http://localhost:8000/health

# 4. Run crawler to test discovery
docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 1

# 5. Check database
docker compose exec postgres psql -U mizzou_user -d mizzou -c "SELECT COUNT(*) FROM candidate_links;"

# 6. Stop when done
docker compose down
```

---

## Environment Variables

### Database Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://mizzou_user:mizzou_pass@postgres:5432/mizzou` | PostgreSQL connection string |

### Application Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `SOURCE_LIMIT` | `50` | Maximum sources to crawl per run |
| `MAX_ARTICLES` | `40` | Maximum articles per source |
| `DAYS_BACK` | `7` | How far back to look for articles |
| `MODEL_PATH` | `/app/models` | Path to ML models |

### Cloud Configuration (Production)

| Variable | Description |
|----------|-------------|
| `GCS_BUCKET` | Google Cloud Storage bucket for raw assets |
| `BIGQUERY_DATASET` | BigQuery dataset name |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |

### Override Environment Variables

Create a `.env` file:

```bash
# .env
DATABASE_URL=postgresql://custom_user:custom_pass@postgres:5432/custom_db
LOG_LEVEL=DEBUG
SOURCE_LIMIT=5
```

Then run:

```bash
docker compose --env-file .env up -d
```

---

## Troubleshooting

### Issue: "Cannot connect to database"

**Symptoms:**
```
psycopg2.OperationalError: could not connect to server
```

**Solutions:**
1. Ensure Postgres is healthy:
   ```bash
   docker compose ps
   # postgres should show "healthy"
   ```

2. Check logs:
   ```bash
   docker compose logs postgres
   ```

3. Restart Postgres:
   ```bash
   docker compose restart postgres
   ```

4. Reset database:
   ```bash
   docker compose down -v
   docker compose up -d
   ```

### Issue: "Image build fails"

**Symptoms:**
```
ERROR: failed to solve: process "/bin/sh -c pip install ..." did not complete successfully
```

**Solutions:**
1. Clear Docker cache:
   ```bash
   docker compose build --no-cache
   ```

2. Check disk space:
   ```bash
   docker system df
   docker system prune  # Clean up unused resources
   ```

3. Increase Docker memory (Docker Desktop):
   - Go to Preferences → Resources
   - Increase memory to 4GB+

### Issue: "Port already in use"

**Symptoms:**
```
Error: bind: address already in use
```

**Solutions:**
1. Find and stop conflicting process:
   ```bash
   # On macOS/Linux
   lsof -i :8000
   kill -9 <PID>
   
   # On Windows
   netstat -ano | findstr :8000
   taskkill /PID <PID> /F
   ```

2. Change port in `docker-compose.yml`:
   ```yaml
   ports:
     - "8001:8000"  # Use 8001 instead
   ```

### Issue: "Base image not found"

**Symptoms:**
```
Error: mizzou-base:latest not found
failed to solve with frontend dockerfile.v0
```

**Solutions:**
1. Build base image first:
   ```bash
   ./scripts/build-base.sh
   # Or
   docker build -t mizzou-base:latest -f Dockerfile.base .
   ```

2. For docker-compose:
   ```bash
   docker compose --profile base build base
   ```

3. Pull from Artifact Registry (production):
   ```bash
   gcloud auth configure-docker us-central1-docker.pkg.dev
   docker pull us-central1-docker.pkg.dev/PROJECT_ID/mizzou-crawler/base:latest
   docker tag us-central1-docker.pkg.dev/PROJECT_ID/mizzou-crawler/base:latest mizzou-base:latest
   ```

### Issue: "Models not found"

**Symptoms:**
```
FileNotFoundError: [Errno 2] No such file or directory: '/app/models/productionmodel.pt'
```

**Solutions:**
1. Spacy model is in base image (en_core_web_sm)
2. For custom models, mount directory:
   ```bash
   docker compose run -v ./models:/app/models processor <command>
   ```

3. In production, models are downloaded from GCS (see Phase 5)

### Issue: "Container exits immediately"

**Symptoms:**
```
mizzou-crawler exited with code 1
```

**Solutions:**
1. Check logs:
   ```bash
   docker compose logs crawler
   ```

2. Run interactively:
   ```bash
   docker compose run --rm crawler bash
   # Then debug inside container
   ```

3. Test command locally:
   ```bash
   python -m src.cli.main discover-urls --source-limit 1
   ```

---

## Production Deployment

### Differences from Local Development

| Aspect | Local (Docker Compose) | Production (Kubernetes) |
|--------|------------------------|-------------------------|
| Database | Postgres container | Cloud SQL (managed) |
| Storage | Local volumes | Cloud Storage (GCS) |
| Models | Local files | Downloaded from GCS |
| Secrets | Environment variables | Google Secret Manager |
| Scaling | Manual | Auto-scaling (HPA) |
| Monitoring | Logs only | Cloud Monitoring + Alerts |

### Building for Production

```bash
# Build and push to Artifact Registry (GCP)
docker build -t us-central1-docker.pkg.dev/PROJECT_ID/images/api:latest -f Dockerfile.api .
docker push us-central1-docker.pkg.dev/PROJECT_ID/images/api:latest

# Or use Cloud Build (recommended)
gcloud builds submit --tag us-central1-docker.pkg.dev/PROJECT_ID/images/api:latest -f Dockerfile.api .
```

### Image Optimization Tips

1. ✅ **Use shared base image** (reduces build time by 80%+)
2. ✅ **Use multi-stage builds** (already implemented)
3. ✅ **Minimize layers** (combine RUN commands)
4. ✅ **Order commands** (least to most frequently changing)
5. ✅ **Use .dockerignore** (exclude unnecessary files)
6. ✅ **Don't install dev dependencies** in production
7. ✅ **Use specific base image tags** (python:3.11-slim, not python:latest)

### When to Rebuild Base Image

The base image should be rebuilt when:
- Base dependencies are added/removed in `requirements-base.txt`
- System dependencies change
- Spacy model version updates
- Security patches needed
- Quarterly maintenance (every 3 months)

**DO NOT rebuild for:**
- Service-specific dependency changes
- Application code changes
- Configuration changes

See [BASE_IMAGE_MAINTENANCE.md](./BASE_IMAGE_MAINTENANCE.md) for detailed rebuild procedures.

### Security Best Practices

1. ✅ **Non-root user** (appuser, UID 1000)
2. ✅ **No secrets in image** (use environment variables)
3. ✅ **Health checks** defined
4. ✅ **Minimal base image** (slim variant)
5. ✅ **Specific versions** (python:3.11-slim, not latest)

---

## Next Steps

- **Phase 2**: Set up GCP infrastructure (GKE, Cloud SQL, BigQuery)
- **Phase 3**: Create Helm charts for Kubernetes deployment
- **Phase 4**: Set up CI/CD pipeline with GitHub Actions

See the [GCP/Kubernetes Deployment Roadmap](./GCP_KUBERNETES_ROADMAP.md) for the full plan.

---

## Support

For issues or questions:
1. Check the [troubleshooting section](#troubleshooting)
2. Review logs: `docker compose logs <service>`
3. Open an issue on GitHub
4. Consult the [main README](../README.md)
