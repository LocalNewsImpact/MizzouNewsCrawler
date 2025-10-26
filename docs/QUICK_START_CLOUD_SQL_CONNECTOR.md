# Quick Start: Cloud SQL Connector

Quick reference for using the Cloud SQL Python Connector instead of proxy sidecars.

## For Local Development

**Default behavior (no changes needed):**
```bash
# Uses SQLite by default - connector is disabled
export DATABASE_URL=sqlite:///data/mizzou.db
python -m src.cli.main status
```

## For Kubernetes Deployment

**Already configured!** The manifests are updated:

### API Deployment
```yaml
env:
- name: USE_CLOUD_SQL_CONNECTOR
  value: "true"
- name: CLOUD_SQL_INSTANCE
  value: "mizzou-news-crawler:us-central1:mizzou-db-prod"
- name: DATABASE_USER
  valueFrom:
    secretKeyRef:
      name: cloudsql-db-credentials
      key: username
# ... other credentials
```

No sidecar containers needed! ✅

## Deployment Commands

```bash
# 1. Build and push updated Docker images
docker build -f Dockerfile.api -t api:latest .
docker push us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:latest

# 2. Apply updated manifests
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/crawler-cronjob.yaml
kubectl apply -f k8s/processor-cronjob.yaml

# 3. Verify pods are running
kubectl get pods -n production

# 4. Test job completion
kubectl create job --from=cronjob/mizzou-crawler test-$(date +%s) -n production
kubectl get jobs -n production -w  # Should show "Complete"
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `USE_CLOUD_SQL_CONNECTOR` | No | `false` | Enable Cloud SQL connector |
| `CLOUD_SQL_INSTANCE` | Yes (if enabled) | - | Format: `project:region:instance` |
| `DATABASE_USER` | Yes | - | Database username |
| `DATABASE_PASSWORD` | Yes | - | Database password |
| `DATABASE_NAME` | Yes | - | Database name |

## Benefits

✅ **Jobs complete automatically** - No more hanging jobs  
✅ **Resource savings** - ~89-445Mi memory, ~75-125m CPU per pod  
✅ **Simpler config** - No sidecar containers  
✅ **Production-grade** - Google-recommended approach  

## Troubleshooting

**Import error?**
```bash
pip install cloud-sql-python-connector[pg8000]
```

**Connection refused?**
- Check instance name format: `project:region:instance`
- Verify credentials in secret
- Ensure Cloud SQL Admin API enabled

**Jobs still hanging?**
- Verify `USE_CLOUD_SQL_CONNECTOR=true` in pod env
- Check Docker images are rebuilt with new dependency
- Review pod logs: `kubectl logs <pod-name>`

## Full Documentation

See [`CLOUD_SQL_CONNECTOR_MIGRATION.md`](./CLOUD_SQL_CONNECTOR_MIGRATION.md) for complete migration guide.
