# Google Cloud Platform + Kubernetes Deployment Roadmap

## Executive Summary

This roadmap outlines the migration of MizzouNewsCrawler from a monolithic local application to a cloud-native, microservices-based architecture on Google Cloud Platform (GCP) with Kubernetes (GKE).

**Target Architecture:**

- **Backend Services**: Kubernetes on GKE (bursty crawlers, background processors, APIs)
- **Frontend**: React SPA on Cloud Storage + Cloud CDN (static hosting)
- **Databases**: Cloud SQL (Postgres) for operational data, BigQuery for analytics
- **Storage**: Cloud Storage for raw assets (HTML, PDFs, screenshots)
- **Auth**: OAuth 2.0 with role-based access control (RBAC)
- **CI/CD**: GitHub Actions → Cloud Build → GKE for backend; GitHub Actions → Cloud Storage for frontend

---

## Phase 1: Containerization (Weeks 1-2)

### 1.1 Docker Strategy

**Goal**: Create efficient, layered Docker images for each service component.

#### 1.1.1 Base Image Strategy

```dockerfile
# Multi-stage build approach
FROM python:3.11-slim as base
# Common dependencies layer
FROM base as deps
# Service-specific layers
FROM deps as crawler
FROM deps as api
FROM deps as processor
```

**Services to containerize:**

1. **FastAPI Backend** (`backend/`)
   - Telemetry API
   - Admin API
   - Report generation API
2. **Crawler Service** (`src/crawler/`)
   - Discovery
   - Extraction
   - Verification
3. **Background Processor** (`src/cli/commands/`)
   - Content cleaning
   - Entity extraction
   - Classification
   - Analysis
4. **Frontend Build** (React)
   - Static build output

#### 1.1.2 Docker Image Optimization

- **Multi-stage builds**: Separate build and runtime dependencies
- **Layer caching**: Order Dockerfile commands for maximum cache reuse
- **Size optimization**:
  - Use slim base images
  - Remove build dependencies in final stage
  - .dockerignore for tests, docs, .git
- **ML Model handling**:
  - Option A: Bake models into image (slower builds, faster startup)
  - Option B: Init containers download from GCS (faster builds, slower startup)
  - **Recommendation**: Option B with caching

#### 1.1.3 Docker Compose for Local Development

```yaml
services:
  postgres:
    image: postgres:16
  api:
    build: ./backend
    depends_on: [postgres]
  crawler:
    build: .
    command: python -m src.cli.main discover-urls
  processor:
    build: .
    command: python -m src.cli.main extract
  frontend:
    build: ./web
    ports: ["3000:3000"]
```

**Deliverables:**

- [ ] `Dockerfile.api` - FastAPI backend
- [ ] `Dockerfile.crawler` - Crawler services
- [ ] `Dockerfile.processor` - Background processors
- [ ] `Dockerfile.frontend` - React build
- [ ] `docker-compose.yml` - Local development stack
- [ ] `.dockerignore` - Exclude unnecessary files
- [ ] `docs/DOCKER_GUIDE.md` - Build and run instructions

---

## Phase 2: GCP Infrastructure Setup (Weeks 2-3)

### 2.1 GCP Project Structure

```
├── Project: mizzou-news-production
│   ├── GKE Cluster: mizzou-crawler-cluster
│   ├── Cloud SQL: mizzou-crawler-db (Postgres 16)
│   ├── Cloud Storage Buckets:
│   │   ├── mizzou-raw-assets (HTML, PDFs)
│   │   ├── mizzou-ml-models (transformers, spacy)
│   │   ├── mizzou-frontend-prod (static site)
│   ├── BigQuery Dataset: mizzou_analytics
│   └── Artifact Registry: us-central1-docker.pkg.dev/mizzou-news/images
```

### 2.2 Resource Provisioning

#### 2.2.1 GKE Cluster Configuration

```yaml
Cluster Name: mizzou-crawler-cluster
Region: us-central1
Release Channel: Regular
GKE Version: Latest stable

Node Pools:
  - default-pool:
      machine-type: e2-medium
      min-nodes: 1
      max-nodes: 3
      auto-scaling: true
      
  - crawler-pool:
      machine-type: e2-standard-4  # Higher CPU for crawlers
      preemptible: true  # Cost savings for bursty workloads
      min-nodes: 0
      max-nodes: 10
      auto-scaling: true
      taints: [workload=crawler:NoSchedule]
      
  - processor-pool:
      machine-type: n2-highmem-2  # Higher memory for ML models
      min-nodes: 0
      max-nodes: 5
      auto-scaling: true
      taints: [workload=processor:NoSchedule]
```

#### 2.2.2 Cloud SQL (Postgres)

```
Instance: mizzou-crawler-db
Version: Postgres 16
Tier: db-custom-2-8192 (2 vCPU, 8 GB RAM)
Storage: 50 GB SSD (auto-increase enabled)
High Availability: Yes (for production)
Backups: Automated daily, 7-day retention
Private IP: Yes (VPC peering with GKE)
```

#### 2.2.3 Cloud Storage Buckets

