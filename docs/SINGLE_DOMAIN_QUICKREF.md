# Single-Domain Dataset Quick Reference

## What Are Single-Domain Datasets?

Datasets where all articles come from a single website domain (e.g., Lehigh Valley News has only `lehighvalleynews.com`).

**Challenge**: Can't rotate between domains to avoid rate limits → higher risk of bot detection.

## How the System Handles Them

### Automatic Detection (New in Issue #74)

The extraction system now **automatically detects** single-domain datasets:

```
📊 Dataset analysis: 1 unique domain(s)
⚠️  Single-domain dataset detected: lehighvalleynews.com
🐌 Rate limiting will be conservative to avoid bot detection
```

### What Happens Automatically

1. **Upfront Analysis**: Checks domain diversity before extraction starts
2. **Conservative Rate Limiting**: Applies longer pauses between batches
3. **Clear Warnings**: Shows if configuration needs adjustment

## Configuration Cheat Sheet

### ✅ Good Configuration (Single-Domain)

```yaml
env:
  - name: BATCH_SLEEP_SECONDS
    value: "300"  # 5 minutes minimum
  - name: BATCH_SLEEP_JITTER
    value: "0.45"  # Add randomness
  - name: INTER_REQUEST_MIN
    value: "90"   # 90 seconds minimum
  - name: INTER_REQUEST_MAX
    value: "180"  # 3 minutes maximum
```

### ⚠️ Aggressive Bot Protection (like Lehigh)

```yaml
env:
  - name: BATCH_SLEEP_SECONDS
    value: "420"  # 7 minutes
  - name: INTER_REQUEST_MIN
    value: "90"
  - name: INTER_REQUEST_MAX
    value: "180"
  - name: CAPTCHA_BACKOFF_BASE
    value: "7200"  # 2 hours on captcha
```

### ❌ Bad Configuration (Too Fast)

```yaml
env:
  - name: BATCH_SLEEP_SECONDS
    value: "5"   # TOO FAST - will trigger bot detection
  - name: INTER_REQUEST_MIN
    value: "10"  # TOO FAST
```

**Warning**: System will alert you if configuration is too aggressive.

## Quick Commands

### Monitor Domain Detection

```bash
# See domain analysis on job start
kubectl logs -n production -l dataset=YOUR_DATASET --follow | grep "Dataset analysis"

# Watch for single-domain warnings
kubectl logs -n production -l dataset=YOUR_DATASET --follow | grep "Single-domain"
```

### Monitor Rate Limiting

```bash
# Watch batch pauses
kubectl logs -n production -l dataset=YOUR_DATASET --follow | grep "⏸️"

# Check for rate limit errors
kubectl logs -n production -l dataset=YOUR_DATASET --follow | grep "429\|rate limit"
```

### Check Configuration

```bash
# View current environment variables
kubectl get job extract-YOUR_DATASET -n production -o yaml | grep -A 2 "BATCH_SLEEP"
```

## Troubleshooting

### Problem: Getting 429 Errors

**Solution**: Increase `BATCH_SLEEP_SECONDS` and `INTER_REQUEST_MIN`

```yaml
- name: BATCH_SLEEP_SECONDS
  value: "600"  # Increase to 10 minutes
```

### Problem: Job Too Slow

**Check First**: Is this a single-domain dataset?
- If YES: Slow is expected and necessary
- If NO: You can reduce sleep times

**For confirmed multi-domain datasets:**

```yaml
- name: BATCH_SLEEP_SECONDS
  value: "30"  # Can be faster with domain rotation
```

### Problem: Warning "BATCH_SLEEP_SECONDS is low"

**What it means**: System detected single domain but config is too aggressive.

**Solution**: Increase the value:

```yaml
- name: BATCH_SLEEP_SECONDS
  value: "300"  # Or higher
```

## Examples

### Lehigh Valley News (Single-Domain, Aggressive Bot Protection)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: extract-lehigh
spec:
  template:
    spec:
      containers:
      - name: extraction
        command: [python, -m, src.cli.main, extract, --dataset, Penn-State-Lehigh]
        env:
        - name: BATCH_SLEEP_SECONDS
          value: "420"    # 7 minutes
        - name: INTER_REQUEST_MIN
          value: "90"     # 90 seconds
        - name: INTER_REQUEST_MAX
          value: "180"    # 3 minutes
        - name: BATCH_SLEEP_JITTER
          value: "0.45"   # ±45% randomness
```

**Expected Runtime**: ~1 article per 2-3 minutes (intentionally slow)

### Missouri Dataset (Multi-Domain)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: extract-missouri
spec:
  template:
    spec:
      containers:
      - name: extraction
        command: [python, -m, src.cli.main, extract, --dataset, missouri]
        env:
        - name: BATCH_SLEEP_SECONDS
          value: "30"     # Can be faster
        - name: INTER_REQUEST_MIN
          value: "10"     # Faster with rotation
```

**Expected Runtime**: ~1 article per 15-30 seconds (domain rotation helps)

## Key Takeaways

1. **Single-domain = Slow is Good**: Conservative timing avoids IP blocks
2. **System Detects Automatically**: No manual configuration needed for basic cases
3. **Watch the Logs**: System provides clear guidance via warnings
4. **When in Doubt, Go Slow**: Better to be conservative than get blocked
5. **Randomness Helps**: Use jitter to avoid pattern detection

## Related Documentation

- `ISSUE_74_IMPLEMENTATION.md` - Full implementation details
- `k8s/templates/README.md` - Job template documentation
- `k8s/lehigh-extraction-job.yaml` - Real-world example

## Support

If you encounter issues with single-domain datasets:

1. Check logs for domain analysis output
2. Verify BATCH_SLEEP_SECONDS is ≥300 for single domain
3. Look for rate limit warnings (429 errors)
4. Consider increasing sleep times if issues persist
