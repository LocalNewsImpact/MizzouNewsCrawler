# Production Smoke Test Results - November 20, 2025

## Test Run Summary

**Status**: 8 failed, 6 passed
**Runtime**: 21.99 seconds
**Pod**: mizzou-processor-7c874f8d69-p9s24

## Passed Tests ✅

1. **TestExtractionPipeline::test_content_quality_checks** - Articles have good content quality
2. **TestTelemetrySystem::test_telemetry_writes_succeed** - Telemetry system writing data
3. **TestTelemetrySystem::test_hash_columns_handle_large_values** - BigInt migration successful
4. **TestDataIntegrity::test_no_orphaned_articles** - No broken foreign keys
5. **TestDataIntegrity::test_source_metadata_complete** - Source metadata is complete
6. **TestPerformance::test_extraction_throughput** - Maintaining >50 articles/hour

## Failed Tests ❌

### 1. Section URL Extraction Tests (3 failures)

**Root Cause**: Schema mismatch - columns don't exist in production

- `candidate_links.is_section_url` - column does not exist
- `candidate_links.section_url_id` - column does not exist  
- `source_urls` table - table does not exist

**Impact**: Section URL extraction feature not yet deployed to production

**Action Required**: 
- Feature is not implemented yet OR
- Migration needed to add these columns/tables
- Tests are validating a future feature

### 2. Low Extraction Rate

**Issue**: Extraction rate is 49.0%, expected >50%
**Status**: Borderline - just slightly below threshold
**Action**: Monitor, may be normal variation

### 3. ML Pipeline Tests (2 failures)

**Root Cause**: Schema mismatch

- `article_entities.entity_type` - column does not exist (has `entity_text` instead)
- `article_labels.confidence` - column does not exist

**Impact**: Schema doesn't match test expectations for ML tables

**Action Required**: Check actual schema structure and update tests

### 4. Duplicate Extractions

**Issue**: Found 3 duplicate URLs with multiple extractions:
- `https://abc17news.com/cnn-other/2025/11/18/archaeologists-surveyed...`
- `https://abc17news.com/cnn-spanish/2025/10/25/el-lider-de-hungria...`
- `https://abc17news.com/cnn-spanish/2025/11/02/encuentran-a-14-mujeres...`

**Impact**: Data quality issue - same article extracted multiple times

**Action Required**: 
- Investigate why duplicates occur
- Add deduplication logic
- Clean up existing duplicates

### 5. Verification Throughput Test

**Root Cause**: Schema mismatch
- `candidate_links.status_updated_at` - column does not exist

**Impact**: Cannot track verification timing

**Action Required**: Check actual columns for status tracking

## Conclusions

### The Good News 👍

1. **Core extraction works**: Content quality is good, throughput is acceptable
2. **Telemetry fixed**: BigInt migration successful, no overflow errors
3. **Data integrity mostly good**: No orphaned records, metadata complete

### The Issues 🔧

1. **Schema mismatches**: Tests assume columns/tables that don't exist yet
   - Section URL feature not deployed
   - ML schema different than expected
   - Status tracking columns missing

2. **Data quality**: Duplicate extractions need investigation

3. **Test accuracy**: Tests were written based on planned features, not actual production schema

## Next Steps

### Immediate (Priority 1)

1. **Query actual production schema** to understand what columns/tables exist:
   ```python
   SELECT table_name, column_name, data_type 
   FROM information_schema.columns 
   WHERE table_schema = 'public'
   ORDER BY table_name, ordinal_position
   ```

2. **Update tests** to match actual production schema

3. **Investigate duplicates** and implement deduplication

### Short-term (Priority 2)

4. **Review section URL feature status**:
   - Is it planned? 
   - Does it need migration?
   - When will it be deployed?

5. **Verify ML schema** matches code expectations

6. **Add status tracking** if needed for verification throughput

### Long-term (Priority 3)

7. **Add slow mark to pytest.ini** to avoid warning
8. **Automate post-deployment testing** via GitHub Actions
9. **Set up alerting** for critical test failures

## Recommendations

1. **Two-phase approach for smoke tests**:
   - **Phase 1**: Update tests to match current production schema
   - **Phase 2**: Add tests for new features as they're deployed

2. **Schema documentation**: Maintain docs/PRODUCTION_SCHEMA.md with actual schema

3. **Feature flags**: Tests should check if features are enabled before testing them

4. **Test markers**: Add `@pytest.mark.skip_if_not_deployed("section_urls")` style markers
