# Work Queue Service

## Overview

The Work Queue Service is a centralized coordination service for domain-aware article extraction. It solves the throughput degradation issue where multiple parallel extraction pods were achieving only 12.5 articles/hour (versus expected 120+) due to uncoordinated domain access patterns.

## Problem Statement

### Before Work Queue

- **Uncoordinated Access**: 6 extraction pods using `ORDER BY RANDOM()` caused overlapping domain access
- **Rate Limit Amplification**: Multiple pods hitting same domains concurrently triggered rate limits 6× faster
- **Excessive Domain Blocking**: 75% of domains became paused/blocked (4,867 of 6,461 candidate links)
- **Low Throughput**: Only 12.5 articles/hour with 6 pods vs. 20 articles/hour with 1 pod

### Root Cause

`FOR UPDATE SKIP LOCKED` prevents duplicate article processing but does NOT coordinate domain access. Workers could still hammer the same domains simultaneously.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Work Queue Service                        │
│  (Single long-running pod, FastAPI + PostgreSQL)            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ Domain State Manager                               │    │
│  │ - Tracks worker → domain assignments              │    │
│  │ - Enforces per-domain rate limits                 │    │
│  │ - Cooldown periods (60s between requests/domain)  │    │
│  │ - Failure tracking & extended pauses              │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ Worker Coordination                                │    │
│  │ - Assigns 3-5 exclusive domains per worker        │    │
│  │ - Rebalances on worker timeout (10 min)          │    │
│  │ - Sticky assignments (workers keep domains)      │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │ HTTP API
         ┌────────────────┼────────────────┐
         │                │                │
    ┌────▼────┐      ┌────▼────┐     ┌────▼────┐
    │ Worker 1│      │ Worker 2│ ... │ Worker 6│
    │ Domains:│      │ Domains:│     │ Domains:│
    │  A,B,C  │      │  D,E,F  │     │  G,H,I  │
    └─────────┘      └─────────┘     └─────────┘
```

## Features

### 1. Domain Partitioning
- Each worker gets 3-5 exclusive domains
- Sticky assignments (workers keep domains across requests)
- No domain assigned to multiple workers simultaneously

### 2. Rate Limiting
- 60-second cooldown between requests to same domain (configurable)
- Prevents rapid-fire access to news sites
- Respects rate limits even across worker restarts

### 3. Failure Handling
- Progressive cooldown: 60s → 120s → 30-min pause
- After 3 failures, domain paused for 30 minutes
- Automatic recovery when pause expires

### 4. Worker Management
- Worker timeout: Reclaim domains from workers inactive for 10+ minutes
- Automatic rebalancing of domains
- Graceful handling of worker crashes

### 5. Thread Safety
- All state protected by locks
- Safe for concurrent requests from multiple workers

## API Endpoints

### POST /work/request
Request work items from the queue.

**Request:**
```json
{
  "worker_id": "extraction-step-1096287420",
  "batch_size": 50,
  "max_articles_per_domain": 3
}
```

**Response:**
```json
{
  "items": [
    {
      "id": "uuid",
      "url": "https://example.com/article",
      "source": "example.com",
      "canonical_name": "Example News"
    }
  ],
  "worker_domains": ["example.com", "another.com"]
}
```

### POST /work/report-failure
Report a domain failure (rate limit, bot protection, etc.).

**Parameters:**
- `worker_id`: Worker reporting the failure
- `domain`: Domain that failed

**Response:**
```json
{
  "status": "success",
  "message": "Failure reported for example.com"
}
```

### GET /stats
Get current queue statistics.

**Response:**
```json
{
  "total_available": 1594,
  "total_paused": 0,
  "domains_available": 50,
  "domains_paused": 0,
  "worker_assignments": {
    "worker-1": ["domain1.com", "domain2.com"],
    "worker-2": ["domain3.com", "domain4.com"]
  },
  "domain_cooldowns": {
    "domain1.com": 45.2
  }
}
```

### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "work-queue"
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | HTTP port for the service |
| `DOMAIN_COOLDOWN_SECONDS` | `60` | Cooldown between requests to same domain |
| `MAX_DOMAIN_FAILURES` | `3` | Failures before 30-minute pause |
| `DOMAIN_PAUSE_SECONDS` | `1800` | Pause duration after max failures (30 min) |
| `WORKER_TIMEOUT_SECONDS` | `600` | Worker inactive timeout (10 min) |
| `MIN_DOMAINS_PER_WORKER` | `3` | Minimum domains per worker |
| `MAX_DOMAINS_PER_WORKER` | `5` | Maximum domains per worker |

### Database Configuration

The service requires read-only access to:
- `candidate_links` table
- `sources` table
- `articles` table (for checking extracted articles)

Uses the same Cloud SQL configuration as extraction pods.

## Deployment

### Kubernetes

```bash
# Apply deployment
kubectl apply -f k8s/work-queue-deployment.yaml

