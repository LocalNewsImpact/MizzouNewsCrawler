# Database Migration Runbook

This document describes how to run database migrations safely for the MizzouNewsCrawler project.

## Overview

Database migrations are managed using Alembic and executed through a dedicated migrator Docker image. This approach ensures:
- Consistent migration environment
- Immutable image tags for reproducibility
- Built-in safety checks
- Automated smoke tests

## Prerequisites

1. Access to the Kubernetes cluster
2. Migrator image built and pushed to Artifact Registry
3. Database credentials configured in the target namespace

## Quick Start

### Option 1: GitHub Actions (Recommended)

Use the automated workflow for running migrations with approval gates:

1. Go to GitHub Actions → "Database Migrations" workflow
2. Click "Run workflow"
3. Select target environment (staging/production)
4. For production, approve the manual gate
5. Monitor the workflow logs

### Option 2: Manual kubectl (Advanced)

For manual execution or troubleshooting:

```bash
# 1. Get the commit SHA of the migrator image
export COMMIT_SHA="abc123def"  # Replace with actual commit SHA

# 2. Create the migration job
kubectl apply -f k8s/jobs/run-alembic-migrations.yaml

# 3. Edit the job to use your commit SHA
kubectl edit job/run-alembic-migrations -n default

# 4. Watch the job status
kubectl get job/run-alembic-migrations -n default -w

# 5. View logs
kubectl logs -l job-name=run-alembic-migrations -n default -f

# 6. Check completion status
kubectl describe job/run-alembic-migrations -n default
```

## Building the Migrator Image

The migrator image should be built as part of CI/CD, but can also be built manually:

```bash
# Submit build to Cloud Build
gcloud builds submit --config=cloudbuild-migrator.yaml

# The build will:
# 1. Build the migrator image
# 2. Validate it contains migration files
# 3. Push to Artifact Registry with commit SHA tag
```

## Running Migrations

### Step 1: Verify Prerequisites

```bash
# Check namespace exists and has correct secrets
kubectl get namespace production

# Verify secret exists with correct keys
kubectl describe secret cloudsql-db-credentials -n production

# Expected keys:
# - instance-connection-name
# - username
# - password
# - database
```

### Step 2: Prepare Migration Job

Replace `<COMMIT_SHA>` in the job manifest with your actual commit SHA:

```bash
# Get latest migrator image tag
gcloud artifacts docker tags list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/migrator \
  --format="value(tag)" \
  --limit=5

# Update the job manifest
sed "s/<COMMIT_SHA>/abc123def/g" \
  k8s/jobs/run-alembic-migrations.yaml \
  > /tmp/migration-job-ready.yaml
```

### Step 3: Apply and Monitor

```bash
# Apply the job
kubectl apply -f /tmp/migration-job-ready.yaml -n production

# Watch for completion (exits when complete or failed)
kubectl wait --for=condition=complete --timeout=600s \
  job/run-alembic-migrations -n production

# View logs
kubectl logs -l job-name=run-alembic-migrations -n production -f
```

### Step 4: Verify Success

```bash
# Check job status
kubectl get job/run-alembic-migrations -n production

# Expected output should show "1/1" completions
# NAME                       COMPLETIONS   DURATION   AGE
# run-alembic-migrations     1/1           45s        2m

# Run smoke tests manually if needed
kubectl run smoke-test --rm -i --restart=Never \
  --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/migrator:abc123def \
  --namespace=production \
  --env="USE_CLOUD_SQL_CONNECTOR=true" \
  --env="CLOUD_SQL_INSTANCE=$(kubectl get secret cloudsql-db-credentials -n production -o jsonpath='{.data.instance-connection-name}' | base64 -d)" \
  --env="DATABASE_USER=$(kubectl get secret cloudsql-db-credentials -n production -o jsonpath='{.data.username}' | base64 -d)" \
  --env="DATABASE_PASSWORD=$(kubectl get secret cloudsql-db-credentials -n production -o jsonpath='{.data.password}' | base64 -d)" \
  --env="DATABASE_NAME=$(kubectl get secret cloudsql-db-credentials -n production -o jsonpath='{.data.database}' | base64 -d)" \
  -- python3 /app/scripts/smoke_test_migrations.py
```

