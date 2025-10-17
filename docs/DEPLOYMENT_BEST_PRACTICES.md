# Deployment Best Practices

This document outlines best practices for deploying the MizzouNewsCrawler application, with a focus on database migrations and container image management.

## Container Image Tagging

### Use Immutable Tags

**Always use immutable tags (commit SHA or semantic version) in production.**

❌ **BAD - Don't do this:**
```yaml
image: us-central1-docker.pkg.dev/project/repo/processor:latest
```

✅ **GOOD - Do this:**
```yaml
image: us-central1-docker.pkg.dev/project/repo/processor:abc123def
```

or
```yaml
image: us-central1-docker.pkg.dev/project/repo/processor:v1.2.3
```

### Why Avoid :latest?

1. **Non-deterministic deployments**: `:latest` can point to different images over time
2. **Difficult rollbacks**: Can't easily revert to a specific version
3. **Hard to debug**: Can't determine what code is running
4. **Cache issues**: Kubernetes may not pull the latest version if already cached
5. **No audit trail**: Can't correlate deployments with code changes

### Tagging Strategy

Our CI/CD pipeline automatically creates multiple tags:

```bash
# Built by Cloud Build
processor:abc123def     # Commit SHA (immutable, recommended)
processor:7a75979       # Short commit SHA
processor:v1.2.3        # Semantic version
processor:latest        # Latest (use only for development)
```

For production deployments, always use the commit SHA tag:

```bash
kubectl set image deployment/processor \
  processor=us-central1-docker.pkg.dev/project/repo/processor:abc123def
```

## Database Migration Workflow

### Pre-Deployment Checklist

Before running migrations in production:

1. ✅ Migrations tested in staging environment
2. ✅ Database backup completed
3. ✅ Rollback plan documented
4. ✅ Team notified of deployment window
5. ✅ Monitoring and alerts configured

### Migration Execution Order

**Correct order:**

1. Run database migrations
2. Wait for migrations to complete successfully
3. Deploy application code
4. Verify application health

**Why this order?**

- Ensures database schema is ready before new code runs
- Prevents application errors due to missing columns/tables
- Allows for safer rollbacks

### Using the Migrator Image

The dedicated migrator image provides:

- Consistent migration environment
- Built-in safety checks
- Automated validation
- Minimal dependencies

```bash
# Get latest migrator commit SHA
gcloud artifacts docker tags list \
  us-central1-docker.pkg.dev/project/repo/migrator

# Apply migration job
./scripts/apply-migration-job.sh \
  --sha abc123def \
  --namespace production \
  --job-type smoke-test
```

See [MIGRATION_RUNBOOK.md](MIGRATION_RUNBOOK.md) for detailed instructions.

## Secret Management

### Declarative Secret Setup

Secrets should be set up declaratively before deployments:

```bash
# Set up database credentials
./scripts/setup-namespace-secrets.sh \
  --namespace production \
  --instance "project:region:instance" \
  --user "dbuser" \
  --password "dbpass" \
  --database "dbname"
```

### Consistent Secret Keys

Always use these standard keys for database secrets:

- `instance-connection-name`
- `username`
- `password`
- `database`

This ensures compatibility across all services and jobs.

### Never Commit Secrets

- Don't commit secrets to source control
- Use environment variables or secret managers
- Rotate credentials regularly
- Use least-privilege access

## CI/CD Integration

### GitHub Actions Workflow

Migrations can be triggered via GitHub Actions:

1. Go to Actions → "Database Migrations"
2. Click "Run workflow"
3. Select environment (staging/production)
4. For production, manual approval is required
5. Workflow validates image, runs migrations, and performs smoke tests

### Cloud Build Integration

Migrator images are built automatically on push to main:

```yaml
# trigger-migrator.yaml defines when to build
includedFiles:
  - Dockerfile.migrator
  - alembic/**
  - scripts/migrations/**
```

## Deployment Safety

### Pre-Deployment Validation

Before deploying to production:

```bash
# 1. Check staging deployment health
kubectl get pods -n staging

# 2. Verify migrations in staging
kubectl logs -n staging -l job-name=alembic-migration-* --tail=100

# 3. Run smoke tests
kubectl run smoke-test -n staging --rm -i --restart=Never \
  --image=migrator:abc123def \
  -- python3 /app/scripts/smoke_test_migrations.py
```

### Progressive Rollout

For application deployments:

1. Deploy to staging first
2. Run integration tests
3. Monitor for errors/alerts
4. Deploy to production with gradual rollout
5. Monitor metrics and rollback if needed

### Rollback Strategy

**Database rollback:**

```bash
# Check current version
alembic current

# Rollback one revision
alembic downgrade -1

# Rollback to specific version
alembic downgrade <revision_id>
```

**Application rollback:**

```bash
# Rollback deployment to previous version
kubectl rollout undo deployment/processor -n production

# Rollback to specific revision
kubectl rollout undo deployment/processor --to-revision=3 -n production
```

## Monitoring and Alerting

### Key Metrics to Monitor

During and after deployments:

- Application error rate
- Response times
- Database connection pool usage
- Pod restart count
- CPU and memory usage

### Post-Deployment Validation

```bash
# Check pod health
kubectl get pods -n production -l app=processor

# View recent logs
kubectl logs -n production -l app=processor --tail=100 --since=5m

# Check for errors
kubectl logs -n production -l app=processor --tail=500 | grep -i error
```

## Common Pitfalls

### 1. Using :latest in Production

**Problem:** Pod restarts pull different images over time

**Solution:** Always use commit SHA tags

### 2. Deploying Code Before Migrations

**Problem:** Application errors due to missing schema changes

**Solution:** Run migrations first, then deploy code

### 3. Not Testing Migrations in Staging

**Problem:** Unexpected failures in production

**Solution:** Always test in staging first

### 4. Missing Secrets in New Namespaces

**Problem:** Pods fail to start due to missing credentials

**Solution:** Run namespace setup scripts before deployment

### 5. Long-Running Migrations Timing Out

**Problem:** Migration job killed before completion

**Solution:** Increase timeout in job spec, run during low-traffic periods

## Resources

- [Migration Runbook](MIGRATION_RUNBOOK.md)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/configuration/overview/)
- [12-Factor App](https://12factor.net/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
