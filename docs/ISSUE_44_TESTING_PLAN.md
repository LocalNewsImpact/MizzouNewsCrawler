# Testing Plan: API Backend Migration (Issue #44)

**Issue**: [#44 Complete API Backend Migration: Replace CSV Reads with Database Queries for Dashboard Endpoints](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/44)

**Date**: October 5, 2025  
**Status**: Planning Phase

---

## Overview

This document outlines the comprehensive testing strategy for migrating dashboard API endpoints from CSV files to Cloud SQL database queries. The testing approach covers unit tests, integration tests against Cloud SQL, load tests, and CI/CD deployment validation.

## Testing Architecture

### 1. Test Pyramid

```
                    ╱╲
                   ╱  ╲
                  ╱ E2E ╲          <- 5% (Smoke tests in production)
                 ╱────────╲
                ╱          ╲
               ╱Integration╲       <- 20% (Cloud SQL + API)
              ╱──────────────╲
             ╱                ╲
            ╱   Unit Tests     ╲   <- 75% (Fast, isolated)
           ╱────────────────────╲
```

### 2. Test Environments

| Environment | Database | Purpose | Access Method |
|-------------|----------|---------|---------------|
| **Local Dev** | SQLite in-memory | Unit tests | `pytest` |
| **Local Integration** | PostgreSQL (Docker) | Integration tests | `TEST_DATABASE_URL` |
| **Cloud SQL Dev** | Cloud SQL (test instance) | Cloud integration | Service account |
| **Staging** | Cloud SQL (staging) | Pre-production validation | GKE staging namespace |
| **Production** | Cloud SQL (production) | Smoke tests only | GKE production namespace |

---

## Phase 1: Unit Tests (Local SQLite)

### Test Coverage Goals
- **Target**: ≥80% line coverage for modified endpoints
- **Files**: `backend/app/main.py` (endpoints), `src/models/api_backend.py` (models)

### Test Cases

#### 1.1 `/api/ui_overview` Endpoint
```python
# tests/backend/test_ui_overview_endpoint.py

def test_ui_overview_empty_database(db_session):
    """Test ui_overview returns zeros when database is empty."""
    response = client.get("/api/ui_overview")
    assert response.status_code == 200
    data = response.json()
    assert data["total_articles"] == 0
    assert data["wire_count"] == 0
    assert data["candidate_issues"] == 0

def test_ui_overview_with_articles(db_session, sample_articles):
    """Test ui_overview returns correct counts from database."""
    # Insert 100 articles, 15 wire-detected, 8 candidates
    response = client.get("/api/ui_overview")
    assert response.status_code == 200
    data = response.json()
    assert data["total_articles"] == 100
    assert data["wire_count"] == 15
    assert data["candidate_issues"] == 8

def test_ui_overview_database_error_handling(db_session, monkeypatch):
    """Test ui_overview handles database connection failures gracefully."""
    def mock_error(*args, **kwargs):
        raise Exception("Database connection lost")
    
    monkeypatch.setattr("sqlalchemy.orm.Session.query", mock_error)
    response = client.get("/api/ui_overview")
    assert response.status_code == 500
    assert "database" in response.json()["detail"].lower()
```

#### 1.2 `/api/articles` Endpoint
```python
# tests/backend/test_articles_endpoint.py

def test_articles_pagination(db_session, sample_articles):
    """Test articles endpoint pagination works correctly."""
    # Insert 50 articles
    response = client.get("/api/articles?limit=10&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 50
    assert len(data["results"]) == 10
    
    # Test offset
    response = client.get("/api/articles?limit=10&offset=10")
    assert len(response.json()["results"]) == 10

def test_articles_reviewer_filter(db_session, sample_articles, sample_reviews):
    """Test articles endpoint filters by reviewer correctly."""
    # Insert articles and reviews
    response = client.get("/api/articles?reviewer=test_user")
    assert response.status_code == 200
    data = response.json()
    # Verify only reviewed articles returned
    assert all(r["reviewed_by"] == "test_user" for r in data["results"])

def test_articles_empty_database(db_session):
    """Test articles endpoint with no data."""
    response = client.get("/api/articles")
    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["results"] == []
```

#### 1.3 `/api/options/*` Endpoints
```python
# tests/backend/test_options_endpoints.py

def test_options_counties_distinct(db_session, sample_articles):
    """Test counties options returns distinct non-null values."""
    response = client.get("/api/options/counties")
    assert response.status_code == 200
    counties = response.json()
    assert "Boone" in counties
    assert "Cole" in counties
    assert None not in counties  # Nulls excluded

def test_options_sources_distinct(db_session, sample_sources):
    """Test sources options returns distinct source names."""
    response = client.get("/api/options/sources")
    assert response.status_code == 200
    sources = response.json()
    assert len(sources) == len(sample_sources)
    assert all(isinstance(s, str) for s in sources)

def test_options_reviewers_distinct(db_session, sample_reviews):
    """Test reviewers options returns distinct reviewer names."""
    response = client.get("/api/options/reviewers")
    assert response.status_code == 200
    reviewers = response.json()
    assert "user1" in reviewers
    assert "user2" in reviewers
```

### Test Fixtures
```python
# tests/backend/conftest.py

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models.database import Base
from src.models.api_backend import Article, Review, Source

@pytest.fixture
def db_engine():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

@pytest.fixture
def db_session(db_engine):
    """Create database session for tests."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()

@pytest.fixture
def sample_articles(db_session):
    """Create sample articles for testing."""
    articles = []
    for i in range(50):
        article = Article(
            uid=f"article-{i}",
            title=f"Test Article {i}",
            url=f"https://example.com/article-{i}",
            source_id=1,
            county="Boone" if i % 2 == 0 else "Cole",
            publish_date=datetime.now() - timedelta(days=i),
            wire_detected=(i % 7 == 0),  # ~14% wire
        )
        articles.append(article)
        db_session.add(article)
    db_session.commit()
    return articles

@pytest.fixture
def sample_reviews(db_session, sample_articles):
    """Create sample reviews for testing."""
    reviews = []
    for i in range(20):
        review = Review(
            id=f"review-{i}",
            article_uid=sample_articles[i].uid,
            reviewer="user1" if i % 2 == 0 else "user2",
            rating=4,
            created_at=datetime.now(),
        )
        reviews.append(review)
        db_session.add(review)
    db_session.commit()
    return reviews
```

### Running Unit Tests
```bash
# Run all unit tests
pytest tests/backend/ -v

# Run with coverage
pytest tests/backend/ --cov=backend/app --cov-report=term-missing

# Run only endpoint tests
pytest tests/backend/test_*_endpoint.py -v
```

---

## Phase 2: Integration Tests (Cloud SQL)

### Prerequisites
1. **Test Database Instance**: Cloud SQL PostgreSQL for testing
2. **Service Account**: JSON key with Cloud SQL Client permissions
3. **Environment Variables**:
   ```bash
   export TEST_DATABASE_URL="postgresql+psycopg2://user:pass@localhost/testdb"
   export USE_CLOUD_SQL_CONNECTOR=true
   export CLOUD_SQL_INSTANCE="project:region:instance"
   export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account.json"
   ```

### Test Cases

#### 2.1 Cloud SQL Connection Tests
```python
# tests/integration/test_cloud_sql_connection.py

import pytest
from src.models.database import DatabaseManager
from src import config

@pytest.mark.integration
def test_cloud_sql_connector_connection():
    """Test Cloud SQL Connector establishes connection successfully."""
    db_manager = DatabaseManager(config.DATABASE_URL)
    with db_manager.get_session() as session:
        result = session.execute("SELECT 1").scalar()
        assert result == 1

@pytest.mark.integration
def test_cloud_sql_query_performance():
    """Test database queries meet performance targets."""
    import time
    db_manager = DatabaseManager(config.DATABASE_URL)
    
    start = time.time()
    with db_manager.get_session() as session:
        count = session.query(Article).count()
    elapsed = time.time() - start
    
    # Should complete in <500ms for dashboard responsiveness
    assert elapsed < 0.5, f"Query took {elapsed:.2f}s (target: <0.5s)"
```

#### 2.2 API Integration Tests
```python
# tests/integration/test_api_cloud_sql.py

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.mark.integration
def test_ui_overview_cloud_sql():
    """Test ui_overview endpoint against real Cloud SQL."""
    client = TestClient(app)
    response = client.get("/api/ui_overview")
    assert response.status_code == 200
    
    data = response.json()
    # With real data, should have non-zero counts
    assert data["total_articles"] > 0
    assert "wire_count" in data
    assert "candidate_issues" in data

@pytest.mark.integration
def test_articles_endpoint_cloud_sql():
    """Test articles endpoint returns real data from Cloud SQL."""
    client = TestClient(app)
    response = client.get("/api/articles?limit=10")
    assert response.status_code == 200
    
    data = response.json()
    assert data["count"] > 0
    assert len(data["results"]) > 0
    # Verify structure
    first_article = data["results"][0]
    assert "uid" in first_article
    assert "title" in first_article
    assert "url" in first_article

@pytest.mark.integration
def test_api_pagination_cloud_sql():
    """Test pagination works correctly with large dataset."""
    client = TestClient(app)
    
    # Get first page
    page1 = client.get("/api/articles?limit=20&offset=0").json()
    # Get second page
    page2 = client.get("/api/articles?limit=20&offset=20").json()
    
    # Verify different results
    page1_uids = {r["uid"] for r in page1["results"]}
    page2_uids = {r["uid"] for r in page2["results"]}
    assert page1_uids.isdisjoint(page2_uids), "Pages should not overlap"
```

### Running Integration Tests

#### Option A: Local PostgreSQL (Docker)
```bash
# Start PostgreSQL container
docker run -d --name postgres-test \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=testdb \
  -p 5432:5432 \
  postgres:15

# Set environment
export TEST_DATABASE_URL="postgresql+psycopg2://postgres:testpass@localhost/testdb"
export USE_CLOUD_SQL_CONNECTOR=false

# Run integration tests
pytest tests/integration/ -v -m integration

# Cleanup
docker stop postgres-test && docker rm postgres-test
```

#### Option B: Cloud SQL (Test Instance)
```bash
# Set Cloud SQL environment
export USE_CLOUD_SQL_CONNECTOR=true
export CLOUD_SQL_INSTANCE="mizzou-news-crawler:us-central1:mizzou-db-test"
export DATABASE_NAME="test_db"
export DATABASE_USER="test_user"
export DATABASE_PASSWORD="test_password"
export GOOGLE_APPLICATION_CREDENTIALS="~/.gcp/service-account.json"

# Run integration tests
pytest tests/integration/ -v -m integration

# Note: Requires Cloud SQL Admin API enabled and proper IAM permissions
```

---

## Phase 3: Load & Performance Tests

### Test Cases

#### 3.1 Concurrent Request Load Test
```python
# tests/load/test_api_load.py

import pytest
import concurrent.futures
import time
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.mark.load
def test_concurrent_ui_overview_requests():
    """Test ui_overview handles 100 concurrent requests."""
    client = TestClient(app)
    
    def make_request():
        start = time.time()
        response = client.get("/api/ui_overview")
        elapsed = time.time() - start
        return response.status_code, elapsed
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(make_request) for _ in range(100)]
        results = [f.result() for f in futures]
    
    # All requests should succeed
    assert all(status == 200 for status, _ in results)
    
    # 95th percentile should be <1s
    times = sorted([elapsed for _, elapsed in results])
    p95 = times[int(len(times) * 0.95)]
    assert p95 < 1.0, f"95th percentile: {p95:.2f}s"

@pytest.mark.load
def test_pagination_performance():
    """Test pagination through large result sets."""
    client = TestClient(app)
    
    total_fetched = 0
    offset = 0
    limit = 100
    
    start = time.time()
    while True:
        response = client.get(f"/api/articles?limit={limit}&offset={offset}")
        data = response.json()
        total_fetched += len(data["results"])
        
        if len(data["results"]) < limit:
            break
        offset += limit
    
    elapsed = time.time() - start
    
    # Should fetch 1000+ articles in <5s
    assert total_fetched > 1000
    assert elapsed < 5.0, f"Fetched {total_fetched} in {elapsed:.2f}s"
```

#### 3.2 Database Connection Pool Test
```python
# tests/load/test_connection_pool.py

@pytest.mark.load
def test_connection_pool_exhaustion():
    """Test app handles connection pool exhaustion gracefully."""
    client = TestClient(app)
    
    # Make more concurrent requests than pool size
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(client.get, "/api/ui_overview") 
                   for _ in range(50)]
        results = [f.result() for f in futures]
    
    # All should succeed or return 503 (not crash)
    assert all(r.status_code in [200, 503] for r in results)
    success_rate = sum(1 for r in results if r.status_code == 200) / len(results)
    # At least 80% should succeed
    assert success_rate >= 0.8
```

### Running Load Tests
```bash
# Run load tests (requires real database)
pytest tests/load/ -v -m load

# Run with stress test (more concurrent users)
pytest tests/load/ -v -m load --maxfail=1
```

---

## Phase 4: CI/CD Integration Tests

### 4.1 Cloud Build Test Stage

**File**: `cloudbuild-api-test.yaml`
```yaml
steps:
  # Step 1: Build API image
  - name: 'gcr.io/cloud-builders/docker'
    id: 'build-api'
    args:
      - 'build'
      - '-t'
      - 'us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/api:${SHORT_SHA}'
      - '-f'
      - 'Dockerfile.api'
      - '.'

  # Step 2: Run unit tests
  - name: 'us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/api:${SHORT_SHA}'
    id: 'unit-tests'
    entrypoint: 'pytest'
    args:
      - 'tests/backend/'
      - '-v'
      - '--cov=backend/app'
      - '--cov-fail-under=80'
    env:
      - 'USE_CLOUD_SQL_CONNECTOR=false'
      - 'DATABASE_URL=sqlite:///test.db'

  # Step 3: Setup Cloud SQL Proxy for integration tests
  - name: 'gcr.io/cloudsql-docker/gce-proxy:latest'
    id: 'cloud-sql-proxy'
    args:
      - '/cloud_sql_proxy'
      - '-instances=${_CLOUD_SQL_INSTANCE}=tcp:5432'
    waitFor: ['-']  # Start immediately

  # Step 4: Run integration tests
  - name: 'us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/api:${SHORT_SHA}'
    id: 'integration-tests'
    entrypoint: 'pytest'
    args:
      - 'tests/integration/'
      - '-v'
      - '-m'
      - 'integration'
    env:
      - 'USE_CLOUD_SQL_CONNECTOR=true'
      - 'CLOUD_SQL_INSTANCE=${_CLOUD_SQL_INSTANCE}'
      - 'DATABASE_NAME=${_TEST_DATABASE_NAME}'
      - 'DATABASE_USER=${_TEST_DATABASE_USER}'
      - 'DATABASE_PASSWORD=${_TEST_DATABASE_PASSWORD}'
    secretEnv:
      - 'DATABASE_PASSWORD'
    waitFor: ['unit-tests', 'cloud-sql-proxy']

  # Step 5: Push image only if tests pass
  - name: 'gcr.io/cloud-builders/docker'
    id: 'push-api'
    args:
      - 'push'
      - 'us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/api:${SHORT_SHA}'
    waitFor: ['integration-tests']

substitutions:
  _CLOUD_SQL_INSTANCE: 'mizzou-news-crawler:us-central1:mizzou-db-test'
  _TEST_DATABASE_NAME: 'test_db'
  _TEST_DATABASE_USER: 'test_user'

availableSecrets:
  secretManager:
    - versionName: projects/${PROJECT_ID}/secrets/test-db-password/versions/latest
      env: 'DATABASE_PASSWORD'

timeout: '1200s'  # 20 minutes
```

### 4.2 GKE Smoke Tests (Post-Deployment)

**File**: `tests/smoke/test_production_api.py`
```python
# tests/smoke/test_production_api.py

import pytest
import requests
import os

# Get production URL from environment
PRODUCTION_URL = os.getenv("PRODUCTION_API_URL", "http://compute.localnewsimpact.org")

@pytest.mark.smoke
def test_production_ui_overview():
    """Smoke test: ui_overview returns valid data in production."""
    response = requests.get(f"{PRODUCTION_URL}/api/ui_overview", timeout=5)
    assert response.status_code == 200
    
    data = response.json()
    # Should have non-zero articles in production
    assert data["total_articles"] > 0
    assert isinstance(data["wire_count"], int)
    assert isinstance(data["candidate_issues"], int)

@pytest.mark.smoke
def test_production_articles_pagination():
    """Smoke test: articles endpoint works in production."""
    response = requests.get(
        f"{PRODUCTION_URL}/api/articles?limit=5", 
        timeout=5
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["count"] > 0
    assert len(data["results"]) <= 5

@pytest.mark.smoke
def test_production_api_response_time():
    """Smoke test: API response time is acceptable."""
    import time
    
    start = time.time()
    response = requests.get(f"{PRODUCTION_URL}/api/ui_overview", timeout=5)
    elapsed = time.time() - start
    
    assert response.status_code == 200
    # Should respond in <500ms
    assert elapsed < 0.5, f"Response took {elapsed:.2f}s"
```

### 4.3 Cloud Deploy Pipeline with Testing

**File**: `clouddeploy.yaml` (updated)
```yaml
apiVersion: deploy.cloud.google.com/v1
kind: DeliveryPipeline
metadata:
  name: mizzou-news-crawler
description: Mizzou News Crawler deployment pipeline with testing
serialPipeline:
  stages:
    # Stage 1: Deploy to staging
    - targetId: staging
      profiles: []
      strategy:
        standard:
          verify: true  # Enable verification

    # Stage 2: Run smoke tests
    - targetId: staging-verification
      profiles: []

    # Stage 3: Deploy to production (requires approval)
    - targetId: production
      profiles: []
      strategy:
        standard:
          verify: true
      deployParameters:
        - name: "requireApproval"
          value: "true"

---
apiVersion: deploy.cloud.google.com/v1
kind: Target
metadata:
  name: staging-verification
description: Run smoke tests in staging
run:
  location: projects/mizzou-news-crawler/locations/us-central1
executionConfigs:
  - usages: [VERIFY]
    artifactStorage: gs://mizzou-deploy-artifacts
```

### 4.4 Deployment Verification Script

**File**: `scripts/verify-deployment.sh`
```bash
#!/bin/bash
# Verify API deployment after Cloud Deploy

set -e

NAMESPACE=${1:-production}
SERVICE=${2:-mizzou-api}
TIMEOUT=300  # 5 minutes

echo "🔍 Verifying deployment in namespace: $NAMESPACE"

# Wait for rollout to complete
echo "⏳ Waiting for rollout..."
kubectl rollout status deployment/$SERVICE -n $NAMESPACE --timeout=${TIMEOUT}s

# Get pod name
POD=$(kubectl get pods -n $NAMESPACE -l app=$SERVICE -o jsonpath='{.items[0].metadata.name}')
echo "✅ Pod: $POD"

# Test 1: Check pod health
echo "🏥 Checking pod health..."
kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.status.phase}' | grep -q "Running"
echo "✅ Pod is running"

# Test 2: Test ui_overview endpoint
echo "📊 Testing /api/ui_overview endpoint..."
RESPONSE=$(kubectl exec -n $NAMESPACE $POD -- curl -s http://localhost:8000/api/ui_overview)
echo "$RESPONSE" | jq -e '.total_articles > 0' > /dev/null
echo "✅ ui_overview returns data"

# Test 3: Test articles endpoint
echo "📰 Testing /api/articles endpoint..."
RESPONSE=$(kubectl exec -n $NAMESPACE $POD -- curl -s 'http://localhost:8000/api/articles?limit=5')
echo "$RESPONSE" | jq -e '.count > 0' > /dev/null
echo "✅ articles endpoint returns data"

# Test 4: Check database connectivity
echo "🗄️  Testing database connectivity..."
RESPONSE=$(kubectl exec -n $NAMESPACE $POD -- curl -s http://localhost:8000/api/snapshots)
echo "$RESPONSE" | jq -e 'type == "array"' > /dev/null
echo "✅ Database connectivity confirmed"

echo ""
echo "🎉 All verification tests passed!"
echo "✅ Deployment verified successfully"
```

### Running CI/CD Tests
```bash
# Trigger Cloud Build with tests
gcloud builds submit --config cloudbuild-api-test.yaml

# Verify deployment after Cloud Deploy
./scripts/verify-deployment.sh production mizzou-api

# Run smoke tests against production
pytest tests/smoke/ -v -m smoke \
  --production-url=http://compute.localnewsimpact.org
```

---

## Phase 5: Rollback Testing

### Rollback Procedure
```bash
# List recent releases
gcloud deploy releases list \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1

# Identify last known good release
GOOD_RELEASE="api-e7b3ece"

# Rollback
gcloud deploy rollouts rollback \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --release=$GOOD_RELEASE \
  --to-target=production

# Verify rollback
./scripts/verify-deployment.sh production mizzou-api
```

### Rollback Test Cases
```python
# tests/rollback/test_rollback_procedure.py

def test_rollback_preserves_data():
    """Test that rollback doesn't lose data."""
    # Record current article count
    before_count = get_article_count()
    
    # Simulate rollback (deploy old image)
    # ... rollback steps ...
    
    # Verify data still accessible
    after_count = get_article_count()
    assert after_count == before_count

def test_rollback_restores_functionality():
    """Test rolled-back version still works."""
    # After rollback, endpoints should still work
    response = requests.get(f"{API_URL}/api/ui_overview")
    assert response.status_code == 200
```

---

## Complications & Mitigation

### 1. **Cloud SQL Connection Limits**
**Risk**: Connection pool exhaustion under load  
**Mitigation**:
- Configure connection pool: `SQLALCHEMY_POOL_SIZE=20`
- Set `SQLALCHEMY_MAX_OVERFLOW=10`
- Implement connection retry logic
- Monitor with Cloud SQL metrics

```python
# src/models/database.py
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_recycle=3600,  # Recycle connections after 1 hour
    pool_pre_ping=True,  # Verify connections before use
)
```

### 2. **Test Data Isolation**
**Risk**: Integration tests pollute Cloud SQL test instance  
**Mitigation**:
- Use separate test database: `test_db`
- Implement database fixtures with cleanup
- Use transactions with rollback
- Consider test-specific schema prefix

```python
@pytest.fixture(scope="function")
def isolated_db_session():
    """Create isolated session that rolls back after test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()
```

### 3. **Performance Degradation**
**Risk**: Database queries slower than CSV reads  
**Mitigation**:
- Add database indexes (see Issue #44)
- Implement query result caching
- Use query optimization (EXPLAIN ANALYZE)
- Set up Cloud SQL Performance Insights

```sql
-- Required indexes for performance
CREATE INDEX CONCURRENTLY idx_articles_county ON articles(county);
CREATE INDEX CONCURRENTLY idx_articles_source_id ON articles(source_id);
CREATE INDEX CONCURRENTLY idx_articles_publish_date ON articles(publish_date DESC);
CREATE INDEX CONCURRENTLY idx_articles_wire_detected ON articles(wire_detected) 
  WHERE wire_detected = true;
```

### 4. **CI/CD Pipeline Timeouts**
**Risk**: Integration tests timeout Cloud Build  
**Mitigation**:
- Increase Cloud Build timeout to 20 minutes
- Run integration tests in parallel
- Cache Docker layers
- Use Cloud SQL Proxy sidecar pattern

### 5. **Data Migration During Deployment**
**Risk**: Schema changes break during rolling update  
**Mitigation**:
- Use backward-compatible migrations
- Deploy in phases:
  1. Run Alembic migrations first
  2. Deploy new API code
  3. Verify endpoints
- Keep old CSV code path as fallback (feature flag)

```python
# Backward-compatible migration approach
USE_DATABASE_QUERIES = os.getenv("USE_DATABASE_QUERIES", "true") == "true"

@app.get("/api/ui_overview")
def ui_overview():
    if USE_DATABASE_QUERIES:
        return ui_overview_from_database()
    else:
        return ui_overview_from_csv()  # Fallback
```

### 6. **Test Environment Costs**
**Risk**: Cloud SQL test instance adds costs  
**Mitigation**:
- Use smallest instance size (db-f1-micro)
- Auto-shutdown after hours
- Share test instance across team
- Consider local PostgreSQL for most tests

### 7. **Secret Management**
**Risk**: Test credentials exposed in CI/CD  
**Mitigation**:
- Use Google Secret Manager
- Never commit credentials
- Rotate test credentials regularly
- Implement least-privilege IAM

```yaml
# Cloud Build secret management
availableSecrets:
  secretManager:
    - versionName: projects/${PROJECT_ID}/secrets/test-db-password/versions/latest
      env: 'DATABASE_PASSWORD'
```

---

## Success Criteria

### Unit Tests
- ✅ All endpoint tests pass (100%)
- ✅ ≥80% line coverage on modified code
- ✅ Tests run in <30 seconds

### Integration Tests
- ✅ All Cloud SQL connection tests pass
- ✅ API endpoints return correct data from database
- ✅ Pagination works with >3,000 articles
- ✅ Query response time <500ms (95th percentile)

### Load Tests
- ✅ Handles 100 concurrent requests
- ✅ No connection pool exhaustion
- ✅ <1% error rate under load

### CI/CD Tests
- ✅ Cloud Build tests pass before deployment
- ✅ Smoke tests pass in staging
- ✅ Production verification succeeds
- ✅ Rollback procedure works

### Production Validation
- ✅ Dashboard displays real article counts (>3,900)
- ✅ No CSV file dependencies remain
- ✅ Zero 500 errors in first hour
- ✅ API response times meet SLA

---

## Testing Schedule

| Phase | Duration | Activities |
|-------|----------|------------|
| **Week 1** | 5 days | Unit tests, local integration tests |
| **Week 2** | 5 days | Cloud SQL integration, load tests |
| **Week 3** | 3 days | CI/CD integration, documentation |
| **Week 4** | 2 days | Staging deployment, production validation |

**Total Estimated Time**: 15 working days (3 weeks)

---

## Next Steps

1. ✅ Review and approve this testing plan
2. Create test fixtures and database seeds
3. Implement Phase 1 unit tests
4. Set up Cloud SQL test instance
5. Implement Phase 2 integration tests
6. Configure Cloud Build test pipeline
7. Deploy to staging and verify
8. Deploy to production with rollback plan ready

---

## References

- [Issue #44: Complete API Backend Migration](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/44)
- [Alembic Testing Documentation](./ALEMBIC_TESTING.md)
- [Cloud SQL Best Practices](https://cloud.google.com/sql/docs/postgres/best-practices)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [pytest-postgresql](https://pytest-postgresql.readthedocs.io/)