```
mizzou-raw-assets:
  Location: us-central1
  Storage Class: Standard
  Lifecycle: Move to Nearline after 90 days
  Versioning: Disabled
  
mizzou-ml-models:
  Location: us-central1
  Storage Class: Standard
  Public access: Disabled
  
mizzou-frontend-prod:
  Location: multi-region US
  Storage Class: Standard
  Website configuration: index.html, 404.html
  Cloud CDN: Enabled
```

#### 2.2.4 BigQuery Dataset

```
Dataset: mizzou_analytics
Location: US
Tables:
  - articles (partitioned by publish_date, clustered by county, source_id)
  - entities (partitioned by extracted_at, clustered by entity_type)
  - cin_labels (partitioned by analysis_date, clustered by county)
  - telemetry_metrics (partitioned by timestamp, clustered by metric_type)
```

**Deliverables:**

- [ ] GCP project created with billing enabled
- [ ] Terraform/gcloud scripts for infrastructure provisioning
- [ ] GKE cluster created with node pools
- [ ] Cloud SQL instance provisioned
- [ ] Cloud Storage buckets created
- [ ] BigQuery dataset and initial schema
- [ ] VPC network and firewall rules configured
- [ ] IAM roles and service accounts set up
- [ ] `docs/GCP_INFRASTRUCTURE.md` - Architecture documentation

---

## Phase 3: Kubernetes Configuration (Weeks 3-4)

### 3.1 Kubernetes Architecture

```
Namespaces:
  - mizzou-prod: Production workloads
  - mizzou-staging: Staging/testing
  - mizzou-system: Infrastructure services (monitoring, etc.)

Services:
  1. FastAPI Backend (Deployment + Service + Ingress)
  2. Crawler Workers (CronJob + Job)
  3. Background Processors (Deployment with HPA)
  4. Postgres Proxy (Cloud SQL Proxy sidecar)
```

### 3.2 Helm Charts vs. Raw Manifests

**Recommendation: Start with Helm, transition to raw manifests if needed**

**Pros of Helm:**

- Templating for multi-environment deployments (dev/staging/prod)
- Version management and rollback
- Dependency management
- Community best practices

**Helm Chart Structure:**

```
helm/
├── mizzou-crawler/
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── values-prod.yaml
│   ├── values-staging.yaml
│   ├── templates/
│   │   ├── api/
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   ├── ingress.yaml
│   │   │   ├── hpa.yaml
│   │   ├── crawler/
│   │   │   ├── cronjob.yaml
│   │   │   ├── job.yaml
│   │   ├── processor/
│   │   │   ├── deployment.yaml
│   │   │   ├── hpa.yaml
│   │   ├── common/
│   │   │   ├── configmap.yaml
│   │   │   ├── secret.yaml
│   │   │   ├── serviceaccount.yaml
│   │   │   ├── cloudsql-proxy.yaml
```

### 3.3 Key Kubernetes Resources

#### 3.3.1 FastAPI Backend Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mizzou-api
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    spec:
      serviceAccountName: mizzou-api-sa
      containers:
      - name: api
        image: us-central1-docker.pkg.dev/mizzou-news/images/api:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: database-secret
              key: url
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
      - name: cloudsql-proxy
        image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:latest
        args:
        - "--structured-logs"
        - "--port=5432"
        - "PROJECT:REGION:INSTANCE"
        resources:
          requests:
            memory: 128Mi
            cpu: 100m
```

#### 3.3.2 Crawler CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mizzou-crawler-discovery
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          nodeSelector:
            workload: crawler
          tolerations:
          - key: workload
            operator: Equal
            value: crawler
            effect: NoSchedule
          containers:
          - name: crawler
            image: us-central1-docker.pkg.dev/mizzou-news/images/crawler:latest
            command: ["python", "-m", "src.cli.main", "discover-urls"]
            env:
            - name: SOURCE_LIMIT
              value: "50"
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: database-secret
                  key: url
            resources:
              requests:
                cpu: 2000m
                memory: 4Gi
              limits:
                cpu: 4000m
                memory: 8Gi
```

#### 3.3.3 Processor Deployment with HPA

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mizzou-processor
spec:
  replicas: 1  # HPA will adjust
  template:
    spec:
      nodeSelector:
        workload: processor
      tolerations:
      - key: workload
        operator: Equal
        value: processor
        effect: NoSchedule
      initContainers:
      - name: download-models
        image: google/cloud-sdk:slim
        command:
        - gsutil
        - -m
        - rsync
        - -r
        - gs://mizzou-ml-models/
        - /models
        volumeMounts:
        - name: models
          mountPath: /models
      containers:
      - name: processor
        image: us-central1-docker.pkg.dev/mizzou-news/images/processor:latest
        command: ["python", "-m", "src.cli.main", "extract"]
        volumeMounts:
        - name: models
          mountPath: /models
          readOnly: true
        resources:
          requests:
            cpu: 1000m
            memory: 4Gi
          limits:
            cpu: 2000m
            memory: 8Gi
      volumes:
      - name: models
        emptyDir: {}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mizzou-processor-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: mizzou-processor
  minReplicas: 0
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
```

#### 3.3.4 ConfigMaps and Secrets

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mizzou-config
data:
  LOG_LEVEL: "INFO"
  MAX_ARTICLES_PER_SOURCE: "40"
  DAYS_BACK: "7"
  GCS_BUCKET: "mizzou-raw-assets"
  BIGQUERY_DATASET: "mizzou_analytics"
---
apiVersion: v1
kind: Secret
metadata:
  name: database-secret
type: Opaque
stringData:
  url: "postgresql://user:pass@localhost:5432/mizzou"
  # In production, use Google Secret Manager
```

