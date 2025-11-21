# Housekeeping Quick Reference

## What It Does

Daily automated maintenance that checks for stuck pipeline records and expires stale candidates:

```text
NULL text    Expired      Stuck         Stuck      Stuck
articles  → candidates → extraction  → cleaning  → verification
(pause)     (pause)      (warn)       (warn)      (warn)
```

## Quick Commands

### Test It Out

```bash
# Dry-run (no changes, see what would happen)
python -m src.cli.cli_modular housekeeping --dry-run --verbose
```

### Run It

```bash
# Actually run housekeeping
python -m src.cli.cli_modular housekeeping --verbose
```

### Custom Thresholds

```bash
# Mark candidates as paused after 3 days instead of 7
python -m src.cli.cli_modular housekeeping --candidate-expiration-days 3

# Only warn about articles stuck for 48+ hours
python -m src.cli.cli_modular housekeeping --extraction-stall-hours 48
```

## Production

Runs daily at **2 AM UTC** via Kubernetes CronJob.

### Check Status

```bash
# View scheduled job
kubectl get cronjob mizzou-housekeeping -n production

# View recent runs
kubectl get jobs -n production -l app=mizzou-housekeeping

# See latest logs
kubectl logs -n production -l app=mizzou-housekeeping --tail=50
```

### Manual Trigger

```bash
kubectl create job --from=cronjob/mizzou-housekeeping \
  housekeeping-manual-$(date +%s) -n production
```

## What Gets Paused

| Record Type | Condition | Reason |
|------------|-----------|--------|
| Articles | NULL text content | Can't proceed through pipeline |
| Candidates | In queue >7 days | Likely expired/unreachable |

## What Gets Warned About

| Record Type | Condition | What It Means |
|------------|-----------|---------------|
| Articles | Stuck in extraction 24h+ | Cleaning pipeline bottleneck |
| Articles | Stuck in cleaning 24h+ | Labeling pipeline bottleneck |
| Candidates | Stuck in verification 24h+ | Extraction queue bottleneck |

## Customization

### Change Schedule

Edit `k8s/housekeeping-cronjob.yaml`:

```yaml
spec:
  schedule: "0 2 * * *"  # Currently: 2 AM UTC daily
  # Use cron format: minute hour day month weekday
  # "0 */6 * * *" = every 6 hours
  # "0 4 * * 1" = 4 AM UTC every Monday
```

### Change Thresholds

Edit `k8s/housekeeping-cronjob.yaml` command section:

```yaml
python -m src.cli.cli_modular housekeeping \
  --candidate-expiration-days 10 \      # 10 days instead of 7
  --extraction-stall-hours 48 \          # 48 hours instead of 24
  --verbose
```

## Troubleshooting

### "No modules named" error

Solution: Make sure processor image is rebuilt with latest code

```bash
gcloud builds triggers run build-processor-manual --branch=main
```

### CronJob not running

Check if CronJob exists:

```bash
kubectl describe cronjob mizzou-housekeeping -n production
```

Check if service account has permissions:

```bash
kubectl get rolebinding -n production | grep mizzou-app
```

### Wrong records got paused

You can undo by updating database directly:

```bash
# Restore an article from paused to extracted
UPDATE articles SET status = 'extracted' WHERE id = '...' AND status = 'paused';

# Restore a candidate from paused to article
UPDATE candidate_links SET status = 'article' WHERE id = '...' AND status = 'paused';
```

## Files

| File | Purpose |
|------|---------|
| `src/cli/commands/housekeeping.py` | Command implementation |
| `k8s/housekeeping-cronjob.yaml` | Kubernetes CronJob |
| `docs/HOUSEKEEPING.md` | Full documentation |
| `docs/HOUSEKEEPING_IMPLEMENTATION.md` | Implementation details |

## Next Steps

1. **Verify production deployment**: `kubectl get cronjob mizzou-housekeeping -n production`
1. **Watch first run**: Check logs at 2 AM UTC
1. **Adjust thresholds if needed**: Edit CronJob manifest and reapply
1. **Monitor metrics**: Track action counts over time
