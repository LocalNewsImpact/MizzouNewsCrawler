# Pipeline Monitoring and Visibility

This document describes the comprehensive monitoring and visibility features added to the MizzouNewsCrawler pipeline to address Issue #56.

## Overview

The crawler pipeline consists of five main stages:
1. **Discovery** - Find article URLs from news sources
2. **Verification** - Validate URLs as actual articles
3. **Extraction** - Extract article content and metadata
4. **Entity Extraction** - Extract location entities from article text
5. **Analysis/Classification** - Classify articles using ML models

## Pipeline Status Command

### Usage

```bash
# Show overall pipeline status
python -m src.cli.cli_modular pipeline-status

# Show detailed breakdown by domain/source
python -m src.cli.cli_modular pipeline-status --detailed

# Show activity in the last 48 hours
python -m src.cli.cli_modular pipeline-status --hours 48
```

### Output

The `pipeline-status` command provides:

1. **Per-Stage Metrics**
   - Queue depth (articles waiting for processing)
   - Recent activity (articles processed in last N hours)
   - Status breakdown
   - Warning indicators for bottlenecks

2. **Overall Pipeline Health**
   - Number of active stages
   - Health score (0-100%)
   - Actionable warnings

### Example Output

```
================================================================================
📊 MIZZOU NEWS CRAWLER - PIPELINE STATUS REPORT
================================================================================
Timestamp: 2025-10-08T12:00:00.000000Z
Activity window: Last 24 hours

━━━ STAGE 1: DISCOVERY ━━━
  Total sources: 157
  Sources due for discovery: 143
  Sources discovered from (last 24h): 15
  URLs discovered (last 24h): 453
  ✓ Average URLs per source: 30.2

━━━ STAGE 2: VERIFICATION ━━━
  Pending verification: 234
  Verified as articles (total): 5,432
  URLs verified (last 24h): 187
  ✓ Verification active in last 24h

━━━ STAGE 3: EXTRACTION ━━━
  Ready for extraction: 123
  Total extracted: 4,892
  Extracted (last 24h): 98
  ✓ Extraction active in last 24h

  Status breakdown:
    • extracted: 2,134
    • cleaned: 1,892
    • wire: 567
    • local: 299

━━━ STAGE 4: ENTITY EXTRACTION ━━━
  Ready for entity extraction: 1,538
  Articles with entities (total): 3,354
  Articles processed (last 24h): 89
  ⚠️  WARNING: Large backlog of 1,538 articles!

━━━ STAGE 5: ANALYSIS/CLASSIFICATION ━━━
  Ready for analysis: 1,405
  Articles analyzed (total): 2,947
  Analyzed (last 24h): 76
  ⚠️  WARNING: Large backlog of 1,405 articles!

━━━ OVERALL PIPELINE HEALTH ━━━
  Pipeline stages active: 5/5
  Health score: 100%
  ✅ Pipeline is healthy!

================================================================================
```

## Real-Time Logging Improvements

All CLI commands now output progress information to stdout in real-time for visibility in cloud logs:

### Discovery Command

```bash
python -m src.cli.cli_modular discover-urls --force-all
```

Output:
```
🚀 Starting URL discovery pipeline...
   Dataset: all
   Source limit: none
   Due only: False
   Force all: True

📊 Source Discovery Status:
   Sources available: 157
   Sources due for discovery: 143
   Sources to process: 157

✓ [1/157] Springfield News-Leader: 42 new URLs
✓ [2/157] Columbia Daily Tribune: 38 new URLs
✓ [3/157] Kansas City Star: 51 new URLs
...
✗ [23/157] Example Source: ERROR - Connection timeout

=== Discovery Results ===
Sources processed: 157
Total candidate URLs discovered: 4,523
...
```

### Extraction Command

```bash
python -m src.cli.cli_modular extract --limit 10 --batches 5
```

Output:
```
🚀 Starting content extraction...
   Batches: 5
   Articles per batch: 10

📄 Processing batch 1/5...
✓ Batch 1 complete: 10 articles extracted
  ⚠️  2 domains skipped due to rate limits

📄 Processing batch 2/5...
✓ Batch 2 complete: 8 articles extracted
  ⚠️  3 domains skipped due to rate limits

...

🧹 Running post-extraction cleaning for 15 domains...
✓ Cleaning complete

📊 ChromeDriver efficiency: 45 reuses, 3 creations

✅ Extraction completed successfully!
```

### Entity Extraction Command

```bash
python -m src.cli.cli_modular extract-entities --limit 100
```

Output:
```
🚀 Starting entity extraction...
   Processing limit: 100 articles

📊 Found 87 articles needing entity extraction
✓ Progress: 10/87 articles processed
✓ Progress: 20/87 articles processed
...
✓ Progress: 80/87 articles processed

✅ Entity extraction completed!
   Processed: 87 articles
   Errors: 0
```

### Verification Command

```bash
python -m src.cli.cli_modular verify-urls --batch-size 50 --max-batches 10
```

Output:
```
🚀 Starting verification service (max 10 batches)...
📄 Processing batch 1: 50 URLs...
✓ Batch 1 complete: 32 articles, 15 non-articles, 3 errors (avg: 245.3ms)
📄 Processing batch 2: 50 URLs...
✓ Batch 2 complete: 28 articles, 19 non-articles, 3 errors (avg: 198.7ms)
...
✅ Verification completed successfully!
```