#### 3.3.5 Ingress with Cloud Load Balancer

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mizzou-ingress
  annotations:
    kubernetes.io/ingress.class: "gce"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    kubernetes.io/ingress.allow-http: "false"
spec:
  tls:
  - hosts:
    - api.mizzounewscrawler.org
    secretName: mizzou-tls
  rules:
  - host: api.mizzounewscrawler.org
    http:
      paths:
      - path: /telemetry
        pathType: Prefix
        backend:
          service:
            name: mizzou-api
            port:
              number: 8000
      - path: /admin
        pathType: Prefix
        backend:
          service:
            name: mizzou-api
            port:
              number: 8000
```

**Deliverables:**

- [ ] Helm chart structure created
- [ ] Deployment manifests for all services
- [ ] ConfigMaps and Secrets templates
- [ ] HPA configurations
- [ ] Ingress and Load Balancer setup
- [ ] Cloud SQL Proxy sidecars configured
- [ ] `docs/KUBERNETES_GUIDE.md` - Deployment instructions

---

## Phase 4: CI/CD Pipeline (Weeks 4-5)

### 4.1 CI/CD Architecture

```
GitHub → GitHub Actions → Cloud Build → Artifact Registry → GKE
                      ↓
                   Cloud Storage (Frontend)
```

### 4.2 Backend CI/CD Workflow

#### 4.2.1 GitHub Actions Workflow

```yaml
# .github/workflows/deploy-backend.yml
name: Deploy Backend to GKE

on:
  push:
    branches: [main]
    paths:
      - 'src/**'
      - 'backend/**'
      - 'requirements*.txt'
      - 'Dockerfile.*'
  workflow_dispatch:

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    
    steps:
    - uses: actions/checkout@v4
    
    - id: auth
      uses: google-github-actions/auth@v2
      with:
        workload_identity_provider: '${{ secrets.WIF_PROVIDER }}'
        service_account: '${{ secrets.WIF_SERVICE_ACCOUNT }}'
    
    - name: Set up Cloud SDK
      uses: google-github-actions/setup-gcloud@v2
    
    - name: Build images
      run: |
        gcloud builds submit \
          --tag us-central1-docker.pkg.dev/mizzou-news/images/api:${{ github.sha }} \
          --tag us-central1-docker.pkg.dev/mizzou-news/images/api:latest \
          -f Dockerfile.api .
        
        gcloud builds submit \
          --tag us-central1-docker.pkg.dev/mizzou-news/images/crawler:${{ github.sha }} \
          -f Dockerfile.crawler .
        
        gcloud builds submit \
          --tag us-central1-docker.pkg.dev/mizzou-news/images/processor:${{ github.sha }} \
          -f Dockerfile.processor .
    
    - name: Get GKE credentials
      run: |
        gcloud container clusters get-credentials mizzou-crawler-cluster \
          --region us-central1
    
    - name: Deploy with Helm
      run: |
        helm upgrade --install mizzou-crawler ./helm/mizzou-crawler \
          --namespace mizzou-prod \
          --create-namespace \
          --values ./helm/mizzou-crawler/values-prod.yaml \
          --set image.tag=${{ github.sha }} \
          --wait
    
    - name: Verify deployment
      run: |
        kubectl rollout status deployment/mizzou-api -n mizzou-prod
        kubectl get pods -n mizzou-prod
```

### 4.3 Frontend CI/CD Workflow

```yaml
# .github/workflows/deploy-frontend.yml
name: Deploy Frontend to Cloud Storage

on:
  push:
    branches: [main]
    paths:
      - 'web/**'
  workflow_dispatch:

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    
    steps:
    - uses: actions/checkout@v4
    
    - uses: actions/setup-node@v4
      with:
        node-version: '20'
        cache: 'npm'
        cache-dependency-path: web/package-lock.json
    
    - name: Build React app
      run: |
        cd web
        npm ci
        npm run build
    
    - id: auth
      uses: google-github-actions/auth@v2
      with:
        workload_identity_provider: '${{ secrets.WIF_PROVIDER }}'
        service_account: '${{ secrets.WIF_SERVICE_ACCOUNT }}'
    
    - name: Deploy to Cloud Storage
      run: |
        gsutil -m rsync -r -d web/build gs://mizzou-frontend-prod
        gsutil -m setmeta -h "Cache-Control:public, max-age=3600" \
          gs://mizzou-frontend-prod/**/*.html
        gsutil -m setmeta -h "Cache-Control:public, max-age=31536000" \
          gs://mizzou-frontend-prod/**/*.js
        gsutil -m setmeta -h "Cache-Control:public, max-age=31536000" \
          gs://mizzou-frontend-prod/**/*.css
    
    - name: Invalidate CDN cache
      run: |
        gcloud compute url-maps invalidate-cdn-cache mizzou-frontend-lb \
          --path "/*"
