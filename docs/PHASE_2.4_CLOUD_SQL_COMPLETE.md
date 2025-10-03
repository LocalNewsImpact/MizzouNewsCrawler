# Phase 2.4 Complete: Cloud SQL PostgreSQL Database

**Status**: ✅ **COMPLETE**  
**Date**: October 3, 2025  
**Duration**: ~10 minutes

## Summary

Successfully created Cloud SQL PostgreSQL 16 instance with database, user, and stored all credentials securely in GCP Secret Manager.

## Cloud SQL Instance Details

### Instance Configuration

- **Instance Name**: `mizzou-db-prod`
- **Status**: RUNNABLE ✅
- **Database Version**: PostgreSQL 16
- **Location**: us-central1-c
- **Tier**: db-f1-micro (614MB RAM, shared-core)
- **Storage**: 10GB HDD
- **Edition**: ENTERPRISE (cost-optimized)
- **Availability**: Zonal (single zone)
- **Backup**: Disabled (development tier)

### Network Configuration

- **Public IP Address**: `34.61.162.107`
- **Private IP**: Not configured (using public IP for now)
- **Connection Name**: `mizzou-news-crawler:us-central1:mizzou-db-prod`

### Cost Estimate

- **Instance**: ~$7-15/month (db-f1-micro)
- **Storage**: ~$0.17/GB/month × 10GB = ~$1.70/month
- **Network egress**: Variable (typically minimal for GKE same-region)
- **Total estimated**: ~$8-17/month

## Database Configuration

### Database

- **Name**: `mizzou`
- **Instance**: `mizzou-db-prod`
- **Project**: `mizzou-news-crawler`
- **Character Set**: UTF8 (default)
- **Collation**: en_US.UTF8 (default)

### User

- **Username**: `mizzou_user`
- **Password**: Stored in Secret Manager (see below)
- **Permissions**: Full access to `mizzou` database

## Secrets in Secret Manager

All sensitive credentials stored securely in GCP Secret Manager:

### 1. Database Password

- **Secret Name**: `db-password`
- **Version**: 1
- **Access Command**:

  ```bash
  gcloud secrets versions access latest --secret=db-password
  ```

### 2. Database Connection String

- **Secret Name**: `db-connection-string`
- **Version**: 1
- **Format**: `postgresql://mizzou_user:PASSWORD@34.61.162.107:5432/mizzou`
- **Access Command**:

  ```bash
  gcloud secrets versions access latest --secret=db-connection-string
  ```

### 3. Cloud SQL Connection Name

- **Secret Name**: `db-instance-connection-name`
- **Version**: 1
- **Value**: `mizzou-news-crawler:us-central1:mizzou-db-prod`
- **Access Command**:

  ```bash
  gcloud secrets versions access latest --secret=db-instance-connection-name
  ```

## Connection Methods

### Method 1: Direct Connection (Public IP)

For local development or testing:

```bash
# Get the password from Secret Manager
DB_PASSWORD=$(gcloud secrets versions access latest --secret=db-password)

# Connect using psql
psql "postgresql://mizzou_user:${DB_PASSWORD}@34.61.162.107:5432/mizzou"

# Or using environment variable
export DATABASE_URL=$(gcloud secrets versions access latest --secret=db-connection-string)
```

### Method 2: Cloud SQL Proxy (Recommended for Production)

For secure connections from GKE or local development:

```bash
# Get connection name
CONNECTION_NAME=$(gcloud secrets versions access latest --secret=db-instance-connection-name)

# Install Cloud SQL Proxy (if not already installed)
# wget https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy
# chmod +x cloud_sql_proxy

# Start proxy (local development)
./cloud_sql_proxy -instances=${CONNECTION_NAME}=tcp:5432

# Connect through proxy
psql "postgresql://mizzou_user:PASSWORD@localhost:5432/mizzou"
```

### Method 3: From Kubernetes (Cloud SQL Proxy Sidecar)

In Kubernetes deployment, use Cloud SQL Proxy as a sidecar container:

```yaml
spec:
  containers:
  - name: api
    image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:latest
    env:
    - name: DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: cloudsql-db-credentials
          key: password
    - name: DATABASE_URL
      value: "postgresql://mizzou_user:$(DB_PASSWORD)@127.0.0.1:5432/mizzou"
  
  - name: cloud-sql-proxy
    image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.8.0
    args:
      - "--structured-logs"
      - "--port=5432"
      - "mizzou-news-crawler:us-central1:mizzou-db-prod"
    securityContext:
      runAsNonRoot: true
```

## Verification Commands

### Check Instance Status

```bash
gcloud sql instances describe mizzou-db-prod
```

### List Databases

```bash
gcloud sql databases list --instance=mizzou-db-prod
```

### List Users

```bash
gcloud sql users list --instance=mizzou-db-prod
```

### Test Connection

```bash
# Get password
DB_PASSWORD=$(gcloud secrets versions access latest --secret=db-password)

# Test connection
psql "postgresql://mizzou_user:${DB_PASSWORD}@34.61.162.107:5432/mizzou" -c "SELECT version();"
```

