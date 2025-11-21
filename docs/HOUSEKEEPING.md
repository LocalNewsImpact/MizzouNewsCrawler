# Pipeline Housekeeping

Daily maintenance command that checks for records stuck in various pipeline states and decides whether to expire/pause them. This helps prevent accumulation of stale data and ensures pipeline health.

## Overview

The housekeeping command runs daily (by default at 2 AM UTC via Kubernetes CronJob) and performs five checks:

1. **NULL text articles** - Articles with empty content that can't be processed
2. **Expired candidates** - Candidates waiting for extraction beyond a threshold
3. **Stuck extraction** - Articles not advancing from `extracted` status
4. **Stuck cleaning** - Articles not advancing from `cleaned` status  
5. **Stuck verification** - Candidates not advancing from `verified` status

## Usage

### Local Development

```bash
# Quick preview (dry-run mode)
python -m src.cli.cli_modular housekeeping --dry-run

# With detailed output
python -m src.cli.cli_modular housekeeping --dry-run --verbose

# Actually run housekeeping
python -m src.cli.cli_modular housekeeping

# Custom thresholds
python -m src.cli.cli_modular housekeeping \
  --candidate-expiration-days 10 \
  --extraction-stall-hours 48 \
  --verbose
```

### Production (Kubernetes)

Deployed as a CronJob in the `production` namespace:

```bash
# Check schedule
kubectl get cronjob mizzou-housekeeping -n production

# View recent runs
kubectl get jobs -n production | grep housekeeping

# View logs from last run
kubectl logs -n production -l app=mizzou-housekeeping --tail=100

# Manually trigger housekeeping
kubectl create job --from=cronjob/mizzou-housekeeping mizzou-housekeeping-manual-$(date +%s) -n production

# View job status
kubectl describe job mizzou-housekeeping-manual-1234567890 -n production
```

## Command Options

| Option | Default | Description |
|--------|---------|-------------|
| `--candidate-expiration-days` | 7 | Mark candidates older than N days as paused (if still in `article` status) |
| `--extraction-stall-hours` | 24 | Warn about articles stuck in `extracted` for N+ hours |
| `--cleaning-stall-hours` | 24 | Warn about articles stuck in `cleaned` for N+ hours |
| `--verification-stall-hours` | 24 | Warn about candidates stuck in `verified` for N+ hours |
| `--dry-run` | False | Show what would happen without making changes |
| `--verbose` | False | Show detailed breakdown by source for actions taken |

## Actions Taken

### 1. NULL Text Articles

**Condition**: Articles in `extracted` status where `text IS NULL`

**Action**: Mark as `paused` with telemetry `pause_reason: "null_text"`

**Why**: These articles failed content extraction (paywalls, e-editions, JavaScript-rendered pages) and cannot proceed to cleaning. Marking them allows analytics to track extraction failures by reason.

**Example**:
```
1️⃣  Checking for articles with NULL text...

   Found 5 articles with NULL text in 'extracted' status
   - AP News (15d): https://apnews.com/article/...
   - NPR (12d): https://npr.org/sections/...
   
   ✅ Marked 5 articles as paused
```

### 2. Expired Candidates

**Condition**: Candidates in `article` status older than threshold (default 7 days)

**Action**: Mark as `paused` (removes from extraction queue)

**Why**: These candidates have been waiting for extraction for too long. They likely hit transient failures or domain rate limiting and are unlikely to succeed. Marking them clears the queue and prevents stale data accumulation.

**Example**:
```
2️⃣  Checking for expired candidates (older than 7 days)...

   Found 128 candidates older than 7 days
   - KPLR11/Fox 2 Now: 45 (oldest 28d)
   - KSN/KODE TV: 32 (oldest 25d)
   - The Missouri Independent: 20 (oldest 22d)
   
   ✅ Marked 128 candidates as paused
```

### 3. Stuck Extraction (Warning Only)

**Condition**: Articles in `extracted` status for 24+ hours

**Action**: Print warning (no automatic action)

**Why**: This indicates a bottleneck in the cleaning pipeline. Manual investigation may be needed to determine why articles aren't advancing.

