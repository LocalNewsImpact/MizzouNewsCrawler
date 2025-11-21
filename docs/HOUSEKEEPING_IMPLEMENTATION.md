# Daily Housekeeping Implementation Summary

## Overview

Implemented a comprehensive daily housekeeping system for the Mizzou News Crawler pipeline. This automated maintenance task runs daily (2 AM UTC) to check for stuck records and expired candidates, preventing pipeline accumulation.

## Files Created/Modified

### New Files

1. **`src/cli/commands/housekeeping.py`** (520 lines)
   - Main housekeeping command implementation
   - Five checks for pipeline health:
     1. NULL text articles in `extracted` status → pauses with telemetry
     2. Expired candidates in `article` status → pauses after threshold
     3. Articles stuck in `extracted` → warns about extraction bottleneck
     4. Articles stuck in `cleaned` → warns about labeling bottleneck
     5. Candidates stuck in `verified` → warns about extraction queue bottleneck
   - Supports dry-run mode for safe testing
   - Verbose output for detailed breakdown by source
   - Configurable thresholds for all checks

2. **`k8s/housekeeping-cronjob.yaml`** (74 lines)
   - Kubernetes CronJob manifest
   - Runs daily at 2 AM UTC (off-peak)
   - Uses processor image with Cloud SQL connector
   - Low resource allocation (100m CPU, 512Mi memory)
   - 5-run history limit for both success and failure

3. **`docs/HOUSEKEEPING.md`** (comprehensive documentation)
   - Complete usage guide
   - Production deployment instructions
   - Troubleshooting guide
   - Command options reference table
   - Examples for local development and Kubernetes
   - Future enhancement suggestions

### Modified Files

1. **`src/cli/cli_modular.py`**
   - Added handler: `"housekeeping": "handle_housekeeping_command"` (line 33)
   - Added module mapping: `"housekeeping": "housekeeping"` (line 108)
   - Now discoverable via CLI dispatcher with lazy loading

## Features

### Pipeline Health Checks

| Check | Threshold | Action |
|-------|-----------|--------|
| NULL text articles | N/A (any) | Mark paused with `pause_reason: "null_text"` |
| Expired candidates | 7 days | Mark paused (removes from queue) |
| Stuck extraction | 24 hours | Warn only (indicates cleaning bottleneck) |
| Stuck cleaning | 24 hours | Warn only (indicates labeling bottleneck) |
| Stuck verification | 24 hours | Warn only (indicates queue bottleneck) |

### Configuration Options

All thresholds are customizable via command-line arguments:

```bash
python -m src.cli.cli_modular housekeeping \
  --candidate-expiration-days 7 \
  --extraction-stall-hours 24 \
  --cleaning-stall-hours 24 \
  --verification-stall-hours 24 \
  --dry-run \
  --verbose
```

### Output Example

```
🧹 Pipeline Housekeeping
======================================================================
Timestamp: 2025-11-21T08:08:29.859576
Dry run: False

1️⃣  Checking for articles with NULL text...
   ✓ No articles with NULL text found

2️⃣  Checking for expired candidates (older than 7 days)...
   Found 128 candidates older than 7 days
   - KPLR11/Fox 2 Now: 45 (oldest 28d)
   - KSN/KODE TV: 32 (oldest 25d)
   ✅ Marked 128 candidates as paused

3️⃣  Checking for articles stuck in extraction (24h+)...
   ✓ No articles stuck in extraction found

4️⃣  Checking for articles stuck in cleaning (24h+)...
   ✓ No articles stuck in cleaning found

5️⃣  Checking for candidates stuck in verification (24h+)...
   ✓ No articles stuck in verification found

Summary
----------------------------------------------------------------------
  Null text articles paused: 0
  Expired candidates paused: 128
  Stuck extraction articles warned: 0
  Stuck cleaning articles warned: 0
  Stuck verification candidates warned: 0
  Total actions: 128
```

## Usage Patterns

### Local Development

```bash
# See what would be cleaned (dry-run)
python -m src.cli.cli_modular housekeeping --dry-run --verbose

# Actually run housekeeping
python -m src.cli.cli_modular housekeeping --verbose

# Custom thresholds
python -m src.cli.cli_modular housekeeping \
  --candidate-expiration-days 3 \
  --extraction-stall-hours 48
```

### Production (Kubernetes)

```bash
# View CronJob
kubectl get cronjob mizzou-housekeeping -n production

# View recent runs
kubectl get jobs -n production -l app=mizzou-housekeeping

# View latest logs
kubectl logs -n production -l app=mizzou-housekeeping --tail=100

# Manually trigger
kubectl create job --from=cronjob/mizzou-housekeeping \
  mizzou-housekeeping-manual-$(date +%s) -n production
```

