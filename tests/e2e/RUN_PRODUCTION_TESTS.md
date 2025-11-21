# Production E2E Tests

Comprehensive end-to-end tests that validate critical functionality after deployment to production.

## Purpose

These tests run **against the actual production database** and verify:

- Core pipeline functionality (discovery → verification → extraction)
- Error recovery and resilience mechanisms
- Data integrity and consistency
- Telemetry and monitoring systems
- ML pipeline integration
- Performance and throughput

## Running Tests

### From production pod

```bash
# All tests
kubectl exec -n production deployment/mizzou-processor -- \
    pytest tests/e2e/test_production_smoke.py -v

# Specific test class
kubectl exec -n production deployment/mizzou-processor -- \
    pytest tests/e2e/test_production_smoke.py::TestErrorRecoveryAndResilience -v

# Specific test
kubectl exec -n production deployment/mizzou-processor -- \
    pytest tests/e2e/test_production_smoke.py::TestErrorRecoveryAndResilience::test_duplicate_article_prevention_via_unique_constraint -v

# With detailed output
kubectl exec -n production deployment/mizzou-processor -- \
    pytest tests/e2e/test_production_smoke.py -v --tb=short
```

### CI/CD Integration

Add to post-deployment workflow:

```yaml
- name: Run production e2e tests
  run: |
    kubectl exec -n production deployment/mizzou-processor -- \
      pytest tests/e2e/test_production_smoke.py -v --tb=short
```

## Test Coverage

### TestSectionURLExtraction

- Section URLs are extracted and stored
- Section discovery is enabled
- Article URLs discovered from section crawling

### TestExtractionPipeline

- Complete discovery → verification → extraction flow
- Content quality checks
- Reasonable conversion rates

### TestTelemetrySystem

- Telemetry writes succeed
- Hash columns handle large values
- No data corruption

### TestMLPipeline

- Entity extraction on new articles
- Classification labeling
- Label confidence scores

### TestDataIntegrity

- No orphaned articles
- No duplicate extractions
- Source metadata completeness

### TestErrorRecoveryAndResilience

- **Extraction failures** are logged and don't corrupt data
- **Duplicate prevention** via unique URL constraint
- **Database resilience** with connection pooling and timeouts
- **Transaction rollback** on extraction errors
- **Retry mechanism** allows retrying failed extractions

### TestContentCleaningPipeline (NEW)

- **Content cleaning status** articles properly transition extracted → cleaned
- **Content validation** boilerplate removal works correctly
- **Byline normalization** author field contains person names not raw bylines
- **Wire service detection** syndicated content properly labeled and preserved
- **Section URL handling** section-discovered articles process normally

### TestPerformance

- Extraction throughput (articles/hour)
- Verification throughput (URLs/hour)

## Key Assertions

### Error Recovery & Resilience Tests

```python
# Extraction failures should be rare and logged
assert failure_rate < 0.05, "High extraction failure rate"

# Duplicate URL constraint prevents double extraction
assert duplicates == 0, "Found duplicate article extractions"

# Database has proper timeout configuration
assert timeout_ms > 0, "Statement timeout not configured"

# Transaction atomicity prevents partial updates
assert incomplete_labeled < 5, "Labeled articles missing content"

# Extraction can be retried on failure
assert success_rate > 0.6, "Low retry success rate"
```

### Content Cleaning Pipeline Tests

```python
# Cleaned articles should exist and be processed
assert cleaned_count > 0, "No articles have cleaned_content"

# Boilerplate removal should reduce content size
assert reduction > 0.05, "Low content reduction - cleaning may not work"
assert reduction < 0.95, "High reduction - cleaning too aggressive"

# Authors should be normalized names, not full bylines
assert avg_author_length < 100, "Authors too long - not normalized"
assert wire_contamination < 0.1, "Wire services in author field"

# Wire articles should be properly labeled
assert preservation_ratio > 0.7, "Wire service bylines not preserved"

# Section URL articles should process normally
assert cleaned_ratio > 0.7, "Low cleaning success for section articles"
```

## Troubleshooting

**Tests require production database access:**

```text
AssertionError: Tests must run against production database
```

→ Tests must run inside production pod via `kubectl exec`

**No recent data in tests:**

→ Verify extraction is actively running: `kubectl logs -n production -l app=mizzou-processor --tail=50`

**Duplicate article assertion fails:**

→ Check if unique constraint migration was applied: `kubectl exec -n production deployment/mizzou-api -- alembic current`

## Test Maintenance

When adding new features:

1. Add corresponding e2e test to validate production behavior
1. Run tests after deployment to ensure feature works
1. Keep assertions loose enough for real-world data variation
1. Document expected baseline metrics in test comments