## Monitoring Best Practices

### Daily Health Check

Run this command daily to ensure the pipeline is healthy:

```bash
python -m src.cli.cli_modular pipeline-status
```

Look for:
- ⚠️ WARNING indicators for large backlogs
- ❌ ERROR indicators for stalled stages
- Health score below 80%

### Debugging Stalled Stages

If a stage shows no recent activity:

1. **Check logs**: Look for errors in the last run
2. **Check resources**: Ensure CPU/memory are available
3. **Check dependencies**: Verify external services are available
4. **Manual test**: Run a small batch manually to see errors

Example:
```bash
# Test discovery manually
python -m src.cli.cli_modular discover-urls --source-limit 1

# Test extraction manually
python -m src.cli.cli_modular extract --limit 1 --batches 1

# Test entity extraction manually
python -m src.cli.cli_modular extract-entities --limit 1
```

### Addressing Backlogs

If the pipeline-status shows large backlogs:

1. **Increase processing frequency**: Run jobs more often
2. **Increase batch sizes**: Process more items per run
3. **Scale resources**: Add more CPU/memory if needed
4. **Parallelize**: Consider running multiple workers

Example Kubernetes CronJob adjustments:
```yaml
# From: Every 6 hours
schedule: "0 */6 * * *"
# To: Every 2 hours
schedule: "0 */2 * * *"
```

## Error Tracking

All commands now provide:
- Real-time error reporting during execution
- Error summaries at completion
- Detailed failure analysis (discovery only)

### Discovery Failure Analysis

If discovery encounters errors, it provides:
```
⚠️  Errors encountered during discovery

=== Failure Analysis ===
Total site failures: 15
Most common failure type: connection_error

Failure breakdown:
  connection_error: 8 (53.3%)
  timeout: 4 (26.7%)
  http_error: 3 (20.0%)
```

## Integration with Kubernetes

### CronJob Monitoring

View logs in Google Cloud Console:
```
gcloud logging read "resource.type=k8s_container
  AND resource.labels.container_name=crawler
  AND timestamp>=2025-10-08T00:00:00Z" \
  --limit 100 --format json
```

### Manual Job Trigger

Test pipeline stages manually in Kubernetes:
```bash
# Trigger discovery
kubectl create job --from=cronjob/mizzou-crawler-discovery mizzou-discovery-test

# Monitor progress
kubectl logs -f job/mizzou-discovery-test

# Check pipeline status
kubectl exec -it deployment/mizzou-processor -- \
  python -m src.cli.cli_modular pipeline-status
```

## Troubleshooting

### No URLs Discovered

Check:
1. Sources are due for discovery (not processed in last 7 days)
2. Network connectivity to source websites
3. RSS feeds are still active
4. Source configurations are correct

```bash
# Force discovery regardless of schedule
python -m src.cli.cli_modular discover-urls --force-all --source-limit 5

# Check specific source
python -m src.cli.cli_modular discover-urls --source "Springfield"
```

### High Error Rates

Check:
1. Rate limiting by news websites
2. CAPTCHA detection
3. Changed website structures
4. Network issues

```bash
# View detailed extraction status
python -m src.cli.cli_modular pipeline-status --detailed --hours 6
```

### Stalled Entity Extraction

Check:
1. Large articles timing out
2. Gazetteer data available
3. SpaCy models loaded correctly

```bash
# Test small batch
python -m src.cli.cli_modular extract-entities --limit 1
```

## Metrics to Monitor

### Key Performance Indicators

1. **Discovery Rate**: URLs discovered per hour
   - Target: > 50 URLs/hour
   - Alert if: < 10 URLs/hour for 6 hours

2. **Verification Rate**: URLs verified per hour
   - Target: > 100 URLs/hour
   - Alert if: < 20 URLs/hour for 6 hours

3. **Extraction Rate**: Articles extracted per hour
   - Target: > 50 articles/hour
   - Alert if: < 10 articles/hour for 6 hours

4. **Pipeline Health Score**: Overall activity level
   - Target: > 80%
   - Alert if: < 60% for 12 hours

5. **Queue Depths**: Pending items at each stage
   - Target: < 500 pending
   - Alert if: > 2000 pending

### Setting Up Alerts

Use the pipeline-status command in a monitoring script:

```bash
#!/bin/bash
# monitor-pipeline.sh

STATUS=$(python -m src.cli.cli_modular pipeline-status)

# Extract health score (example - adjust parsing as needed)
HEALTH=$(echo "$STATUS" | grep "Health score:" | awk '{print $3}' | tr -d '%')

if [ "$HEALTH" -lt 60 ]; then
  echo "ALERT: Pipeline health is ${HEALTH}%"
  # Send alert (email, Slack, PagerDuty, etc.)
fi
```

## Future Enhancements

Planned improvements for pipeline visibility:
- [ ] Prometheus metrics export
- [ ] Grafana dashboards
- [ ] Automated alerting via Cloud Monitoring
- [ ] Per-source success rate tracking
- [ ] Historical trend analysis
- [ ] Predictive backlog warnings
