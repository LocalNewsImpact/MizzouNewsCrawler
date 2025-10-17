# Database Migrations

This directory contains scripts and tools for managing database migrations.

## Files

- **entrypoint.sh**: Entrypoint script for the migrator Docker image. Runs safety checks and executes Alembic migrations.

## Usage

### Running Migrations in Kubernetes

The recommended way to run migrations is using the dedicated migrator image in Kubernetes:

```bash
# Apply the migration job with correct commit SHA
kubectl apply -f k8s/jobs/run-alembic-migrations.yaml
```

See [docs/MIGRATION_RUNBOOK.md](../../docs/MIGRATION_RUNBOOK.md) for detailed instructions.

### Running Migrations Locally

For local development, you can run migrations directly:

```bash
# From project root
export DATABASE_URL="postgresql://user:pass@localhost:5432/dbname"
alembic upgrade head
```

Or using the entrypoint script:

```bash
export USE_CLOUD_SQL_CONNECTOR="false"
export DATABASE_URL="postgresql://user:pass@localhost:5432/dbname"
./scripts/migrations/entrypoint.sh
```

### Creating New Migrations

```bash
# Create a new migration
alembic revision -m "description of change"

# Auto-generate migration from model changes
alembic revision --autogenerate -m "description of change"
```

## Safety Checks

The entrypoint script performs these safety checks before running migrations:

1. Validates required environment variables are set
2. Checks that `alembic.ini` exists
3. Verifies `alembic/` and `alembic/versions/` directories exist
4. Counts migration files to ensure they're present
5. Shows current database version before migrating
6. Verifies migrations succeeded after completion

## Environment Variables

Required environment variables:

- `USE_CLOUD_SQL_CONNECTOR`: Set to "true" for Cloud SQL, "false" otherwise
- `CLOUD_SQL_INSTANCE`: Instance connection name (required if using Cloud SQL)
- `DATABASE_USER`: Database username
- `DATABASE_PASSWORD`: Database password
- `DATABASE_NAME`: Database name
- `DATABASE_URL`: Full database URL (alternative to individual components)

## Related Documentation

- [Main Migration Runbook](../../docs/MIGRATION_RUNBOOK.md)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
