# Kubernetes Deployment Guide

## Overview

This guide documents the Kubernetes deployment architecture for MizzouNewsCrawler on Google Kubernetes Engine (GKE).

## Architecture Decision: Raw Manifests vs Helm Charts

### Decision Summary

**We chose raw Kubernetes YAML manifests instead of Helm charts.**

### Rationale

**Reasons for choosing raw manifests:**

1. **Simplicity**: Single production environment means templating overhead isn't needed
2. **Transparency**: Raw YAML is easier to debug and understand
3. **Direct control**: No abstraction layer between us and Kubernetes
4. **Faster iteration**: Can apply changes directly without Helm release management
5. **Smaller learning curve**: Team already familiar with Kubernetes YAML

**When we might reconsider Helm:**
- Multiple environments (dev/staging/prod) with different configs
- Complex dependency management between charts
- Need for version rollback beyond kubectl rollout undo
- Sharing configuration with other teams/projects

### Current Approach

- All manifests in `k8s/` directory
- Organized by service type (deployments, cronjobs, argo workflows)
- Applied directly with `kubectl apply -f`
- Version control via Git commits
- Deployments managed via Cloud Build + kubectl

## Repository Structure

```
k8s/
├── api-deployment.yaml           # FastAPI backend deployment
├── processor-deployment.yaml     # Background processor deployment
├── cli-deployment.yaml           # CLI utility deployment
├── priority-classes.yaml         # Pod priority configuration
├── pdbs/                         # Pod Disruption Budgets
│   ├── mizzou-api-pdb.yaml
│   └── mizzou-processor-pdb.yaml
├── argo/                         # Argo Workflows configuration
│   ├── rbac.yaml                 # RBAC for Argo
│   ├── base-pipeline-workflow.yaml
│   ├── dataset-pipeline-template.yaml
│   └── mizzou-pipeline-cronworkflow.yaml
├── jobs/                         # One-time jobs
│   └── run-alembic-migrations.yaml
└── templates/                    # Reusable job templates
    ├── dataset-discovery-job.yaml
    └── dataset-extraction-job.yaml
```

## Deployment Components

### Core Services

#### 1. API Deployment (`mizzou-api`)
- **Purpose**: FastAPI backend serving telemetry and admin APIs
- **Replicas**: 1 (can scale to 5 with HPA if needed)
- **Resources**: 250m-1000m CPU, 512Mi-1Gi memory
- **Endpoints**:
  - `/health` - Liveness probe
  - `/ready` - Readiness probe (checks DB connection)
  - `/telemetry/*` - Telemetry API routes
  - `/admin/*` - Admin API routes

#### 2. Processor Deployment (`mizzou-processor`)
- **Purpose**: Background processing for content cleaning, entity extraction, classification
- **Replicas**: 1 (can scale based on workload)
- **Resources**: 1-2 CPU, 4-8Gi memory
- **Features**:
  - ML model loading from Cloud Storage
  - Auto-scaling based on queue depth
  - Cloud SQL Proxy sidecar for database access

#### 3. CLI Deployment (`mizzou-cli`)
- **Purpose**: Utility container for running one-off commands
- **Replicas**: 0 (scaled up manually when needed)
- **Use cases**:
  - Database migrations
  - Data cleanup
  - Manual pipeline operations

### Argo Workflows

#### CronWorkflow: `mizzou-news-pipeline`
- **Schedule**: `0 */6 * * *` (every 6 hours)
- **Steps**:
  1. **Discovery**: Find new articles from configured sources
  2. **Verification**: Validate discovered URLs
  3. **Extraction**: Extract content from articles
- **Concurrency**: Forbid (prevents overlapping runs)

### Supporting Resources

#### Priority Classes
- **high-priority**: For critical API services
- **medium-priority**: For scheduled pipelines
- **low-priority**: For batch processing

#### Pod Disruption Budgets (PDBs)
- Ensures minimum availability during cluster maintenance
- API: minAvailable=1
- Processor: minAvailable=0 (can tolerate disruption)

## Database Configuration

### Cloud SQL Connection

All services connect to Cloud SQL (PostgreSQL 16) using:

**Method**: Cloud SQL Python Connector (recommended)
- Environment: `USE_CLOUD_SQL_CONNECTOR=true`
- Connection: unix socket via IAM authentication
- No proxy sidecar needed

**Alternative**: Cloud SQL Proxy sidecar (legacy)
- Proxy container in each pod
- Connects via localhost:5432

### Database Environment Variables

Required in all deployments:
```yaml
env:
- name: DATABASE_ENGINE
  value: "postgresql+psycopg2"
- name: DATABASE_HOST
  value: "127.0.0.1"  # or Cloud SQL instance connection name
- name: DATABASE_PORT
  value: "5432"
- name: DATABASE_NAME
  valueFrom:
    secretKeyRef:
      name: cloudsql-db-credentials
      key: database
- name: DATABASE_USER
  valueFrom:
    secretKeyRef:
      name: cloudsql-db-credentials
      key: username
- name: DATABASE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: cloudsql-db-credentials
      key: password
- name: DATABASE_URL
  value: "$(DATABASE_ENGINE)://$(DATABASE_USER):$(DATABASE_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(DATABASE_NAME)"
```

**Important**: The `DATABASE_URL` environment variable is critical - without it, the application falls back to SQLite.

## Deployment Procedures

### Initial Deployment

```bash
# 1. Configure kubectl context
gcloud container clusters get-credentials mizzou-cluster \
  --region us-central1-a \
  --project mizzou-news-crawler

# 2. Create namespace (if not exists)
kubectl create namespace production

# 3. Create secrets
kubectl create secret generic cloudsql-db-credentials \
  --from-literal=username=mizzou_user \
  --from-literal=password='YOUR_PASSWORD' \
  --from-literal=database=mizzou \
  -n production

# 4. Apply priority classes (cluster-wide)
kubectl apply -f k8s/priority-classes.yaml

# 5. Deploy core services
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/processor-deployment.yaml

# 6. Deploy Argo workflows
kubectl apply -f k8s/argo/rbac.yaml
kubectl apply -f k8s/argo/base-pipeline-workflow.yaml
kubectl apply -f k8s/argo/mizzou-pipeline-cronworkflow.yaml

# 7. Apply Pod Disruption Budgets
kubectl apply -f k8s/pdbs/

# 8. Verify deployments
kubectl get deployments -n production
kubectl get pods -n production
kubectl get cronworkflows -n production
```

### Updating Deployments

#### Option 1: Via Cloud Build (Recommended)

```bash
# Trigger manual build for specific service
gcloud builds triggers run build-api-manual --branch=feature/gcp-kubernetes-deployment
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment
```

Cloud Build will:
1. Build new Docker image
2. Push to Artifact Registry
3. Update deployment with new image tag
4. Perform rolling update

#### Option 2: Manual kubectl

```bash
# Update image tag
kubectl set image deployment/mizzou-processor \
  processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:NEW_TAG \
  -n production

# Or apply updated YAML
kubectl apply -f k8s/processor-deployment.yaml

# Watch rollout
kubectl rollout status deployment/mizzou-processor -n production

# Rollback if needed
kubectl rollout undo deployment/mizzou-processor -n production
```

### Viewing Logs

```bash
# Stream logs from a deployment
kubectl logs -f deployment/mizzou-api -n production

# Get logs from specific pod
kubectl logs POD_NAME -n production

# Get logs from all pods with label
kubectl logs -l app=mizzou-processor -n production --tail=100

# View Argo workflow logs
kubectl logs -n production $(kubectl get pod -n production -l workflows.argoproj.io/workflow=WORKFLOW_NAME -o name)
```

### Scaling

```bash
# Manual scaling
kubectl scale deployment/mizzou-processor --replicas=3 -n production

# Enable Horizontal Pod Autoscaler (HPA)
kubectl autoscale deployment/mizzou-processor \
  --min=1 --max=5 --cpu-percent=70 \
  -n production

# Check HPA status
kubectl get hpa -n production
```

## Troubleshooting

### Pod Not Starting

```bash
# Describe pod for events
kubectl describe pod POD_NAME -n production

# Check pod logs
kubectl logs POD_NAME -n production

# Common issues:
# - Image pull errors: Check Artifact Registry permissions
# - CrashLoopBackOff: Check application logs for startup errors
# - Pending: Check resource requests vs available cluster capacity
```