# Check status
kubectl get pods -n production -l app=work-queue
kubectl logs -n production -l app=work-queue --tail=50

# Test health endpoint
kubectl exec -n production deploy/work-queue -- curl localhost:8080/health

# Check stats
kubectl exec -n production deploy/work-queue -- curl localhost:8080/stats | jq
```

### Enable in Extraction Pods

Set environment variable in extraction step:

```yaml
env:
  - name: USE_WORK_QUEUE
    value: "true"
  - name: WORK_QUEUE_URL
    value: "http://work-queue.production.svc.cluster.local:8080"
```

## Monitoring

### Key Metrics

```bash
# Check worker assignments
curl http://work-queue:8080/stats | jq .worker_assignments

# Check domain cooldowns
curl http://work-queue:8080/stats | jq .domain_cooldowns

# Monitor throughput (articles extracted per hour)
kubectl exec -n production deploy/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT 
            DATE_TRUNC('hour', extracted_at) as hour,
            COUNT(*) as articles
        FROM articles 
        WHERE extracted_at >= NOW() - INTERVAL '2 hours'
        GROUP BY hour
        ORDER BY hour DESC
    ''')).fetchall()
    
    for row in result:
        print(f'{row[0]}: {row[1]} articles')
"
```

### Expected Performance

| Metric | Before | After (Target) |
|--------|--------|----------------|
| Throughput (6 pods) | 12.5/hour | 100+/hour |
| Paused domains | 75% | <10% |
| Domain diversity | Low | High (15+ sources/hour) |

## Fallback Behavior

If work queue service is unavailable:
- Extraction pods automatically fall back to direct database queries
- Uses existing `ORDER BY RANDOM()` logic
- Logs warning but continues processing
- No data loss or extraction failures

## Testing

### Unit Tests
```bash
pytest tests/services/test_work_queue.py -v
```

### Integration Tests (PostgreSQL required)
```bash
export TEST_DATABASE_URL="postgresql://user:pass@localhost/testdb"
pytest tests/integration/test_work_queue_integration.py -v -m integration
```

### Local Testing
```bash
# Start service locally
PORT=8080 DATABASE_URL="postgresql://..." python -m src.services.work_queue

# Test endpoints
curl http://localhost:8080/health
curl http://localhost:8080/stats
curl -X POST http://localhost:8080/work/request \
  -H "Content-Type: application/json" \
  -d '{"worker_id": "test-worker", "batch_size": 10, "max_articles_per_domain": 3}'
```

## Troubleshooting

### Service Not Starting
```bash
# Check logs
kubectl logs -n production deploy/work-queue --tail=100

# Verify database connection
kubectl exec -n production deploy/work-queue -- env | grep DATABASE

# Check Cloud SQL proxy
kubectl logs -n production deploy/work-queue -c cloud-sql-proxy --tail=50
```

### No Work Assigned
```bash
# Check available articles
curl http://work-queue:8080/stats | jq .total_available

# Check domain assignments
curl http://work-queue:8080/stats | jq .worker_assignments

# Check cooldowns
curl http://work-queue:8080/stats | jq .domain_cooldowns
```

### Worker Not Receiving Work
```bash
# Check if worker is active
curl http://work-queue:8080/stats | jq '.worker_assignments["worker-id"]'

# Check if domains are on cooldown
curl http://work-queue:8080/stats | jq .domain_cooldowns

# Check extraction pod logs
kubectl logs -n production -l stage=extraction --tail=50 | grep "work queue"
```

## Security Considerations

- **Read-Only Database Access**: Service only reads from database, never writes
- **No Credentials in Logs**: Database URLs are masked in logs
- **Network Policy**: Service accessible only within cluster (ClusterIP)
- **Health Checks**: Liveness/readiness probes detect unhealthy state
- **Resource Limits**: Memory and CPU limits prevent resource exhaustion

## Future Enhancements

- [ ] Persist worker assignments to database (survive restarts)
- [ ] Add metrics endpoint for Prometheus
- [ ] Implement priority queue (high-priority domains first)
- [ ] Add configurable rate limits per domain
- [ ] Support for burst mode (temporarily increase limits)
- [ ] Dashboard for monitoring domain assignments
