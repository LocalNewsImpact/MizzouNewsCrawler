FastAPI backend scaffold for MizzouNewsCrawler reviewer UI

Usage (development):

1. Create a Python virtualenv and install requirements:
   python -m venv .venv
   source .venv/bin/activate
   pip install -r backend/requirements.txt

2. Start the server:
   uvicorn backend.app.main:app --reload --port 8000

The server will expose endpoints under /api/* and a tiny static UI is provided at /web/index.html

DB: an SQLite DB will be created at backend/reviews.db by the app on first run.

## Lifecycle Management

The backend uses centralized lifecycle management for shared resources (database, telemetry, HTTP sessions). This ensures:

- Proper initialization on startup
- Graceful cleanup on shutdown
- Easy dependency injection in route handlers
- Testable components

See [docs/LIFECYCLE_MANAGEMENT.md](../docs/LIFECYCLE_MANAGEMENT.md) for detailed documentation on:
- How to use dependency injection in route handlers
- How to override dependencies in tests
- Configuration options
- Migration guide for existing code

### Health Checks

- `GET /health` - Basic health check (always returns 200 OK)
- `GET /ready` - Readiness check (returns 503 if resources unavailable)

Cloud deployment notes
----------------------

Recommended: deploy the backend to Google Cloud Run and host the frontend as a static site
in a Google Cloud Storage bucket (served via a load balancer or directly with public access).

Set the environment variable `ALLOWED_ORIGINS` on the Cloud Run service to the frontend origin(s)
for example: `https://storage.googleapis.com/bucket-name` or your custom domain. For local
development you can set `ALLOWED_ORIGINS='*'`.

Example Cloud Run env var (gcloud):

   gcloud run deploy mizzou-backend \
      --image gcr.io/PROJECT_ID/mizzou-backend \
      --set-env-vars "ALLOWED_ORIGINS=https://your-frontend-host.example.com" \
      --region=us-central1

Security note: allow_origins='*' is acceptable for local development only. For production use a
restricted list of origins.