## Deployment

### Prerequisites

- Processor image already deployed with housekeeping code
- Cloud SQL credentials configured in `cloudsql-db-credentials` secret
- `mizzou-app` service account with job creation permissions

### Deployment Steps

1. Apply the CronJob manifest:
   ```bash
   kubectl apply -f k8s/housekeeping-cronjob.yaml
   ```

2. Verify deployment:
   ```bash
   kubectl get cronjob mizzou-housekeeping -n production
   ```

3. Monitor first run:
   ```bash
   kubectl logs -n production -l app=mizzou-housekeeping --tail=100
   ```

## Integration with Existing Systems

### Cleanup Command

The new housekeeping command **complements** the existing `cleanup-candidates` command:

- **`cleanup-candidates`**: Targeted, on-demand cleanup of expired candidates
  - Manual invocation
  - Specific to one check (expired candidates)
  
- **`housekeeping`**: Comprehensive, scheduled maintenance
  - Daily automated execution
  - Runs all five checks
  - Reports on pipeline health

Both can coexist. Use `cleanup-candidates` for:
- One-off cleanup with custom thresholds
- Investigating specific issues
- Manual maintenance

Use `housekeeping` for:
- Scheduled daily maintenance (default 2 AM UTC)
- Comprehensive pipeline health monitoring
- Automated record expiration

### Telemetry Integration

Paused records include telemetry metadata:

```json
{
  "pause_reason": "null_text"  // or "expired"
}
```

This allows analytics to track:
- How many articles fail extraction (NULL text)
- How many candidates expire in queue (7+ days)
- Reasons for pipeline blockages

## Monitoring & Alerts

### What to Monitor

1. **Housekeeping job runs**: Should complete daily around 2 AM UTC
2. **Action counts**: Track if NULL text or expired candidate counts change
3. **Warning flags**: Articles/candidates stuck longer than threshold
4. **Job duration**: Should complete in <1 minute (low overhead)

### Sample Dashboard Metrics

```
housekeeping_null_text_articles_paused (counter)
housekeeping_expired_candidates_paused (counter)
housekeeping_stuck_extraction_articles (gauge)
housekeeping_stuck_cleaning_articles (gauge)
housekeeping_stuck_verification_candidates (gauge)
housekeeping_run_duration_seconds (histogram)
housekeeping_run_success (gauge: 1/0)
```

### Setting Alerts

Consider alerting on:

```yaml
# Too many articles stuck
alert: StuckExtractionArticles
expr: housekeeping_stuck_extraction_articles > 50

# Housekeeping job failing
alert: HousekeepingJobFailed
expr: housekeeping_run_success == 0
```

## Future Enhancements

### Phase 1 (Current)
- ✅ Implement housekeeping checks
- ✅ Deploy as Kubernetes CronJob
- ✅ Document usage and troubleshooting

### Phase 2
- [ ] Add database telemetry for pause_reason to candidate_links
- [ ] Export housekeeping metrics to Prometheus
- [ ] Add alert integration (Slack notifications)
- [ ] Create dashboard for housekeeping metrics

### Phase 3
- [ ] Add configurable auto-delete for old paused records
- [ ] Implement retry reconciliation (retry expired candidates)
- [ ] Add integration with pipeline status reporting
- [ ] Create runbooks for common housekeeping scenarios

## Testing

### Unit Tests (future)

```bash
# Test individual checks with synthetic data
pytest tests/cli/commands/test_housekeeping.py -v
```

### Integration Tests

```bash
# Test against local PostgreSQL
python -m src.cli.cli_modular housekeeping --dry-run --verbose
```

### Production Testing

```bash
# Manual run in production
kubectl create job --from=cronjob/mizzou-housekeeping \
  test-housekeeping-$(date +%s) -n production

# Monitor output
kubectl logs -n production job/test-housekeeping-1234567890
```

## Performance Impact

- **CPU**: 100-500m (request-limit)
- **Memory**: 512Mi-1Gi (request-limit)  
- **Duration**: <1 minute per run
- **Database load**: Minimal (read-heavy with some writes)
- **Frequency**: Once daily at 2 AM UTC (off-peak)

**Overall impact**: Negligible - designed for low overhead maintenance.

## Rollback

If housekeeping causes issues:

1. Delete the CronJob:
   ```bash
   kubectl delete cronjob mizzou-housekeeping -n production
   ```

2. Manually pause/clean records as needed:
   ```bash
   # Restore a paused article to extracted
   UPDATE articles SET status = 'extracted' WHERE id = '...';
   ```

3. Re-deploy after investigation:
   ```bash
   kubectl apply -f k8s/housekeeping-cronjob.yaml
   ```