```

### 4.4 Staging Environment

```yaml
# Separate workflow for staging with manual approval
name: Deploy to Staging

on:
  pull_request:
    types: [opened, synchronize, reopened]
  workflow_dispatch:

jobs:
  deploy-staging:
    runs-on: ubuntu-latest
    environment: staging  # Requires manual approval
    steps:
      # Similar to production but uses:
      # - values-staging.yaml
      # - namespace: mizzou-staging
      # - subdomain: staging.mizzounewscrawler.org
```

**Deliverables:**

- [ ] GitHub Actions workflows for backend deployment
- [ ] GitHub Actions workflows for frontend deployment
- [ ] Cloud Build configurations
- [ ] Workload Identity Federation setup
- [ ] Staging environment workflow with approvals
- [ ] Rollback procedures documented
- [ ] `docs/CICD_GUIDE.md` - CI/CD pipeline documentation

---

## Phase 5: Data Pipeline Migration (Weeks 5-6)

### 5.1 Database Migration

#### 5.1.1 SQLite → Cloud SQL (Postgres)

```python
# Migration script
import sqlite3
import psycopg2
from sqlalchemy import create_engine

def migrate_to_postgres():
    # Export from SQLite
    sqlite_conn = sqlite3.connect('data/mizzou.db')
    sqlite_conn.row_factory = sqlite3.Row
    
    # Import to Postgres
    pg_engine = create_engine(os.environ['DATABASE_URL'])
    
    tables = ['sources', 'articles', 'candidate_links', 'article_entities', ...]
    
    for table in tables:
        print(f"Migrating {table}...")
        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
        
        # Batch insert into Postgres
        df = pd.DataFrame([dict(row) for row in rows])
        df.to_sql(table, pg_engine, if_exists='append', index=False, 
                  method='multi', chunksize=1000)
```

#### 5.1.2 Schema Updates for Cloud SQL

- Add indexes for common query patterns
- Add partitioning for large tables
- Update foreign key constraints
- Add audit columns (created_at, updated_at, created_by)

### 5.2 BigQuery Integration

#### 5.2.1 Data Export Pipeline

```python
# Scheduled job to export to BigQuery
from google.cloud import bigquery

def export_to_bigquery():
    # Export articles to BigQuery
    client = bigquery.Client()
    
    # Load from Postgres
    df = pd.read_sql("""
        SELECT 
            article_id,
            source_id,
            url,
            title,
            content,
            publish_date,
            extracted_at,
            county
        FROM articles
        WHERE extracted_at >= NOW() - INTERVAL '1 day'
    """, pg_engine)
    
    # Write to BigQuery
    table_ref = client.dataset('mizzou_analytics').table('articles')
    job_config = bigquery.LoadJobConfig(
        write_disposition='WRITE_APPEND',
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field='publish_date'
        ),
        clustering_fields=['county', 'source_id']
    )
    
    job = client.load_table_from_dataframe(df, table_ref, job_config=job_config)
    job.result()
```

#### 5.2.2 BigQuery Schema

```sql
-- articles table
CREATE TABLE mizzou_analytics.articles (
    article_id STRING NOT NULL,
    source_id INT64,
    url STRING,
    title STRING,
    content STRING,
    publish_date TIMESTAMP,
    extracted_at TIMESTAMP,
    county STRING,
    cin_labels ARRAY<STRUCT<label STRING, confidence FLOAT64>>
)
PARTITION BY DATE(publish_date)
CLUSTER BY county, source_id;

-- entities table
CREATE TABLE mizzou_analytics.entities (
    entity_id STRING NOT NULL,
    article_id STRING,
    entity_text STRING,
    entity_type STRING,
    confidence FLOAT64,
    extracted_at TIMESTAMP,
    county STRING
)
PARTITION BY DATE(extracted_at)
CLUSTER BY entity_type, county;
```

### 5.3 Cloud Storage for Raw Assets

```python
from google.cloud import storage

def upload_raw_asset(url, content, content_type):
    client = storage.Client()
    bucket = client.bucket('mizzou-raw-assets')
    
    # Use content hash as filename
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    blob_name = f"{content_type}/{content_hash[:2]}/{content_hash}.html"
    
    blob = bucket.blob(blob_name)
    blob.upload_from_string(content, content_type='text/html')
    
    return f"gs://mizzou-raw-assets/{blob_name}"
