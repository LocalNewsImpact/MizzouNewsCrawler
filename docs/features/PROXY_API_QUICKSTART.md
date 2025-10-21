# Proxy Telemetry API - Quick Start Guide

## Running the Backend API Locally

The backend API must be run from the **project root directory**, not from the `backend/` subdirectory. This is because the code uses absolute imports like `from src.models.database import DatabaseManager`.

### Correct way to start the server:

```bash
# From the project root directory
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts

# Activate virtual environment
source venv/bin/activate

# Start uvicorn (it will automatically find backend/app/main.py)
PYTHONPATH=$PWD uvicorn backend.app.main:app --reload
```

### ❌ Wrong way (will cause import errors):

```bash
# DON'T do this - imports will fail
cd backend
uvicorn app.main:app --reload
# Error: ModuleNotFoundError: No module named 'src.models.database'
```

## Testing the Proxy Telemetry Endpoints

Once the server is running, test the endpoints:

```bash
# Get proxy usage summary (last 7 days)
curl 'http://localhost:8000/telemetry/proxy/summary?days=7'

# Get daily trends (last 30 days)
curl 'http://localhost:8000/telemetry/proxy/trends?days=30'

# Get top domains using proxy
curl 'http://localhost:8000/telemetry/proxy/domains?limit=20'

# Get common proxy errors
curl 'http://localhost:8000/telemetry/proxy/errors?limit=20'

# Get authentication statistics
curl 'http://localhost:8000/telemetry/proxy/authentication?days=7'

# Compare proxy vs direct performance
curl 'http://localhost:8000/telemetry/proxy/comparison?days=7'

# Get proxy status distribution
curl 'http://localhost:8000/telemetry/proxy/status-distribution?days=7'

# Get recent failures (last 24 hours)
curl 'http://localhost:8000/telemetry/proxy/recent-failures?hours=24'

# Analyze bot detection patterns
curl 'http://localhost:8000/telemetry/proxy/bot-detection?days=7'
```

**Note for zsh users:** Always quote URLs with query parameters (the `?` character) to prevent zsh glob expansion errors.

## API Documentation

Once the server is running, visit:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

These provide interactive API documentation where you can test endpoints directly in your browser.

## Common Issues

### Issue: `ModuleNotFoundError: No module named 'backend.app.database'`
**Solution:** The proxy.py file has been fixed to use `DatabaseManager` from `src.models.database` instead. Make sure you have the latest code (commit 3f19a63 or later).

### Issue: `unable to open database file`
**Solution:** Run uvicorn from the project root directory, not from `/backend`. The database path is relative to the project root.

### Issue: Empty response or no data
**Solution:** The endpoints require actual telemetry data in the `extraction_telemetry_v2` table. Run some crawls first to populate the database with proxy metrics.

## Database Schema

The proxy telemetry endpoints query these columns in `extraction_telemetry_v2`:

- `proxy_used` (BOOLEAN) - Whether proxy was enabled
- `proxy_url` (TEXT) - Proxy URL (without credentials)
- `proxy_authenticated` (BOOLEAN) - Whether credentials were provided  
- `proxy_status` (TEXT) - "success", "failed", "bypassed", or "disabled"
- `proxy_error` (TEXT) - Error message if proxy failed

These columns are automatically added by the telemetry system's auto-migration code when you first run a crawl after deploying this update.

## Production Deployment

In production (GKE), the processor service will:

1. Automatically run database migrations on startup
2. Start collecting proxy telemetry data
3. Make API endpoints available at `/telemetry/proxy/*`

No manual database changes are required - the migration is automatic!