**Example**:
```
3️⃣  Checking for articles stuck in extraction (24h+)...

   ⚠️  Found 15 articles stuck in 'extracted' status
   - AP News (48h): https://apnews.com/article/...
   - Reuters (42h): https://reuters.com/...
   
   → This usually indicates a cleaning pipeline bottleneck
```

### 4. Stuck Cleaning (Warning Only)

**Condition**: Articles in `cleaned` status for 24+ hours

**Action**: Print warning (no automatic action)

**Why**: This indicates a bottleneck in the labeling/downstream pipeline.

### 5. Stuck Verification (Warning Only)

**Condition**: Candidates in `verified` status for 24+ hours without fetching

**Action**: Print warning (no automatic action)

**Why**: This indicates a bottleneck in the extraction queue management.

## Pipeline States

Articles flow through these states:

```
discovered → verified → article → extracted → cleaned → local → labeled
                                                          ↓
                                                      (labeling)
```

Candidates flow through these states:

```
new → discovered → verified → article → (extraction) → (article extracted)
                         ↓
                   (archived/paused)
```

**Paused** state is a terminal state for records that won't be processed further (expired, null content, intentionally archived, etc.).

## Examples

### Production Housekeeping Preview

Check what housekeeping would do without making changes:

```bash
kubectl exec -n production $(kubectl get pods -n production -l app=mizzou-processor -o jsonpath='{.items[0].metadata.name}') -- \
  python -m src.cli.cli_modular housekeeping --dry-run --verbose
```

### Run with Shorter Candidate Expiration

Mark candidates as paused after 3 days instead of 7:

```bash
python -m src.cli.cli_modular housekeeping \
  --candidate-expiration-days 3 \
  --verbose
```

### Run with Longer Stall Thresholds

Only warn about articles stuck for 48+ hours:

```bash
python -m src.cli.cli_modular housekeeping \
  --extraction-stall-hours 48 \
  --cleaning-stall-hours 48 \
  --verbose
```

## Kubernetes Deployment

The housekeeping CronJob runs daily at **2 AM UTC** (off-peak):

```yaml
# From k8s/housekeeping-cronjob.yaml
spec:
  schedule: "0 2 * * *"  # 2 AM UTC daily
  concurrencyPolicy: Forbid  # Don't overlap runs
  successfulJobsHistoryLimit: 5  # Keep last 5 successful runs
  failedJobsHistoryLimit: 5      # Keep last 5 failed runs
```

### Resource Allocation

```yaml
resources:
  requests:
    cpu: 100m
    memory: 512Mi
  limits:
    cpu: 500m
    memory: 1Gi
```

Low resource requirements since this is off-peak, non-critical maintenance work.

### Monitoring

Monitor housekeeping runs via:

```bash
# All housekeeping jobs
kubectl get jobs -n production -l app=mizzou-housekeeping

# Latest run details
kubectl describe job -n production $(kubectl get jobs -n production -l app=mizzou-housekeeping -o jsonpath='{.items[0].metadata.name}')

# Logs
kubectl logs -n production -l app=mizzou-housekeeping --tail=200
```

## Troubleshooting

### Housekeeping not running

Check CronJob status:
```bash
kubectl get cronjob mizzou-housekeeping -n production
kubectl describe cronjob mizzou-housekeeping -n production
```

### No actions taken but articles appear stuck

Housekeeping runs at 2 AM UTC. To run immediately:

```bash
kubectl create job --from=cronjob/mizzou-housekeeping \
  mizzou-housekeeping-manual-$(date +%s) -n production
```

### Paused records should not have been paused

The action is based on database state at runtime. If records should not be paused:

1. Update record status in database: `UPDATE articles SET status = 'extracted' WHERE id = '...'`
2. Review why records were in that state (NULL text, old age, etc.)
3. Consider adjusting thresholds if needed

## Future Enhancements

- [ ] Add database telemetry for pause_reason to candidate_links
- [ ] Add configurable actions (auto-delete old paused records)
- [ ] Integrate with alerting system for stuck records
- [ ] Add metrics export for pipeline health monitoring
- [ ] Add reconciliation commands to fix common issues (e.g., retry expired candidates)