```

**Deliverables:**

- [ ] Migration scripts from SQLite to Cloud SQL
- [ ] BigQuery schema definitions
- [ ] Data export pipeline to BigQuery
- [ ] Cloud Storage integration for raw assets
- [ ] Data validation and reconciliation scripts
- [ ] `docs/DATA_MIGRATION_GUIDE.md` - Migration procedures

---

## Phase 6: Frontend Development (Weeks 6-8)

### 6.1 React Application Architecture

```
web/
├── public/
├── src/
│   ├── components/
│   │   ├── admin/
│   │   │   ├── UserManagement.tsx
│   │   │   ├── SourceManagement.tsx
│   │   │   ├── PermissionEditor.tsx
│   │   ├── telemetry/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── MetricsChart.tsx
│   │   │   ├── LogViewer.tsx
│   │   ├── reports/
│   │   │   ├── ArticleList.tsx
│   │   │   ├── CountyReport.tsx
│   │   │   ├── ExportDialog.tsx
│   │   ├── common/
│   │   │   ├── Layout.tsx
│   │   │   ├── Navigation.tsx
│   │   │   ├── Auth.tsx
│   ├── services/
│   │   ├── api.ts
│   │   ├── auth.ts
│   ├── hooks/
│   ├── contexts/
│   │   ├── AuthContext.tsx
│   │   ├── ThemeContext.tsx
│   ├── types/
│   ├── utils/
│   ├── App.tsx
│   ├── index.tsx
├── package.json
├── tsconfig.json
├── vite.config.ts
```

### 6.2 Key Features

#### 6.2.1 Authentication & Authorization

- OAuth 2.0 integration (Google, GitHub)
- JWT token management
- Role-based access control (RBAC)
  - Roles: Admin, Editor, Viewer, Reporter
  - Permissions: read:articles, write:sources, admin:users, etc.

#### 6.2.2 Admin Portal

- User management (invite, roles, permissions)
- Source configuration (add, edit, disable sources)
- System settings (rate limits, extraction params)
- Audit logs

#### 6.2.3 Telemetry Dashboard

- Real-time metrics (articles crawled, errors, queue depth)
- Historical trends (charts, graphs)
- System health (CPU, memory, disk, API latency)
- Alert configuration

#### 6.2.4 Report/Export Interface

- Article search and filtering
- County-based reports
- Export to CSV, JSON, Excel
- Scheduled report generation

### 6.3 Technology Stack

- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite
- **UI Library**: Material-UI (MUI) or Chakra UI
- **State Management**: React Query + Zustand
- **Charts**: Recharts or Chart.js
- **Forms**: React Hook Form + Zod validation
- **Routing**: React Router v6

**Deliverables:**

- [ ] React application scaffolding
- [ ] Authentication flow implemented
- [ ] Admin portal components
- [ ] Telemetry dashboard
- [ ] Report generation interface
- [ ] Responsive design
- [ ] Unit and integration tests
- [ ] `web/README.md` - Frontend development guide

---

## Phase 7: Security & Compliance (Weeks 8-9)

### 7.1 Authentication & Authorization

#### 7.1.1 OAuth 2.0 Implementation

```python
# FastAPI backend
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://accounts.google.com/o/oauth2/v2/auth",
    tokenUrl="https://oauth2.googleapis.com/token"
)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Validate JWT token
    # Check permissions
    # Return user object
    pass
```

#### 7.1.2 Role-Based Access Control

```python
from enum import Enum

