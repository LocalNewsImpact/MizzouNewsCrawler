# Production Smoke Tests

End-to-end smoke tests that validate critical workflows in the production environment after deployments.

## Overview

These tests ensure that integrated systems are working as designed by testing the full pipeline from discovery to extraction to analysis.

## Running Tests

### Local Execution (against production)

```bash
# Run all smoke tests
./scripts/run-production-smoke-tests.sh

# Run specific test class
./scripts/run-production-smoke-tests.sh TestSectionURLExtraction

# Run with verbose output
./scripts/run-production-smoke-tests.sh --verbose
```

### Direct kubectl execution

```bash
# Run all tests
kubectl exec -n production deployment/mizzou-processor -- \
  pytest tests/e2e/test_production_smoke.py -v

# Run specific test
kubectl exec -n production deployment/mizzou-processor -- \
  pytest tests/e2e/test_production_smoke.py::TestSectionURLExtraction -v
```

### GitHub Actions

Tests run automatically after successful deployments via the `production-smoke-tests.yml` workflow.

Manual trigger:
1. Go to Actions → Production Smoke Tests
2. Click "Run workflow"
3. Optionally specify a test filter

## Test Coverage

### TestSectionURLExtraction

Validates the section URL extraction and discovery integration:
- ✅ Section URLs are extracted from article URLs and stored
- ✅ Section URLs are marked correctly in database
- ✅ Section URLs are used by newspaper3k for discovery
- ✅ New article URLs are discovered from section URLs

**Why this matters:** This integrated fix ensures we discover more articles by using section/category pages as entry points.

### TestExtractionPipeline

Validates the complete discovery → verification → extraction pipeline:
- ✅ URLs are discovered and saved to `candidate_links`
- ✅ URLs are verified and marked as `article` or `non-article`
- ✅ Articles are extracted and content saved
- ✅ Extraction happens within reasonable time
- ✅ Content quality is maintained (length, fields populated)

**Why this matters:** This is the core pipeline - if any stage breaks, no articles get processed.

### TestTelemetrySystem

Validates telemetry and monitoring systems:
- ✅ Telemetry writes succeed without errors
- ✅ Hash columns handle full 64-bit values (no integer overflow)
- ✅ Telemetry data is recent and continuous

**Why this matters:** Telemetry tracks extraction quality and performance. Failures here mean blind spots in monitoring.

### TestMLPipeline

Validates ML analysis and labeling:
- ✅ Articles get entity extraction (NER)
- ✅ Articles get classification labels
- ✅ Entity types and labels are reasonable
- ✅ Confidence scores are acceptable

**Why this matters:** Without ML analysis, articles lack the metadata needed for filtering and discovery.

### TestDataIntegrity

Validates data consistency:
- ✅ No orphaned articles (broken foreign keys)
- ✅ No duplicate extractions for same URL
- ✅ Active sources have complete metadata

**Why this matters:** Data integrity issues compound over time and can break analytics queries.

### TestPerformance

Validates throughput and performance:
- ✅ Extraction maintains >50 articles/hour
- ✅ Verification maintains >100 URLs/hour

**Why this matters:** Low throughput indicates bottlenecks or resource constraints.

## Test Design Principles

### Production-Safe
- Read-only queries (no writes)
- Uses existing production data
- No test data insertion required
- Safe to run repeatedly

### Fast Execution
- Most tests complete in <5 seconds
- Performance tests marked with `@pytest.mark.slow`
- Can run subset of tests for quick validation

### Clear Failure Messages
Each assertion includes context:
```python
assert result > 0, \
    "No articles extracted in last 24h - extraction may not be running"
```

### Time-Aware
- Tests look at recent data (last 1-24 hours)
- Accounts for deployment gaps (doesn't expect real-time data)
- Validates trends, not absolute numbers

## Adding New Tests

When adding new integrated features, add corresponding smoke tests:

1. **Identify the workflow**: What stages does data flow through?
2. **Find verification points**: What database state proves each stage worked?
3. **Write assertions**: Check that recent data shows the workflow is active
4. **Add failure context**: Explain what might be broken if the test fails

### Example: Adding a new feature test

```python
class TestNewFeature:
    """Test the new X feature integration."""
    
    def test_feature_x_workflow(self, production_db):
        """
        Verify feature X works end-to-end.
        
        Validates:
        1. Input data is processed
        2. Feature X writes results
        3. Results are recent and valid
        """
        with production_db.get_session() as session:
            result = session.execute(text("""
                SELECT COUNT(*) 
                FROM feature_x_table
                WHERE created_at >= NOW() - INTERVAL '1 hour'
            """)).scalar()
            
            assert result > 0, \
                "No feature X results in last hour - feature may not be running"
```

## Interpreting Failures

### "No articles extracted in last 24h"
- Check Argo workflows are running: `argo list -n production`
- Check processor logs: `kubectl logs -n production -l app=mizzou-processor`
- Verify database connectivity

### "Low verification rate"
- URL discovery may be finding non-articles
- Check source configurations
- Review verification logic

### "Hash columns are not bigint"
- Migration didn't run or was rolled back
- Check: `kubectl exec -n production deployment/mizzou-api -- alembic current`

### "No telemetry writes"
- Telemetry system may be broken
- Check processor logs for errors
- Verify database permissions

### "Low extraction rate"
- May need more workers (scale up processor)
- Check for backlog: run pipeline-status
- Review extraction logs for errors

## CI Integration

The `production-smoke-tests.yml` workflow:
1. Triggers after successful deployments
2. Waits 60 seconds for deployment to stabilize
3. Runs all smoke tests in production
4. Creates GitHub issue if tests fail
5. Can be triggered manually for ad-hoc validation

## Monitoring

After each deployment:
1. Monitor workflow in GitHub Actions
2. Check Slack notifications (if configured)
3. Review any created issues
4. If tests fail, investigate before next deployment

## Best Practices

### When to Run
- ✅ After every production deployment
- ✅ Before major releases
- ✅ When investigating production issues
- ✅ After database migrations
- ❌ Not in development/staging (designed for production data)

### What to Check
- All tests passing → deployment successful
- Performance tests failing → may need scaling
- Pipeline tests failing → critical, investigate immediately
- Integrity tests failing → data corruption, urgent

### Response Times
- **Critical failures** (extraction, discovery): <1 hour response
- **Performance degradation**: <4 hour response
- **Telemetry failures**: <24 hour response
- **Integrity issues**: <24 hour response

## Future Enhancements

Potential additions:
- [ ] Alert integration (PagerDuty, Slack)
- [ ] Performance benchmarking over time
- [ ] Automated rollback on critical failures
- [ ] API endpoint smoke tests
- [ ] Geography/county coverage validation
- [ ] Source-specific validation (per-county checks)