### List Secrets

```bash
gcloud secrets list
```

## Security Considerations

### Current Setup

✅ **Implemented**:

- Password stored in Secret Manager (not in code)
- Secure 32-character password generated with openssl
- Connection string stored in Secret Manager
- Database user with limited scope (not superuser)

⚠️ **Not Yet Implemented** (Phase 2.5/2.6):

- Private IP configuration (using public IP currently)
- VPC peering with GKE cluster
- SSL/TLS enforcement
- IP whitelisting
- Automated backups
- High availability (single zone only)

### Recommended Next Steps for Production

1. **Enable Private IP**: Configure VPC peering for secure internal communication
2. **Enable SSL**: Require SSL connections
3. **Enable Backups**: Configure automated backups and point-in-time recovery
4. **IP Whitelist**: Restrict connections to GKE cluster IPs only
5. **Monitoring**: Set up Cloud Monitoring alerts for database metrics

## Database Schema Migration

### Option 1: Import from Local SQLite

If you have existing data in local SQLite database:

```bash
# Export SQLite to SQL dump
sqlite3 data/mizzou.db .dump > mizzou_dump.sql

# Import to Cloud SQL (after connecting)
psql "postgresql://mizzou_user:PASSWORD@34.61.162.107:5432/mizzou" < mizzou_dump.sql
```

### Option 2: Use Cloud SQL Proxy for Migration

```bash
# Start Cloud SQL Proxy
./cloud_sql_proxy -instances=mizzou-news-crawler:us-central1:mizzou-db-prod=tcp:5432 &

# Run migration script
python scripts/migrate_sqlite_to_postgres.py
```

### Option 3: Let Application Create Schema

If using SQLAlchemy or similar ORM, tables will be created automatically on first run.

## Cost Optimization Tips

1. **Storage**: Start with 10GB, increase only as needed
2. **Tier**: db-f1-micro is sufficient for development/testing
3. **Backups**: Disabled for development, enable for production
4. **High Availability**: Not needed for development tier
5. **Maintenance Window**: Use default to avoid manual scheduling costs

## Next Steps: Phase 2.5 - GKE Cluster Creation

Now that Cloud SQL is ready, proceed to Phase 2.5:

1. **Create GKE Cluster** (`mizzou-cluster`)
   - Cluster type: Standard (not Autopilot for cost control)
   - Machine type: e2-small (2 vCPUs, 2GB RAM, ~$30-50/month)
   - Node count: 1 (autoscaling 1-3)
   - Region: us-central1 (same as Cloud SQL)
   - Workload Identity: Enabled (for Secret Manager access)

2. **Configure kubectl** for cluster access

3. **Create Kubernetes namespace** (`production`)

4. **Prepare for deployment** in Phase 2.6:
   - Create Kubernetes Secrets from GCP Secret Manager
   - Deploy API service with Cloud SQL Proxy sidecar
   - Deploy Crawler and Processor as CronJobs
   - Configure Ingress for external access

See `docs/PHASE_2_IMPLEMENTATION.md` for detailed GKE setup instructions.

## Environment Variables

Update `~/.mizzou-gcp-env` with database details:

```bash
# Add these to ~/.mizzou-gcp-env
export DB_INSTANCE_NAME="mizzou-db-prod"
export DB_NAME="mizzou"
export DB_USER="mizzou_user"
export DB_PUBLIC_IP="34.61.162.107"
export DB_CONNECTION_NAME="mizzou-news-crawler:us-central1:mizzou-db-prod"
```

## Troubleshooting

### Cannot Connect to Database

1. Check instance status: `gcloud sql instances describe mizzou-db-prod`
2. Verify firewall rules allow your IP
3. Check credentials: `gcloud secrets versions access latest --secret=db-password`
4. Try Cloud SQL Proxy instead of direct connection

### "Connection Refused" Error

- Instance may still be starting (wait 1-2 minutes)
- Public IP may be disabled (check instance configuration)
- Firewall rules may block connection

### "Authentication Failed" Error

- Verify username and password
- Check if user exists: `gcloud sql users list --instance=mizzou-db-prod`
- Password may contain special characters (use single quotes in connection string)

## Phase 2 Progress

- ✅ Phase 2.1: Prerequisites Installation (gcloud CLI, kubectl)
- ✅ Phase 2.2: GCP Project Setup (project created, billing linked, APIs enabled)
- ✅ Phase 2.3: Artifact Registry & Docker Images (all images pushed)
- ✅ **Phase 2.4: Cloud SQL PostgreSQL Setup** ← **YOU ARE HERE**
- ⏳ Phase 2.5: GKE Cluster Creation
- ⏳ Phase 2.6: Kubernetes Deployment
- ⏳ Phase 2.7: Domain & SSL Configuration

---

**Phase 2.4 Status**: ✅ **COMPLETE** - Cloud SQL PostgreSQL database ready for application deployment.