class Role(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    REPORTER = "reporter"

class Permission(str, Enum):
    READ_ARTICLES = "read:articles"
    WRITE_ARTICLES = "write:articles"
    READ_SOURCES = "read:sources"
    WRITE_SOURCES = "write:sources"
    ADMIN_USERS = "admin:users"
    EXPORT_DATA = "export:data"

ROLE_PERMISSIONS = {
    Role.ADMIN: list(Permission),
    Role.EDITOR: [
        Permission.READ_ARTICLES, Permission.WRITE_ARTICLES,
        Permission.READ_SOURCES, Permission.WRITE_SOURCES,
        Permission.EXPORT_DATA
    ],
    Role.VIEWER: [Permission.READ_ARTICLES, Permission.READ_SOURCES],
    Role.REPORTER: [Permission.READ_ARTICLES, Permission.EXPORT_DATA]
}

def require_permission(permission: Permission):
    def decorator(func):
        async def wrapper(*args, current_user=Depends(get_current_user), **kwargs):
            if permission not in ROLE_PERMISSIONS[current_user.role]:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator
```

### 7.2 Secrets Management

#### 7.2.1 Google Secret Manager Integration

```python
from google.cloud import secretmanager

def get_secret(secret_id: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

# Usage
DATABASE_PASSWORD = get_secret('database-password')
OAUTH_CLIENT_SECRET = get_secret('oauth-client-secret')
```

#### 7.2.2 Kubernetes Secrets from Secret Manager

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: database-secret
  annotations:
    secrets.google.com/secret: "database-password"
    secrets.google.com/version: "latest"
type: Opaque
```

### 7.3 Network Security

#### 7.3.1 VPC and Firewall Rules

- Private GKE cluster (no public endpoints)
- Cloud SQL with private IP only
- VPC peering between GKE and Cloud SQL
- Firewall rules:
  - Allow internal traffic within VPC
  - Allow HTTPS ingress via Load Balancer
  - Deny all other ingress

#### 7.3.2 SSL/TLS Certificates

```yaml
# Use cert-manager for automatic certificate management
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@mizzounewscrawler.org
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: gce
```

### 7.4 Compliance & Auditing

#### 7.4.1 Audit Logging

```python
from google.cloud import logging

def log_audit_event(user_id, action, resource, result):
    client = logging.Client()
    logger = client.logger('audit-log')
    
    logger.log_struct({
        'user_id': user_id,
        'action': action,
        'resource': resource,
        'result': result,
        'timestamp': datetime.utcnow().isoformat(),
        'ip_address': request.client.host
    })
```

#### 7.4.2 Data Retention Policies

- Article data: Retain indefinitely (research data)
- Raw HTML: Retain for 1 year, then move to Nearline storage
- Logs: Retain for 90 days
- Telemetry: Aggregate to daily summaries after 30 days

**Deliverables:**

- [ ] OAuth 2.0 authentication implemented
- [ ] RBAC system with permissions
- [ ] Secret Manager integration
- [ ] VPC and firewall rules configured
- [ ] SSL/TLS certificates automated
- [ ] Audit logging implemented
- [ ] Data retention policies configured
- [ ] Security documentation
- [ ] `docs/SECURITY_GUIDE.md` - Security practices

---

## Phase 8: Observability & Monitoring (Weeks 9-10)

### 8.1 Monitoring Stack

**Components:**

- **Metrics**: Google Cloud Monitoring (formerly Stackdriver)
- **Logs**: Cloud Logging with Log Explorer
- **Traces**: Cloud Trace
- **Dashboards**: Cloud Monitoring dashboards + Grafana (optional)
- **Alerting**: Cloud Monitoring alerts + PagerDuty integration

### 8.2 Application Instrumentation

#### 8.2.1 Structured Logging

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "article_extracted",
    article_id=article.id,
    source_id=article.source_id,
    county=article.county,
    extraction_time_ms=extraction_time * 1000,
    trace_id=trace_id
)
```

#### 8.2.2 Custom Metrics

```python
from google.cloud import monitoring_v3

def record_metric(metric_name, value, labels=None):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{PROJECT_ID}"
    
    series = monitoring_v3.TimeSeries()
    series.metric.type = f"custom.googleapis.com/{metric_name}"
    series.resource.type = "k8s_pod"
    
    if labels:
        for key, value in labels.items():
            series.metric.labels[key] = value
    
    point = series.points.add()
    point.value.int64_value = value
    point.interval.end_time.seconds = int(time.time())
    
    client.create_time_series(name=project_name, time_series=[series])

# Usage
record_metric("articles_extracted", 1, {"county": "Boone", "source": "columbia-tribune"})
record_metric("extraction_duration_ms", 1250, {"county": "Boone"})
```

#### 8.2.3 Health Check Endpoints

```python
from fastapi import FastAPI, Response
from sqlalchemy import text

app = FastAPI()

@app.get("/health")
async def health():
    # Liveness probe - is the service running?
    return {"status": "healthy"}

@app.get("/ready")
async def readiness():
    # Readiness probe - can the service handle requests?
    try:
        # Check database connection
        engine.execute(text("SELECT 1"))
        # Check other dependencies
        return {"status": "ready", "checks": {"database": "ok"}}
    except Exception as e:
        return Response(
            content={"status": "not ready", "error": str(e)},
            status_code=503
        )
```

### 8.3 Monitoring Dashboards

#### 8.3.1 System Health Dashboard

- Pod CPU/Memory usage
- Node resource utilization
- API request rate and latency (p50, p95, p99)
- Error rate
- Database connections and query performance

#### 8.3.2 Pipeline Metrics Dashboard

- Articles discovered per hour
- Articles extracted per hour
- Extraction success rate
- Queue depth (pending articles)
- Processing time per stage

#### 8.3.3 Business Metrics Dashboard

- Articles by county
- Articles by source
- CIN label distribution
- Entity extraction coverage
- Data completeness metrics

### 8.4 Alerting

#### 8.4.1 Alert Policies

```yaml
# Example alert policy (via Terraform or gcloud)
name: high-error-rate
conditions:
  - displayName: Error rate > 5%
    conditionThreshold:
      filter: metric.type="custom.googleapis.com/api_errors"
      comparison: COMPARISON_GT
      thresholdValue: 0.05
      duration: 300s
notificationChannels:
  - projects/PROJECT_ID/notificationChannels/CHANNEL_ID
```

**Critical Alerts:**

- API error rate > 5% for 5 minutes
- Pod restart count > 3 in 10 minutes
- Database connection failure
- Disk usage > 80%
- Queue depth > 1000 for 30 minutes

**Warning Alerts:**

- API latency p95 > 1s
- Memory usage > 80%
- Crawler success rate < 90%

**Deliverables:**

- [ ] Structured logging implemented
- [ ] Custom metrics instrumented
- [ ] Health check endpoints added
- [ ] Cloud Monitoring dashboards created
- [ ] Alert policies configured
- [ ] PagerDuty integration (optional)
- [ ] `docs/OBSERVABILITY_GUIDE.md` - Monitoring documentation

---

## Phase 9: Testing & Validation (Weeks 10-11)

### 9.1 Testing Strategy

#### 9.1.1 Unit Tests

- Continue existing pytest coverage (current: 82.93%)
- Add tests for new cloud integrations
- Mock GCP services using `google-cloud-testutils`

#### 9.1.2 Integration Tests

```python
# Test Cloud SQL connection
def test_postgres_connection():
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1

# Test BigQuery export
def test_bigquery_export():
    export_to_bigquery()
    
    client = bigquery.Client()
    query = """
        SELECT COUNT(*) as count
        FROM mizzou_analytics.articles
        WHERE DATE(extracted_at) = CURRENT_DATE()
    """
    result = client.query(query).result()
    count = next(result).count
    assert count > 0
```

#### 9.1.3 End-to-End Tests

```python
# Test full pipeline
@pytest.mark.e2e
def test_full_pipeline():
    # 1. Discover URLs
    subprocess.run(["python", "-m", "src.cli.main", "discover-urls", 
                    "--source-limit", "1"], check=True)
    
    # 2. Extract content
    subprocess.run(["python", "-m", "src.cli.main", "extract", 
                    "--limit", "1"], check=True)
    
    # 3. Verify in database
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT COUNT(*) FROM articles WHERE extracted_at >= NOW() - INTERVAL '5 minutes'"
        ))
        assert result.scalar() > 0
    
    # 4. Verify in BigQuery
    # ... check BigQuery
