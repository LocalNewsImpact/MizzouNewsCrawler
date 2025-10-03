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

### Build All Images

```bash
# Build all images defined in docker-compose.yml
docker compose build

# Build with no cache (force rebuild)
docker compose build --no-cache
```

### Build Individual Images

```bash
# API only
docker build -t mizzou-api:latest -f Dockerfile.api .

# Crawler only
docker build -t mizzou-crawler:latest -f Dockerfile.crawler .

# Processor only
docker build -t mizzou-processor:latest -f Dockerfile.processor .
```

### Check Image Sizes

```bash
docker images | grep mizzou
```

**Expected sizes:**
- `mizzou-api`: ~300-400 MB
- `mizzou-crawler`: ~600-800 MB (includes Playwright dependencies)
- `mizzou-processor`: ~400-500 MB (includes ML models)

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

### Issue: "Models not found"

**Symptoms:**
```
FileNotFoundError: [Errno 2] No such file or directory: '/app/models/productionmodel.pt'
```

**Solutions:**
1. Download models:
   ```bash
   python -m spacy download en_core_web_sm
   ```

2. Mount models directory:
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

1. **Use multi-stage builds** (already implemented)
2. **Minimize layers** (combine RUN commands)
3. **Order commands** (least to most frequently changing)
4. **Use .dockerignore** (exclude unnecessary files)
5. **Don't install dev dependencies** in production
6. **Use specific base image tags** (python:3.11-slim, not python:latest)

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
