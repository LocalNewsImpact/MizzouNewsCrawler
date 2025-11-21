# Housekeeping Deployment Checklist

## Status: ✅ READY FOR DEPLOYMENT

The housekeeping system is fully implemented and deployed to Kubernetes. It will automatically start working once the processor image is rebuilt with the latest code.

## Current State

- **Code**: ✅ Complete and tested locally
  - `src/cli/commands/housekeeping.py` - Full implementation
  - `src/cli/cli_modular.py` - CLI integration complete

- **Kubernetes**: ✅ CronJob deployed
  - `k8s/housekeeping-cronjob.yaml` - Applied to production namespace
  - Schedule: Daily at 2 AM UTC
  - PriorityClass: `batch-low`
  - Resource requests: 100m CPU / 512Mi RAM

- **Testing**: ⏳ Waiting for image rebuild
  - Local testing: ✅ Passed (`--dry-run --verbose`)
  - Production testing: ⏳ Will run once processor image includes housekeeping code

## Deployment Timeline

### What's Done ✅

1. Housekeeping command implemented and tested locally
2. CronJob manifest created and applied to production
3. Documentation completed (3 docs files)
4. CLI fully integrated

### What's Needed ⏳

1. **Push code to repository** (if not already done)

```bash
git add src/cli/commands/housekeeping.py src/cli/cli_modular.py k8s/housekeeping-cronjob.yaml
git commit -m "feat: add daily pipeline housekeeping maintenance"
git push origin main
```

2. **Rebuild processor image**

```bash
gcloud builds triggers run build-processor-manual --branch=main
```

Or wait for next scheduled CI/CD run that includes processor.

### What Will Happen ✅

Once processor image is rebuilt with housekeeping code:

1. CronJob (already deployed) will automatically use the new image
2. First scheduled run: 2 AM UTC tomorrow
3. Housekeeping will check for:
   - NULL text articles
   - Expired candidates (7+ days)
   - Stuck records in extraction/cleaning/verification
4. Actions taken:
   - Pause articles with NULL text
   - Pause expired candidates
   - Report on stuck records

## Commands to Monitor Deployment

### Check CronJob Status

```bash
kubectl get cronjob mizzou-housekeeping -n production
```

### View Scheduled Runs

```bash
kubectl get jobs -n production -l app=mizzou-housekeeping
```

### View Latest Run Logs

```bash
kubectl logs -n production -l app=mizzou-housekeeping --tail=100
```

### Manual Test Run (after image rebuild)

```bash
kubectl create job --from=cronjob/mizzou-housekeeping \
  housekeeping-test-$(date +%s) -n production

# Check result
kubectl logs -n production -l app=mizzou-housekeeping --tail=50
```

## Configuration

If you need to adjust before production runs:

### Change Schedule

Edit `k8s/housekeeping-cronjob.yaml` and change `spec.schedule`:

```yaml
schedule: "0 2 * * *"  # Currently: 2 AM UTC daily
# Examples:
# "0 */6 * * *" = every 6 hours
# "0 4 * * 0" = 4 AM UTC every Sunday
# "30 * * * *" = every hour at :30
```

### Change Thresholds

Edit the command in `k8s/housekeeping-cronjob.yaml`:

```yaml
python -m src.cli.cli_modular housekeeping \
  --candidate-expiration-days 10 \      # was 7
  --extraction-stall-hours 48 \          # was 24
  --cleaning-stall-hours 48 \            # was 24
  --verification-stall-hours 48 \        # was 24
  --verbose
```

Then apply changes:

```bash
kubectl apply -f k8s/housekeeping-cronjob.yaml
```

## Rollback Plan

If housekeeping causes issues:

```bash
# Delete the CronJob
kubectl delete cronjob mizzou-housekeeping -n production

# Manually restore any records if needed
# Example: Restore an article from paused to extracted
UPDATE articles SET status = 'extracted'
WHERE id = '...' AND status = 'paused';
```

Then investigate and re-deploy after fixes:

```bash
kubectl apply -f k8s/housekeeping-cronjob.yaml
```

## Next Steps

1. **Push code to main** (if not done): `git push origin main`
2. **Trigger processor build**: `gcloud builds triggers run build-processor-manual --branch=main`
3. **Monitor first run**: Check logs around 2 AM UTC tomorrow
4. **Adjust thresholds if needed** based on first run results

## Documentation References

- **Quick Reference**: `docs/HOUSEKEEPING_QUICK_REFERENCE.md`
- **Full Guide**: `docs/HOUSEKEEPING.md`
- **Implementation Details**: `docs/HOUSEKEEPING_IMPLEMENTATION.md`

## Success Criteria

Once deployed, you'll know it's working when:

- ✅ CronJob runs daily at 2 AM UTC
- ✅ Job completes successfully (check logs)
- ✅ Reports show number of articles/candidates checked
- ✅ NULL text articles get paused with telemetry
- ✅ Expired candidates get paused and removed from queue
- ✅ Warnings appear for stuck records

Example successful output:

```text
🧹 Pipeline Housekeeping
======================================================================
Timestamp: 2025-11-21T08:08:29.859576
Dry run: False

1️⃣  Checking for articles with NULL text...
   ✓ No articles with NULL text found

2️⃣  Checking for expired candidates (older than 7 days)...
   Found 128 candidates older than 7 days
   ✅ Marked 128 candidates as paused

[... more checks ...]

Summary
----------------------------------------------------------------------
  Null text articles paused: 0
  Expired candidates paused: 128
  Total actions: 128
```
