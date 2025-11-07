# Kustomize Base + Overlays for Multi-Environment Setup

This directory structure uses Kustomize to manage staging and production environments.

## Structure

```
k8s/
├── base/                          # Base manifests (environment-agnostic)
│   ├── kustomization.yaml
│   ├── api-deployment.yaml
│   ├── processor-deployment.yaml
│   ├── cli-deployment.yaml
│   └── argo/
│       ├── base-pipeline-workflow.yaml
│       └── mizzou-pipeline-cronworkflow.yaml
├── overlays/
│   ├── staging/                   # Staging-specific overrides
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   └── patches/
│   │       ├── reduce-resources.yaml
│   │       └── staging-database.yaml
│   └── production/                # Production-specific overrides
│       ├── kustomization.yaml
│       ├── namespace.yaml
│       └── patches/
│           └── production-images.yaml
```

## Usage

### Apply to Staging
```bash
kubectl apply -k k8s/overlays/staging
```

### Apply to Production
```bash
kubectl apply -k k8s/overlays/production
```

### Test Workflow in Staging
```bash
# Submit workflow to staging namespace
argo submit --from workflowtemplate/news-pipeline-template -n staging \
  -p dataset="Test Dataset" \
  -p limit=10

# Monitor staging workflow
argo logs -n staging @latest -f
```

### Promote to Production
```bash
# After successful staging validation
kubectl apply -k k8s/overlays/production
```

## Environment Differences

**Staging:**
- Namespace: `staging`
- Database: Separate staging Cloud SQL instance
- Resources: Reduced (0.5 CPU, 1Gi memory)
- Cron schedule: Manual only (no automatic runs)
- Images: Can use `:latest` for rapid testing

**Production:**
- Namespace: `production`
- Database: Production Cloud SQL instance
- Resources: Full (2 CPU, 4Gi memory)
- Cron schedule: Every 6 hours
- Images: Immutable commit SHA tags only

## Creating Staging Database

```bash
# 1. Create staging Cloud SQL instance (smaller/cheaper)
gcloud sql instances create mizzou-crawler-staging \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1

# 2. Create staging database
gcloud sql databases create mizzou_staging --instance=mizzou-crawler-staging

# 3. Create staging secrets
kubectl create secret generic cloudsql-db-credentials-staging \
  --from-literal=username=postgres \
  --from-literal=password=<STAGING_PASSWORD> \
  -n staging
```

## Validation Workflow

1. **Develop locally** - Test with local SQLite or Docker PostgreSQL
2. **CI validation** - GitHub Actions validates SQL and workflow syntax
3. **Deploy to staging** - `kubectl apply -k k8s/overlays/staging`
4. **Test in staging** - Run workflows, verify results
5. **Deploy to production** - `kubectl apply -k k8s/overlays/production`

## Benefits

- ✅ Catch SQL errors before production
- ✅ Test workflow changes safely
- ✅ Validate resource limits and scaling
- ✅ Test database migrations in isolation
- ✅ Parallel development without production impact