## Using Migration Job with Smoke Tests

For production deployments, use the version with integrated smoke tests:

```bash
# Use the combined job that runs both migration and smoke tests
sed "s/<COMMIT_SHA>/abc123def/g" \
  k8s/jobs/run-alembic-migrations-with-smoke-test.yaml \
  > /tmp/migration-with-test.yaml

kubectl apply -f /tmp/migration-with-test.yaml -n production

# This job runs:
# 1. Init container: Alembic migration
# 2. Main container: Smoke test validation
```

## Rollback Procedure

If a migration fails or causes issues:

```bash
# 1. Check current database version
kubectl run alembic-current --rm -i --restart=Never \
  --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/migrator:abc123def \
  --namespace=production \
  --env="USE_CLOUD_SQL_CONNECTOR=true" \
  --env="CLOUD_SQL_INSTANCE=..." \
  --env="DATABASE_USER=..." \
  --env="DATABASE_PASSWORD=..." \
  --env="DATABASE_NAME=..." \
  --command -- alembic -c /app/alembic.ini current

# 2. Downgrade to previous version
# Create a downgrade job (copy migration job and change command)
cat > /tmp/downgrade-job.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: alembic-downgrade
  namespace: production
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: alembic-downgrade
          image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/migrator:abc123def
          command: ["/bin/sh", "-c"]
          args:
            - |
              cd /app
              # Downgrade one revision
              alembic -c alembic.ini downgrade -1
          env:
            # ... same env vars as migration job
EOF

kubectl apply -f /tmp/downgrade-job.yaml
```

## Troubleshooting

### Migration Job Fails

```bash
# Get detailed job status
kubectl describe job/run-alembic-migrations -n production

# Get pod logs (including failed pods)
kubectl logs -l job-name=run-alembic-migrations -n production --all-containers --prefix

# Check pod events
kubectl get events -n production --sort-by='.lastTimestamp' | grep migration
```

### Secret Not Found

```bash
# Recreate secret using setup script
./scripts/setup-namespace-secrets.sh \
  --namespace production \
  --instance "project:region:instance" \
  --user "dbuser" \
  --password "dbpass" \
  --database "dbname"
```

### Image Not Found

```bash
# Check if image exists
gcloud artifacts docker images describe \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/migrator:abc123def

# If missing, rebuild
gcloud builds submit --config=cloudbuild-migrator.yaml
```

### Database Connection Issues

```bash
# Test database connectivity from a pod
kubectl run db-test --rm -i --restart=Never \
  --image=postgres:15 \
  --namespace=production \
  --env="PGHOST=/cloudsql/your-instance" \
  --env="PGUSER=..." \
  --env="PGPASSWORD=..." \
  --env="PGDATABASE=..." \
  -- psql -c "SELECT 1"
```

## Best Practices

1. **Always use immutable tags**: Never use `:latest` in production
2. **Test in staging first**: Run migrations in staging before production
3. **Backup before migrations**: Take a database snapshot before major migrations
4. **Monitor during rollout**: Watch application pods during deployment
5. **Keep jobs for inspection**: Jobs auto-delete after 24 hours (configurable)
6. **Use smoke tests**: Run validation after migrations complete

## CI/CD Integration

Migrations are integrated into the deployment pipeline:

1. Pull request triggers CI tests including migration tests
2. Merge to main builds migrator image with commit SHA
3. GitHub Actions workflow allows manual migration execution
4. Production migrations require manual approval gate
5. Smoke tests run automatically after migrations

## Related Documentation

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Cloud SQL Connector](https://cloud.google.com/sql/docs/postgres/connect-instance-kubernetes)
- [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