```

#### 9.1.4 Load Testing

```python
# Using locust for API load testing
from locust import HttpUser, task, between

class TelemetryAPIUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def get_metrics(self):
        self.client.get("/telemetry/metrics")
    
    @task(3)
    def get_articles(self):
        self.client.get("/articles?county=Boone&limit=20")
```

### 9.2 Staging Environment Testing

1. **Deploy to staging**: `helm upgrade mizzou-crawler ./helm --values values-staging.yaml`
2. **Run smoke tests**: Basic functionality checks
3. **Run integration tests**: Full pipeline validation
4. **Run load tests**: Performance under load
5. **Security scan**: OWASP ZAP, vulnerability scanning
6. **Manual QA**: UI testing, edge cases

### 9.3 Production Rollout Strategy

#### 9.3.1 Blue-Green Deployment

```yaml
# Deploy new version alongside old
helm upgrade mizzou-crawler-green ./helm --values values-prod.yaml \
  --set image.tag=v2.0.0 \
  --set service.name=mizzou-api-green

# Test green deployment
kubectl port-forward svc/mizzou-api-green 8000:8000

# Switch traffic
kubectl patch svc mizzou-api -p '{"spec":{"selector":{"version":"green"}}}'

# Rollback if needed
kubectl patch svc mizzou-api -p '{"spec":{"selector":{"version":"blue"}}}'
```

#### 9.3.2 Canary Deployment

```yaml
# Gradually shift traffic using Istio or similar
# Start: 95% old, 5% new
# After 1 hour: 80% old, 20% new
# After 4 hours: 50% old, 50% new
# After 24 hours: 0% old, 100% new
```

**Deliverables:**

- [ ] Integration tests for GCP services
- [ ] End-to-end pipeline tests
- [ ] Load testing suite
- [ ] Staging environment fully tested
- [ ] Production rollout plan
- [ ] Rollback procedures tested
- [ ] `docs/TESTING_GUIDE.md` - Testing documentation

---

## Phase 10: Production Launch & Optimization (Weeks 11-12)

### 10.1 Pre-Launch Checklist

- [ ] All services deployed and healthy
- [ ] Monitoring and alerting configured
- [ ] Database backups automated
- [ ] Disaster recovery plan documented
- [ ] Security audit completed
- [ ] Performance benchmarks met
- [ ] User documentation complete
- [ ] Support processes established

### 10.2 Launch Day Activities

1. **Final data migration**: Migrate production data to Cloud SQL
2. **DNS cutover**: Point domain to new infrastructure
3. **Monitor closely**: Watch dashboards for issues
4. **Communicate**: Notify users of any downtime
5. **Standby team**: On-call for issues

### 10.3 Post-Launch Optimization

#### 10.3.1 Cost Optimization

- Review resource utilization
- Right-size node pools
- Use committed use discounts
- Implement preemptible nodes for batch workloads
- Set up budget alerts

#### 10.3.2 Performance Tuning

- Optimize database queries
- Add caching (Redis/Memorystore)
- CDN optimization
- Image optimization
- Code profiling

#### 10.3.3 Continuous Improvement

- Weekly metrics review
- Monthly cost review
- Quarterly architecture review
- User feedback integration

**Deliverables:**

- [ ] Production environment live
- [ ] Cost optimization plan
- [ ] Performance tuning completed
- [ ] Documentation finalized
- [ ] Post-mortem document (if issues)
- [ ] `docs/PRODUCTION_RUNBOOK.md` - Operations guide

---

## Summary Timeline

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| 1. Containerization | 2 weeks | Dockerfiles, docker-compose |
| 2. GCP Infrastructure | 1 week | GKE, Cloud SQL, Cloud Storage, BigQuery |
| 3. Kubernetes Config | 1 week | Helm charts, deployments, services |
| 4. CI/CD Pipeline | 1 week | GitHub Actions, Cloud Build integration |
| 5. Data Migration | 1 week | SQLite → Postgres, BigQuery export |
| 6. Frontend Development | 2 weeks | React app, admin portal, dashboards |
| 7. Security & Compliance | 1 week | OAuth, RBAC, secrets management |
| 8. Observability | 1 week | Monitoring, logging, alerting |
| 9. Testing & Validation | 1 week | Integration tests, load tests, staging |
| 10. Production Launch | 1 week | Launch, optimization |
| **Total** | **12 weeks** | **Full production deployment** |

---

## Decision Points & Discussion Topics

### 1. Dockerfiles - Immediate Start ✅

**Decision**: Yes, start now

- Low risk, high value
- Enables local development improvements
- Foundation for everything else
- Can iterate and refine over time

**Action**: Create base Dockerfiles in Phase 1

### 2. Helm Charts - Yes, but Keep Simple

**Decision**: Use Helm, but avoid over-engineering

- Start with basic templates
- Add complexity only when needed
- Document why Helm vs. raw manifests
- Keep values.yaml simple and flat

**Questions to resolve:**

- How many environments? (dev/staging/prod)
- Shared values vs. per-environment?
- Chart versioning strategy?

### 3. CI/CD - Phased Approach

**Decision**: Start manual, automate incrementally

- Phase 1: Manual deployment via kubectl/helm
- Phase 2: GitHub Actions for images
- Phase 3: Automated deployment to staging
- Phase 4: Automated deployment to prod (with gates)

**Questions to resolve:**

- Approval gates for production?
- Rollback automation?
- Deployment notifications (Slack, email)?

### 4. Cost Management Strategy

**Key concerns:**

- GKE cluster costs (~$75/month minimum)
- Cloud SQL (~$50-200/month depending on size)
- BigQuery (~$5/TB query, $20/TB storage)
- Cloud Storage (~$20/TB/month)
- Egress costs

**Cost optimization:**

- Use preemptible nodes for batch workloads (60-90% savings)
- Auto-scaling to zero for non-production
- Committed use discounts (1-year: 37% off, 3-year: 55% off)
- Regional resources (cheaper than multi-region)
- Budget alerts and quotas

**Questions to resolve:**

- Monthly budget limit?
- Cost allocation by project/team?
- Acceptable cost per article crawled?

### 5. Data Pipeline Architecture

**Current**: Monolithic batch processing
**Proposed**: Event-driven microservices

**Options:**
A. **Keep batch processing** (simpler)

- Scheduled CronJobs in Kubernetes
- Process N articles per run
- Simpler to reason about

B. **Event-driven with Pub/Sub** (more scalable)

- Article discovered → publish to discovery topic
- Extraction service subscribes
- Better scaling, more complexity

C. **Hybrid** (recommended)

- Discovery: scheduled batch (CronJob)
- Extraction: queue-based (Cloud Tasks or Pub/Sub)
- Analysis: batch processing (nightly)

**Questions to resolve:**

- Expected article volume?
- Latency requirements (real-time vs. batch)?
- Cost tolerance for Pub/Sub?

### 6. Multi-tenancy Design

**Scenario**: Multiple universities/organizations using same infrastructure

**Options:**
A. **Namespace per tenant** (Kubernetes-native)

- Separate namespace per org
- Separate databases per org
- Resource quotas per namespace

B. **Single namespace, tenant column** (application-level)

- Single database with tenant_id column
- Row-level security
- Shared resources

C. **Separate clusters** (maximum isolation)

- Separate GKE cluster per tenant
- No resource contention
- Higher operational overhead

**Questions to resolve:**

- How many tenants expected?
- Isolation requirements?
- Cost per tenant?

---

## Next Steps (Immediate)

1. **This week**:
   - Review this roadmap
   - Answer discussion questions
   - Prioritize phases
   - Create GitHub issues for each phase

2. **Next week**:
   - Start Phase 1: Containerization
   - Create Dockerfile.api
   - Create Dockerfile.crawler
   - Create docker-compose.yml for local dev

3. **Week 3**:
   - GCP project setup
   - Enable APIs
   - Create service accounts
   - Provision GKE cluster

4. **Ongoing**:
   - Weekly progress reviews
   - Update roadmap as needed
   - Document decisions and lessons learned

---

## Questions for Discussion

1. **Budget**: What's the monthly budget for GCP costs?
2. **Timeline**: Is 12 weeks realistic, or do we need to adjust scope?
3. **Team**: Who will be responsible for each phase?
4. **Priorities**: Which phases are must-have vs. nice-to-have?
5. **Multi-tenancy**: Do we need to support multiple organizations from day 1?
6. **Data retention**: How long should we keep raw HTML, articles, etc.?
7. **Compliance**: Any specific compliance requirements (GDPR, CCPA, etc.)?
8. **Disaster recovery**: What's the acceptable RTO/RPO?

---

*This roadmap is a living document. Please provide feedback and ask questions!*