### Database Connection Issues

```bash
# Check secret exists
kubectl get secret cloudsql-db-credentials -n production

# Verify DATABASE_URL is set
kubectl exec deployment/mizzou-processor -n production -- env | grep DATABASE

# Test database connectivity
kubectl exec deployment/mizzou-processor -n production -- \
  python -c "from src.database import get_engine; engine = get_engine(); print(engine.connect())"
```

### Argo Workflow Issues

```bash
# List workflows
kubectl get workflows -n production

# Describe workflow
kubectl describe workflow WORKFLOW_NAME -n production

# Get workflow logs
argo logs WORKFLOW_NAME -n production

# Delete stuck workflow
kubectl delete workflow WORKFLOW_NAME -n production
```

### Image Not Updating

If pods aren't using the new image after deployment:

```bash
# Force restart deployment
kubectl rollout restart deployment/mizzou-processor -n production

# Verify image tag
kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}'

# Check if pods are using new image
kubectl get pods -n production -o jsonpath='{.items[*].spec.containers[0].image}'
```

## Security Best Practices

### Secrets Management

- **Never commit secrets to Git**: Use Kubernetes secrets or Google Secret Manager
- **Rotate credentials regularly**: Update secrets every 90 days
- **Use least privilege**: Grant minimal permissions to service accounts

### Network Security

- **Private GKE cluster**: Control plane not publicly accessible
- **Cloud SQL private IP**: Database only accessible from VPC
- **Workload Identity**: Use IAM instead of service account keys

### Resource Limits

Always set resource limits to prevent resource exhaustion:
```yaml
resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
```

## Monitoring

### Basic Health Checks

```bash
# Check all pods
kubectl get pods -n production

# Check services
kubectl get services -n production

# Check resource usage
kubectl top pods -n production
kubectl top nodes
```

### Database Telemetry

The application includes built-in telemetry stored in PostgreSQL:

```bash
# Access database
kubectl exec -it deployment/mizzou-processor -n production -- \
  psql $DATABASE_URL

# Query recent operations
SELECT * FROM discovery_operations ORDER BY created_at DESC LIMIT 10;

# Check pipeline status via CLI
kubectl exec deployment/mizzou-processor -n production -- \
  python -m src.cli.main pipeline-status
```

## Cost Optimization

### Current Resource Allocation

- **GKE cluster**: 1-3 nodes (e2-medium, e2-standard-4 preemptible)
- **Cloud SQL**: db-custom-2-8192 (2 vCPU, 8GB RAM)
- **Target budget**: $150-200/month

### Optimization Strategies

1. **Use preemptible nodes** for crawler workloads (60-90% cost savings)
2. **Scale to zero** during off-hours if workload allows
3. **Right-size resources** based on actual usage
4. **Enable cluster autoscaling** to match demand
5. **Use committed use discounts** for steady-state resources

### Monitor Costs

```bash
# View current billing
gcloud billing accounts list
gcloud billing projects describe mizzou-news-crawler

# Set budget alerts at 90% of target ($180/month)
```

## Next Steps

### Recommended Improvements

1. **Staging environment**: Create separate namespace for testing
2. **Health endpoints**: Ensure all services expose `/health` and `/ready`
3. **Horizontal Pod Autoscaling**: Configure HPA for API and processor
4. **Monitoring dashboards**: Set up Cloud Monitoring for visibility
5. **Alert policies**: Configure alerts for errors, latency, resource usage

### Documentation

See also:
- [GCP Kubernetes Roadmap](./GCP_KUBERNETES_ROADMAP.md) - Overall migration plan
- [Docker Guide](./DOCKER_GUIDE.md) - Container build process
- [Migration Runbook](./MIGRATION_RUNBOOK.md) - Database migration procedures
- [Pipeline Monitoring](./PIPELINE_MONITORING.md) - Telemetry and observability

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review pod/deployment logs
3. Check #mizzou-news-crawler Slack channel
4. Contact DevOps team

---

**Last Updated**: October 17, 2025  
**Kubernetes Version**: 1.33.4  
**GKE Cluster**: mizzou-cluster (us-central1-a)
