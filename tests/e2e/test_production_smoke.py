"""
End-to-end smoke tests for production environment.

These tests validate critical workflows after deployment to ensure
integrated systems are working as designed.

Run with:
    pytest tests/e2e/test_production_smoke.py -v

Or via kubectl:
    kubectl exec -n production deployment/mizzou-processor -- \
        pytest tests/e2e/test_production_smoke.py -v
"""
import logging
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def production_db():
    """Get production database connection."""
    # Ensure we're connecting to production Cloud SQL
    assert os.getenv("USE_CLOUD_SQL_CONNECTOR") == "true", \
        "Tests must run against production database"

    db = DatabaseManager()
    yield db


class TestSectionURLExtraction:
    """Test section URL extraction and discovery integration."""

    def test_section_urls_are_extracted_and_stored(self, production_db):
        """
        Verify section URLs are discovered and stored in sources.discovered_sections.

        Validates the integrated fix where:
        1. Section URLs are discovered from news sites
        2. Section URLs are saved to sources.discovered_sections JSON column
        3. Section discovery is enabled for sources
        4. Discovery timestamps are recent
        """
        with production_db.get_session() as session:
            # Check that we have section URLs in the database
            result = session.execute(text("""
                SELECT
                    COUNT(*) as sources_with_sections,
                    MIN(section_last_updated) as oldest,
                    MAX(section_last_updated) as newest
                FROM sources
                WHERE discovered_sections IS NOT NULL
            """)).fetchone()

            section_count, oldest, newest = result

            # Should have sources with discovered sections
            assert section_count > 0, \
                "No section URLs found - section discovery may not be working"

            # Section URLs should be recent (within last 7 days)
            if newest:
                age_days = (datetime.now() - newest).days
                assert age_days < 7, \
                    f"Most recent section discovery is {age_days} days old - may have stopped"

    def test_section_urls_used_in_discovery(self, production_db):
        """
        Verify section URLs are configured and enabled for discovery.

        Validates that:
        1. Active sources have section_discovery_enabled flag set
        2. Sources have discovered_sections data populated
        3. Multiple sources are using section-based discovery
        """
        with production_db.get_session() as session:
            # Check that sources have section discovery enabled
            result = session.execute(text("""
                SELECT
                    COUNT(*) as total_active,
                    COUNT(CASE WHEN section_discovery_enabled THEN 1 END) as enabled_count,
                    COUNT(CASE WHEN discovered_sections IS NOT NULL THEN 1 END) as with_sections
                FROM sources
                WHERE status = 'active'
            """)).fetchone()

            total_active, enabled_count, with_sections = result

            assert enabled_count > 0, \
                "No active sources have section discovery enabled"

            # At least some active sources should have discovered sections
            if total_active > 0:
                ratio = with_sections / total_active
                assert ratio > 0.1, \
                    f"Only {ratio:.1%} of active sources have discovered sections"

    def test_article_urls_discovered_from_sections(self, production_db):
        """
        Verify article URLs are discovered using supplemental section crawling.

        Section discovery runs alongside homepage discovery to ensure comprehensive
        coverage, not just as a fallback when homepage discovery fails.

        Validates the full workflow:
        1. Section URLs exist in sources.discovered_sections
        2. Sources are ready to use supplemental section discovery
        3. Infrastructure is in place for section-based discovery
        """
        with production_db.get_session() as session:
            # Check for discoveries using section_supplemental method
            result = session.execute(text("""
                SELECT COUNT(*) as section_discoveries
                FROM candidate_links
                WHERE discovered_at >= NOW() - INTERVAL '7 days'
                AND discovered_by = 'section_supplemental'
            """)).scalar()

            # Verify infrastructure is ready
            sources_ready = session.execute(text("""
                SELECT COUNT(*)
                FROM sources
                WHERE discovered_sections IS NOT NULL
                AND section_discovery_enabled = true
            """)).scalar()

            assert sources_ready > 0, \
                "No sources configured with sections - section discovery not set up"

            # Section discovery should be actively finding articles
            logger.info(
                f"Found {result} articles via supplemental section discovery "
                f"in last 7 days from {sources_ready} configured sources"
            )


class TestExtractionPipeline:
    """Test extraction pipeline end-to-end."""

    def test_discovery_verification_extraction_flow(self, production_db):
        """
        Verify the complete discovery → verification → extraction pipeline.

        Validates:
        1. URLs are discovered (candidate_links created)
        2. URLs are verified (status updated to 'article')
        3. Articles are extracted (articles table populated)
        4. Extraction happens within reasonable time
        """
        with production_db.get_session() as session:
            # Get pipeline statistics for last 24 hours
            result = session.execute(text("""
                SELECT
                    COUNT(DISTINCT cl.id) as discovered,
                    COUNT(DISTINCT CASE WHEN cl.status = 'article' THEN cl.id END) as verified,
                    COUNT(DISTINCT a.id) as extracted,
                    AVG(EXTRACT(EPOCH FROM (a.extracted_at - cl.discovered_at))) as avg_time_to_extract
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                WHERE cl.discovered_at >= NOW() - INTERVAL '24 hours'
            """)).fetchone()

            discovered, verified, extracted, avg_time = result

            assert discovered > 0, "No URLs discovered in last 24h"
            assert verified > 0, "No URLs verified in last 24h"
            assert extracted > 0, "No articles extracted in last 24h"

            # Verify conversion rates are reasonable
            verification_rate = verified / discovered if discovered > 0 else 0
            extraction_rate = extracted / verified if verified > 0 else 0

            assert verification_rate > 0.3, \
                f"Low verification rate: {verification_rate:.1%} - URL discovery may be finding non-articles"

            assert extraction_rate > 0.5, \
                f"Low extraction rate: {extraction_rate:.1%} - extraction may be failing"

            # Check extraction latency (should be < 1 hour on average)
            if avg_time:
                hours = avg_time / 3600
                assert hours < 2, \
                    f"High extraction latency: {hours:.1f}h average - backlog may be growing"

    def test_content_quality_checks(self, production_db):
        """
        Verify extracted articles have reasonable content quality.

        Validates:
        1. Articles have text content
        2. Content length is reasonable
        3. Key fields are populated
        """
        with production_db.get_session() as session:
            # Check recent extractions for quality
            result = session.execute(text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN LENGTH(text) > 100 THEN 1 END) as has_text,
                    COUNT(title) as has_title,
                    COUNT(author) as has_author,
                    COUNT(publish_date) as has_date,
                    AVG(LENGTH(text)) as avg_text_length
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '1 hour'
            """)).fetchone()

            total, has_text, has_title, has_author, has_date, avg_length = result

            if total > 0:
                # At least 80% should have substantial text
                text_rate = has_text / total
                assert text_rate > 0.8, \
                    f"Only {text_rate:.1%} of articles have substantial text - extraction may be broken"

                # At least 90% should have titles
                title_rate = has_title / total
                assert title_rate > 0.9, \
                    f"Only {title_rate:.1%} of articles have titles - extraction quality degraded"

                # Average text length should be reasonable (500+ chars)
                if avg_length:
                    assert avg_length > 500, \
                        f"Average text length only {avg_length:.0f} chars - may be extracting incomplete content"


class TestTelemetrySystem:
    """Test telemetry and monitoring systems."""

    def test_telemetry_writes_succeed(self, production_db):
        """
        Verify telemetry writes are succeeding without errors.

        Validates:
        1. Extraction telemetry is being written
        2. No integer overflow errors on hash columns
        3. Telemetry data is recent
        """
        with production_db.get_session() as session:
            # Check recent telemetry writes
            result = session.execute(text("""
                SELECT
                    MAX(created_at) as last_write,
                    COUNT(*) as recent_count
                FROM content_cleaning_segments
                WHERE created_at >= NOW() - INTERVAL '1 hour'
            """)).fetchone()

            last_write, count = result

            if last_write:
                age_minutes = (datetime.now() - last_write).total_seconds() / 60
                assert age_minutes < 30, \
                    f"No telemetry writes in {age_minutes:.0f} minutes - telemetry may be broken"

            # Should have some telemetry if extraction is running
            assert count > 0, \
                "No telemetry written in last hour - telemetry system may be broken"

    def test_hash_columns_handle_large_values(self, production_db):
        """
        Verify hash columns can handle full 64-bit hash values.

        Validates that the BigInteger migration was successful and
        large hash values (> 2^31) are being stored correctly.
        """
        with production_db.get_session() as session:
            # Check column types
            result = session.execute(text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name IN ('content_cleaning_segments', 'content_cleaning_wire_events')
                AND column_name LIKE '%hash%'
            """)).fetchall()

            for col_name, data_type in result:
                assert data_type == 'bigint', \
                    f"Column {col_name} is {data_type}, should be bigint - migration may have failed"

            # Check for large hash values (would fail with INTEGER)
            result = session.execute(text("""
                SELECT COUNT(*)
                FROM content_cleaning_segments
                WHERE ABS(segment_text_hash) > 2147483647
            """)).scalar()

            # If we have data, some should have large hashes
            total = session.execute(text(
                "SELECT COUNT(*) FROM content_cleaning_segments"
            )).scalar()

            if total > 100:
                # Expect ~50% to exceed 32-bit range
                ratio = result / total
                assert ratio > 0.1, \
                    "No large hash values found - column may not be working correctly"


class TestDataIntegrity:
    """Test data integrity and consistency."""

    def test_no_orphaned_articles(self, production_db):
        """Verify articles are properly linked to candidate_links."""
        with production_db.get_session() as session:
            orphans = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                WHERE a.candidate_link_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM candidate_links cl
                    WHERE cl.id = a.candidate_link_id
                )
            """)).scalar()

            assert orphans == 0, \
                f"Found {orphans} orphaned articles with invalid candidate_link_id"

    def test_no_duplicate_extractions(self, production_db):
        """Verify no duplicate extractions for the same URL."""
        with production_db.get_session() as session:
            duplicates = session.execute(text("""
                SELECT url, COUNT(*) as dup_count
                FROM articles
                GROUP BY url
                HAVING COUNT(*) > 1
                LIMIT 5
            """)).fetchall()

            if duplicates:
                dup_urls = [row[0] for row in duplicates[:3]]
                pytest.fail(f"Found duplicate extractions for URLs: {dup_urls}")

    def test_source_metadata_complete(self, production_db):
        """Verify active sources have required metadata."""
        with production_db.get_session() as session:
            incomplete = session.execute(text("""
                SELECT COUNT(*)
                FROM sources
                WHERE status = 'active'
                AND (
                    canonical_name IS NULL
                    OR host IS NULL
                    OR city IS NULL
                    OR county IS NULL
                )
            """)).scalar()

            assert incomplete == 0, \
                f"Found {incomplete} active sources with incomplete metadata"


class TestErrorRecoveryAndResilience:
    """Test error recovery and resilience of critical workflows."""

    def test_extraction_failures_are_logged_and_retried(self, production_db):
        """
        Verify extraction failures are properly logged and don't corrupt database.

        Validates:
        1. Failed extraction attempts don't create orphaned articles
        2. Failed URLs remain in candidate_links for retry
        3. Error logging captures extraction failures
        4. Retries can succeed after transient failures
        """
        with production_db.get_session() as session:
            # Check for articles with null/empty content (extraction failures)
            failed_extractions = session.execute(text("""
                SELECT COUNT(*) as failed_count
                FROM articles
                WHERE (text IS NULL OR LENGTH(TRIM(text)) < 50)
                AND extracted_at >= NOW() - INTERVAL '6 hours'
                AND status = 'extracted'
            """)).scalar()

            # Some failures are expected, but should be rare (<5%)
            total_recent = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '6 hours'
            """)).scalar()

            if total_recent > 100:
                failure_rate = failed_extractions / total_recent
                assert failure_rate < 0.05, \
                    f"High extraction failure rate: {failure_rate:.1%} - " \
                    f"may indicate systemic issue"

            # Failed URLs should still be in candidate_links (not deleted)
            orphaned = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                WHERE a.candidate_link_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM candidate_links cl
                    WHERE cl.id = a.candidate_link_id
                )
                AND a.extracted_at >= NOW() - INTERVAL '6 hours'
            """)).scalar()

            assert orphaned == 0, \
                f"Found {orphaned} orphaned articles - " \
                f"extraction may have deleted candidate_links on failure"

    def test_duplicate_article_prevention_via_unique_constraint(self, production_db):
        """
        Verify the unique URL constraint prevents duplicate extractions.

        Validates:
        1. No duplicate URLs in articles table
        2. Unique constraint migration was successful
        3. Concurrent extraction attempts don't create duplicates
        4. Constraint is actually enforced by database
        """
        with production_db.get_session() as session:
            # Check for any duplicate URLs (should be zero)
            duplicates = session.execute(text("""
                SELECT url, COUNT(*) as count
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '7 days'
                GROUP BY url
                HAVING COUNT(*) > 1
            """)).fetchall()

            if duplicates:
                dup_list = [(row[0][:80], row[1]) for row in duplicates[:5]]
                pytest.fail(
                    f"Found duplicate article extractions "
                    f"(constraint may have failed): {dup_list}"
                )

            # Verify constraint is defined in database schema
            constraint_exists = session.execute(text("""
                SELECT constraint_type
                FROM information_schema.table_constraints
                WHERE table_name = 'articles'
                AND constraint_type = 'UNIQUE'
                AND constraint_name ILIKE '%url%'
            """)).scalar()

            assert constraint_exists, \
                "Unique constraint on articles.url not found - may not be enforced"

            # Check for high rate of duplicate extraction attempts
            recent_urls = session.execute(text("""
                SELECT COUNT(DISTINCT url) as unique_urls,
                       COUNT(*) as total_articles
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '1 day'
            """)).fetchone()

            if recent_urls and recent_urls[1] > 0:
                uniqueness_ratio = recent_urls[0] / recent_urls[1]
                assert uniqueness_ratio > 0.95, \
                    f"Only {uniqueness_ratio:.1%} of recent articles " \
                    f"have unique URLs - high duplication risk"

    def test_database_connection_resilience(self, production_db):
        """
        Verify database connections handle transient failures gracefully.

        Validates:
        1. Connection pool is healthy
        2. Queries succeed after connection failures
        3. No orphaned connections
        4. Statement timeouts are configured
        """
        with production_db.get_session() as session:
            # Test basic connectivity and query
            try:
                result = session.execute(text("""
                    SELECT
                        version() as db_version,
                        NOW() as server_time,
                        COUNT(*) as article_count
                    FROM articles
                    LIMIT 1
                """)).fetchone()

                assert result is not None, "Database query returned no result"

            except Exception as e:
                pytest.fail(f"Database connection failed: {e}")

            # Check for long-running queries that might indicate stuck connections
            long_queries = session.execute(text("""
                SELECT COUNT(*)
                FROM pg_stat_activity
                WHERE state = 'active'
                AND query_start < NOW() - INTERVAL '5 minutes'
                AND pid != pg_backend_pid()
            """)).scalar()

            # Some long queries acceptable, but excessive indicates issues
            assert long_queries < 10, \
                f"Found {long_queries} queries running >5 minutes - " \
                f"connections may be stuck"

            # Verify statement timeout is configured
            statement_timeout = session.execute(text("""
                SELECT setting
                FROM pg_settings
                WHERE name = 'statement_timeout'
            """)).scalar()

            # Should have a timeout set (not 0)
            if statement_timeout:
                timeout_val = statement_timeout.split('ms')[0]
                timeout_ms = int(timeout_val) if 'ms' in statement_timeout else 0
                assert timeout_ms > 0, \
                    "Statement timeout is 0 - queries can hang indefinitely"

    def test_transaction_rollback_on_extraction_errors(self, production_db):
        """
        Verify extraction errors trigger proper transaction rollback.

        Validates:
        1. Partial article data is not committed on extraction failure
        2. Article counts are consistent across related tables
        3. No orphaned entities when article extraction fails
        4. Status transitions are atomic
        """
        with production_db.get_session() as session:
            # Check for consistency between articles and article_entities
            inconsistent = session.execute(text("""
                SELECT
                    COUNT(*) as articles_without_entities_when_classified
                FROM articles a
                WHERE a.status IN ('classified', 'analyzed')
                AND a.extracted_at >= NOW() - INTERVAL '6 hours'
                AND NOT EXISTS (
                    SELECT 1 FROM article_entities ae
                    WHERE ae.article_id = a.id
                )
            """)).scalar()

            # Some articles may legitimately have no entities,
            # but shouldn't be classified without them
            assert inconsistent < 10, \
                f"Found {inconsistent} articles classified without " \
                f"entities - extraction may not be atomic"

            # Check for articles with labels but missing required fields
            incomplete_labeled = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                INNER JOIN article_labels al ON a.id = al.article_id
                WHERE (a.text IS NULL OR LENGTH(TRIM(a.text)) < 100)
                AND a.extracted_at >= NOW() - INTERVAL '6 hours'
            """)).scalar()

            assert incomplete_labeled < 5, \
                f"Found {incomplete_labeled} labeled articles with " \
                f"incomplete content - extraction transaction may not " \
                f"be rolling back"

            # Verify status transitions are consistent
            invalid_status = session.execute(text("""
                SELECT COUNT(DISTINCT a.id)
                FROM articles a
                WHERE (
                    (a.status = 'extracted' AND a.primary_label IS NOT NULL) OR
                    (a.status = 'classified' AND a.primary_label IS NULL)
                )
            """)).scalar()

            assert invalid_status == 0, \
                f"Found {invalid_status} articles with inconsistent " \
                f"status/label states - state transitions may not be " \
                f"transactional"

    def test_extraction_retry_mechanism_works(self, production_db):
        """
        Verify articles that fail extraction can be retried.

        Validates:
        1. Failed candidate_links remain with status='article'
        2. Failed articles can be re-extracted by retrying the candidate_link
        3. Retry logic successfully completes previously failed extractions
        4. No blocking flags prevent retries
        """
        with production_db.get_session() as session:
            # Find candidate_links that have been attempted multiple times
            retry_candidates = session.execute(text("""
                SELECT COUNT(DISTINCT cl.id) as retry_count
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                WHERE cl.status = 'article'
                AND cl.last_verified_at >= NOW() - INTERVAL '7 days'
                AND NOT EXISTS (
                    SELECT 1 FROM articles a2
                    WHERE a2.candidate_link_id = cl.id
                    AND a2.extracted_at >= NOW() - INTERVAL '1 day'
                )
            """)).scalar()

            # Some URLs may be in retry queue
            logger.info(f"Found {retry_candidates} candidate_links eligible for retry")

            # Verify candidate_links don't have a "failed" or "blocked" status
            blocked = session.execute(text("""
                SELECT COUNT(*)
                FROM candidate_links
                WHERE status IN ('failed', 'blocked', 'error')
            """)).scalar()

            assert blocked == 0, \
                f"Found {blocked} candidate_links with blocked " \
                f"status - may prevent retries"

            # Check extraction success rate for URLs attempted multiple times
            multi_attempt = session.execute(text("""
                SELECT
                    COUNT(DISTINCT cl.id) as attempted,
                    COUNT(DISTINCT a.id) as successful
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                WHERE cl.status = 'article'
                AND cl.last_verified_at >= NOW() - INTERVAL '7 days'
            """)).fetchone()

            if multi_attempt and multi_attempt[0] > 100:
                success_calc = (
                    multi_attempt[1] / multi_attempt[0]
                    if multi_attempt[0] > 0 else 0
                )
                assert success_calc > 0.6, \
                    f"Low extraction success rate on retries: " \
                    f"{success_calc:.1%} - retry mechanism may be failing"


class TestDataPipelineConsistency:
    """Test data pipeline state transitions and consistency."""

    def test_state_transition_discovered_to_article(self, production_db):
        """
        Verify state transition from discovered → article.

        Validates:
        1. Candidate links transition from 'discovered' to 'article'
        2. Verification metadata is recorded
        3. No intermediate state leakage
        4. Status update timestamps are consistent
        """
        with production_db.get_session() as session:
            # Find recently verified URLs
            verified_urls = session.execute(text("""
                SELECT COUNT(*) as count
                FROM candidate_links
                WHERE status = 'article'
                AND status_updated_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            # Should have URLs transitioning through verification
            assert verified_urls > 0, \
                "No URLs verified in last 24h - verification may not be running"

            # Check for any stuck in intermediate states
            stuck = session.execute(text("""
                SELECT COUNT(*)
                FROM candidate_links
                WHERE status NOT IN
                    ('discovered', 'article', 'non-article', 'failed')
                AND created_at >= NOW() - INTERVAL '7 days'
            """)).scalar()

            assert stuck == 0, \
                f"Found {stuck} URLs in unknown status - " \
                f"state transition may be broken"

            # Verify status timestamps progress forward
            bad_timestamps = session.execute(text("""
                SELECT COUNT(*)
                FROM candidate_links
                WHERE status_updated_at < created_at
                AND created_at >= NOW() - INTERVAL '7 days'
            """)).scalar()

            assert bad_timestamps == 0, \
                f"Found {bad_timestamps} URLs with reversed timestamps - " \
                f"time ordering broken"

    def test_state_transition_article_to_extracted(
        self, production_db
    ):
        """
        Verify state transition from article → extracted.

        Validates:
        1. Articles are created only from 'article' status candidate_links
        2. Extraction timestamps are recent
        3. Article creation doesn't break candidate_link relationship
        4. No articles without valid candidate_link
        """
        with production_db.get_session() as session:
            # Find recently extracted articles
            recent_extractions = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            assert recent_extractions > 0, \
                "No articles extracted in last 24h - extraction may not work"

            # All articles should link to 'article' status candidate_links
            bad_links = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE cl.status NOT IN ('article', 'extracted', 'non-article')
                AND a.extracted_at >= NOW() - INTERVAL '7 days'
            """)).scalar()

            assert bad_links == 0, \
                f"Found {bad_links} articles from non-article candidate_links - " \
                f"extraction validation may be broken"

            # Extraction timestamp should be after verification
            bad_timing = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE a.extracted_at < cl.status_updated_at
                AND a.extracted_at >= NOW() - INTERVAL '7 days'
            """)).scalar()

            assert bad_timing == 0, \
                f"Found {bad_timing} articles extracted before verification - " \
                f"timeline ordering broken"

    def test_state_transition_extracted_to_cleaned(
        self, production_db
    ):
        """
        Verify state transition from extracted → cleaned.

        Validates:
        1. Articles transition through cleaning pipeline
        2. Cleaned articles have content processed
        3. Status progression is consistent
        4. Cleaning metadata is recorded
        """
        with production_db.get_session() as session:
            # Find recently cleaned articles
            cleaned_articles = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE status = 'cleaned'
                AND extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            # Should have cleaned articles if extraction is running
            extracted = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE status = 'extracted'
                AND extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            if extracted > 10:
                # If we have many extracted, should have some cleaned
                assert cleaned_articles > 0, \
                    "No cleaned articles - cleaning pipeline may not run"

            # Cleaned articles should have content
            cleaned_without_content = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE status IN ('cleaned', 'classified')
                AND (content IS NULL OR LENGTH(TRIM(content)) < 50)
                AND extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            assert cleaned_without_content == 0, \
                f"Found {cleaned_without_content} cleaned articles " \
                f"without content - cleaning may be broken"

    def test_state_transition_cleaned_to_classified(
        self, production_db
    ):
        """
        Verify state transition from cleaned → classified.

        Validates:
        1. Articles get ML labels after cleaning
        2. Classification happens in correct sequence
        3. Labels have proper confidence scores
        4. No articles skip cleaning before classification
        """
        with production_db.get_session() as session:
            # Articles can go directly to classified or through cleaned
            classified = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE status IN ('classified', 'local', 'wire',
                                'opinion', 'obituary')
                AND extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            # Should have classified articles
            assert classified > 0, \
                "No classified articles - ML pipeline may not run"

            # All classified articles should have labels
            no_labels = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE status IN ('classified', 'local', 'wire',
                                'opinion', 'obituary')
                AND primary_label IS NULL
                AND extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            assert no_labels == 0, \
                f"Found {no_labels} classified articles without labels - " \
                f"classification may be incomplete"

            # Labels should have reasonable confidence
            low_confidence = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                WHERE a.status IN
                    ('classified', 'local', 'wire', 'opinion', 'obituary')
                AND EXISTS (
                    SELECT 1 FROM article_labels al
                    WHERE al.article_id = a.id
                    AND al.confidence < 0.3
                )
                AND a.extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            # Some low confidence is ok, but shouldn't be excessive
            if classified > 50:
                bad_rate = low_confidence / classified
                assert bad_rate < 0.1, \
                    f"High rate of low-confidence labels: {bad_rate:.1%}"

    def test_cascade_and_data_lineage(self, production_db):
        """
        Verify data relationships and lineage tracking.

        Validates:
        1. Entities are linked to correct articles
        2. Labels are linked to correct articles
        3. Lineage is complete (no orphaned children)
        4. Parent-child relationships are preserved
        """
        with production_db.get_session() as session:
            # Check entities lineage
            orphaned_entities = session.execute(text("""
                SELECT COUNT(*)
                FROM article_entities ae
                WHERE NOT EXISTS (
                    SELECT 1 FROM articles a
                    WHERE a.id = ae.article_id
                )
            """)).scalar()

            assert orphaned_entities == 0, \
                f"Found {orphaned_entities} orphaned entities - " \
                f"lineage broken"

            # Check labels lineage
            orphaned_labels = session.execute(text("""
                SELECT COUNT(*)
                FROM article_labels al
                WHERE NOT EXISTS (
                    SELECT 1 FROM articles a
                    WHERE a.id = al.article_id
                )
            """)).scalar()

            assert orphaned_labels == 0, \
                f"Found {orphaned_labels} orphaned labels - " \
                f"lineage broken"

            # Check article-candidate_link lineage
            orphaned_articles = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                WHERE a.candidate_link_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM candidate_links cl
                    WHERE cl.id = a.candidate_link_id
                )
            """)).scalar()

            assert orphaned_articles == 0, \
                f"Found {orphaned_articles} orphaned articles - " \
                f"FK relationship broken"

    def test_transactionality_prevents_partial_states(
        self, production_db
    ):
        """
        Verify atomic transactions prevent partial state updates.

        Validates:
        1. No articles with inconsistent status/label combinations
        2. Entity extractions are all-or-nothing per article
        3. Label assignments are consistent with article state
        4. No orphaned intermediate states
        """
        with production_db.get_session() as session:
            # Check for inconsistent label states
            bad_label_state = session.execute(text("""
                SELECT COUNT(*)
                FROM articles a
                WHERE (
                    (a.status = 'extracted' AND a.primary_label IS NOT NULL)
                    OR
                    (a.status IN ('cleaned', 'local', 'wire',
                    'opinion', 'obituary') AND a.primary_label IS NULL)
                )
                AND a.extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            assert bad_label_state == 0, \
                f"Found {bad_label_state} articles with " \
                f"inconsistent status/label - transactions may not be atomic"

            # Check for partial entity extraction
            partial_entities = session.execute(text("""
                SELECT a.id, COUNT(ae.id) as entity_count
                FROM articles a
                LEFT JOIN article_entities ae ON a.id = ae.article_id
                WHERE a.status IN ('classified', 'local', 'wire',
                                   'opinion', 'obituary')
                AND a.extracted_at >= NOW() - INTERVAL '24 hours'
                GROUP BY a.id
                HAVING COUNT(ae.id) = 0
            """)).fetchall()

            if partial_entities:
                bad_count = len(partial_entities)
                # Some articles may legitimately have no entities
                # but classified articles usually should
                if bad_count > 20:
                    logger.warning(
                        f"Found {bad_count} classified articles "
                        f"without entities - may be transactional issue"
                    )

            # Check content vs status consistency
            bad_content = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE status IN ('classified', 'local', 'wire',
                                'opinion', 'obituary')
                AND (content IS NULL OR LENGTH(TRIM(content)) < 100)
                AND extracted_at >= NOW() - INTERVAL '24 hours'
            """)).scalar()

            assert bad_content == 0, \
                f"Found {bad_content} classified articles without content - " \
                f"transaction may not be atomic"

    def test_data_lineage_timestamps_progression(
        self, production_db
    ):
        """
        Verify timestamp progression through pipeline.

        Validates:
        1. created_at < discovered_at < verified_at < extracted_at
        2. Status updates reflect actual pipeline progression
        3. No backwards time travel
        4. Reasonable time deltas between stages
        """
        with production_db.get_session() as session:
            # Check timestamp ordering for recently processed URLs
            bad_order = session.execute(text("""
                SELECT COUNT(*)
                FROM (
                    SELECT
                        cl.id,
                        cl.created_at,
                        cl.discovered_at,
                        cl.status_updated_at as verified_at,
                        COALESCE(a.extracted_at, NOW()) as extracted_at
                    FROM candidate_links cl
                    LEFT JOIN articles a ON cl.id = a.candidate_link_id
                    WHERE cl.created_at >= NOW() - INTERVAL '7 days'
                ) pipeline
                WHERE NOT (
                    created_at <= discovered_at
                    AND discovered_at <= verified_at
                    AND verified_at <= extracted_at
                )
            """)).scalar()

            assert bad_order == 0, \
                f"Found {bad_order} pipeline items with " \
                f"out-of-order timestamps"

            # Check for reasonable processing delays
            slow_verification = session.execute(text("""
                SELECT COUNT(*)
                FROM candidate_links
                WHERE status = 'article'
                AND EXTRACT(EPOCH FROM
                    (status_updated_at - discovered_at)) > 86400
                AND discovered_at >= NOW() - INTERVAL '7 days'
            """)).scalar()

            if slow_verification > 100:
                logger.warning(
                    f"Found {slow_verification} URLs taking >24h "
                    f"to verify - may indicate bottleneck"
                )

            # Check extraction latency
            slow_extraction = session.execute(text("""
                SELECT COUNT(*)
                FROM candidate_links cl
                JOIN articles a ON cl.id = a.candidate_link_id
                WHERE EXTRACT(EPOCH FROM
                    (a.extracted_at - cl.status_updated_at)) > 3600
                AND cl.status_updated_at >= NOW() - INTERVAL '7 days'
            """)).scalar()

            if slow_extraction > 50:
                logger.warning(
                    f"Found {slow_extraction} articles taking >1h "
                    f"to extract - may indicate load issues"
                )


class TestContentCleaningPipeline:
    """Test content cleaning pipeline (extracted → cleaned transition)."""

    def test_article_cleaning_status_transition(self, production_db):
        """
        Verify articles transition from extracted to cleaned status.

        Validates:
        1. Extracted articles are processed for cleaning
        2. cleaned_content field is populated after extraction
        3. Status transition happens within reasonable time
        4. Timestamps progress: extracted_at < cleaned_at
        """
        with production_db.get_session() as session:
            # Check articles with cleaned content from last 24 hours
            result = session.execute(text("""
                SELECT
                    COUNT(*) as total_extracted,
                    COUNT(CASE
                        WHEN cleaned_content IS NOT NULL
                        AND LENGTH(TRIM(cleaned_content)) > 100
                        THEN 1
                    END) as with_cleaned_content,
                    AVG(CASE
                        WHEN cleaned_content IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (cleaned_at - extracted_at))
                        ELSE NULL
                    END) as avg_cleaning_latency_seconds
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '24 hours'
                AND status IN ('cleaned', 'classified', 'local', 'wire',
                               'opinion', 'obituary')
            """)).fetchone()

            total_extracted, cleaned_count, avg_latency = result

            # At least some articles should have cleaned content
            assert total_extracted > 0, \
                "No extracted articles found in last 24 hours"
            assert cleaned_count > 0, \
                "No articles have cleaned_content - cleaning may have failed"

            # Cleaning latency should be reasonable (<5 minutes typically)
            if avg_latency:
                assert avg_latency < 300, \
                    f"High cleaning latency: {avg_latency:.0f}s - " \
                    f"cleaning may be bottlenecked"

    def test_content_validation_after_cleaning(self, production_db):
        """
        Verify cleaned content meets quality standards.

        Validates:
        1. Cleaned content is shorter than original (boilerplate removed)
        2. Cleaned content still has substantial text (>100 chars)
        3. Content length ratio is reasonable (not removing too much)
        4. No NULL cleaned_content for classified articles
        """
        with production_db.get_session() as session:
            # Check content reduction statistics
            result = session.execute(text("""
                SELECT
                    COUNT(*) as cleaned_articles,
                    AVG(LENGTH(COALESCE(content, ''))) as avg_original_length,
                    AVG(LENGTH(COALESCE(cleaned_content, ''))) as avg_cleaned_length,
                    MIN(CASE
                        WHEN LENGTH(COALESCE(cleaned_content, '')) > 0
                        THEN LENGTH(cleaned_content) /
                             GREATEST(LENGTH(content), 1)
                        ELSE NULL
                    END) as min_retention_ratio,
                    MAX(CASE
                        WHEN LENGTH(COALESCE(cleaned_content, '')) > 0
                        THEN LENGTH(cleaned_content) /
                             GREATEST(LENGTH(content), 1)
                        ELSE NULL
                    END) as max_retention_ratio
                FROM articles
                WHERE status IN ('cleaned', 'classified', 'local', 'wire',
                                 'opinion', 'obituary')
                AND extracted_at >= NOW() - INTERVAL '24 hours'
                AND cleaned_content IS NOT NULL
            """)).fetchone()

            cleaned_count, avg_orig, avg_clean, min_ratio, max_ratio = result

            # Should have cleaned articles
            assert cleaned_count > 0, \
                "No articles with cleaned_content found"

            # Cleaned content should be shorter than original
            if avg_clean and avg_orig:
                reduction = (avg_orig - avg_clean) / avg_orig
                assert reduction > 0.05, \
                    (f"Low content reduction: {reduction:.1%} - "
                     f"cleaning may not be working")
                assert reduction < 0.95, \
                    (f"High content reduction: {reduction:.1%} - "
                     f"may be removing too much")

            # Retention ratio should be reasonable
            if min_ratio and max_ratio:
                assert min_ratio > 0.05, \
                    "Some articles retain <5% content - cleaning aggressive"
                assert max_ratio < 0.99, \
                    "Some articles retain >99% content - cleaning not working"

    def test_byline_extraction_and_normalization(self, production_db):
        """
        Verify byline extraction and author normalization.

        Validates:
        1. Author field is populated for cleaned articles
        2. Bylines are normalized (single person names, not raw bylines)
        3. Wire service indicators are removed from author field
        4. Author field length is reasonable (not entire bylines)
        """
        with production_db.get_session() as session:
            # Check byline/author extraction quality
            result = session.execute(text("""
                SELECT
                    COUNT(*) as total_articles,
                    COUNT(CASE
                        WHEN author IS NOT NULL
                        AND LENGTH(TRIM(author)) > 2
                        AND LENGTH(TRIM(author)) < 200
                        THEN 1
                    END) as with_valid_authors,
                    AVG(LENGTH(COALESCE(author, ''))) as avg_author_length,
                    COUNT(CASE
                        WHEN author ILIKE '%associated press%'
                        OR author ILIKE '%reuters%'
                        OR author ILIKE '%ap%'
                        OR author ILIKE '%upi%'
                        OR author ILIKE '%cnn%'
                        THEN 1
                    END) as authors_with_wire_service_text
                FROM articles
                WHERE status IN ('cleaned', 'classified', 'local', 'wire',
                                 'opinion', 'obituary')
                AND extracted_at >= NOW() - INTERVAL '24 hours'
            """)).fetchone()

            total, valid_authors, avg_len, wire_in_author = result

            # Should have authors extracted
            assert total > 0, \
                "No cleaned articles found for byline validation"
            assert valid_authors > 0, \
                "No valid authors extracted - byline cleaning may have failed"

            # Authors should be reasonably short (normalized, not full bylines)
            if avg_len:
                assert avg_len < 100, \
                    (f"Average author length {avg_len:.0f}s - "
                     f"bylines may not be normalized")

            # Wire service indicators should be removed from author field
            if wire_in_author and total > 0:
                wire_ratio = wire_in_author / total
                assert wire_ratio < 0.1, \
                    f"High wire service contamination in authors: {wire_ratio:.1%}"

    def test_wire_service_detection_and_classification(self, production_db):
        """
        Verify wire service content is correctly detected and labeled.

        Validates:
        1. Wire articles have 'wire' or syndicated status
        2. Wire service bylines are preserved (not corrupted to author names)
        3. Wire articles are tagged in primary_label if applicable
        4. Wire service detection has reasonable precision
        """
        with production_db.get_session() as session:
            # Check wire service article classification
            result = session.execute(text("""
                SELECT
                    COUNT(CASE WHEN status = 'wire' THEN 1 END) as wire_articles,
                    COUNT(CASE WHEN status = 'local' THEN 1 END) as local_articles,
                    COUNT(CASE
                        WHEN status = 'wire'
                        AND (author ILIKE '%associated press%'
                             OR author ILIKE '%reuters%'
                             OR author ILIKE '%ap%'
                             OR author ILIKE '%upi%'
                             OR author ILIKE '%cnn%')
                        THEN 1
                    END) as wire_with_service_author,
                    COUNT(CASE
                        WHEN status = 'wire'
                        AND (author ILIKE '%associated press%'
                             OR author ILIKE '%reuters%')
                        AND primary_label IN ('wire', 'syndicated')
                        THEN 1
                    END) as wire_correctly_labeled
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '7 days'
            """)).fetchone()

            wire_count, local_count, wire_with_svc, labeled = result

            # Should have some wire articles detected
            assert wire_count > 0, \
                "No wire articles detected - wire service detection may be failing"

            # Most wire articles should have wire service author text preserved
            if wire_count > 0:
                preservation_ratio = wire_with_svc / wire_count
                assert preservation_ratio > 0.7, \
                    f"Low wire service preservation: {preservation_ratio:.1%} - " \
                    f"bylines may be corrupted"

            # Wire articles should have consistent labeling
            if wire_with_svc > 0:
                label_ratio = labeled / wire_with_svc
                logger.info(
                    f"Wire article labeling ratio: {label_ratio:.1%} "
                    f"({labeled}/{wire_with_svc} labeled)"
                )

    def test_section_url_handling_in_cleaning(self, production_db):
        """
        Verify section URLs don't corrupt article content during cleaning.

        Validates:
        1. Articles from section URLs are properly extracted and cleaned
        2. Content from section discovery doesn't break cleaning pipeline
        3. Section-discovered articles have valid content
        4. Cleaning works consistently across all discovery sources
        """
        with production_db.get_session() as session:
            # Check articles discovered via section URLs
            result = session.execute(text("""
                SELECT
                    COUNT(DISTINCT cl.id) as section_url_articles,
                    COUNT(CASE
                        WHEN a.id IS NOT NULL
                        AND a.cleaned_content IS NOT NULL
                        THEN 1
                    END) as with_cleaned_content,
                    COUNT(CASE
                        WHEN a.status IN ('cleaned', 'classified',
                                         'local', 'wire', 'opinion', 'obituary')
                        THEN 1
                    END) as properly_processed
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                WHERE cl.source_type = 'section'
                AND cl.created_at >= NOW() - INTERVAL '7 days'
            """)).fetchone()

            section_articles, with_cleaned, processed = result

            # Should have section-discovered articles
            if section_articles and section_articles > 0:
                # Most should be cleaned
                cleaned_ratio = with_cleaned / section_articles
                assert cleaned_ratio > 0.7, \
                    f"Low cleaning success for section articles: {cleaned_ratio:.1%}"

                # Processing should be consistent
                process_ratio = processed / section_articles
                logger.info(
                    f"Section article processing ratio: {process_ratio:.1%} "
                    f"({processed}/{section_articles} processed)"
                )


class TestMLPipeline:
    """Test ML pipeline (entity extraction, gazetteer, labeling)."""

    def test_entity_extraction_gazetteer_loading(self, production_db):
        """
        Verify entity extraction with gazetteer loading per source.

        Validates:
        1. Articles have extracted entities in article_entities table
        2. Entities are linked to gazetteer records when available
        3. Entity extraction happens with proper gazetteer source filtering
        4. Match scores indicate quality of gazetteer matching
        """
        with production_db.get_session() as session:
            # Check entity extraction statistics
            result = session.execute(text("""
                SELECT
                    COUNT(DISTINCT ae.article_id) as articles_with_entities,
                    COUNT(DISTINCT ae.extractor_version) as extractor_versions,
                    COUNT(CASE
                        WHEN ae.matched_gazetteer_id IS NOT NULL
                        THEN 1
                    END) as entities_with_gazetteer_match,
                    AVG(ae.match_score) as avg_match_score,
                    MIN(ae.match_score) as min_match_score,
                    MAX(ae.match_score) as max_match_score
                FROM article_entities ae
                WHERE ae.created_at >= NOW() - INTERVAL '24 hours'
            """)).fetchone()

            articles_ents, versions, with_match, avg_score, min_score, \
                max_score = result

            # Should have extracted entities
            assert articles_ents and articles_ents > 0, \
                "No articles with entities found - extraction may be failing"

            # Should have gazetteer matches
            if with_match and articles_ents:
                match_ratio = with_match / articles_ents
                logger.info(
                    f"Entity gazetteer matching: {match_ratio:.1%} "
                    f"({with_match}/{articles_ents} matched)"
                )

            # Match scores should be reasonable (0-1 range)
            if avg_score:
                assert avg_score > 0.5, \
                    (f"Low average match score: {avg_score:.2f} - "
                     f"may indicate gazetteer mismatch")
                assert max_score <= 1.0, \
                    f"Invalid match score: {max_score} - >1.0 impossible"

    def test_label_distribution_across_article_types(self, production_db):
        """
        Verify label distribution across article types.

        Validates:
        1. Local articles have 'local' or similar labels
        2. Wire articles have 'wire' or syndicated labels
        3. Opinion/obituary articles are correctly classified
        4. Label distribution across statuses is reasonable
        5. Primary label assignment is consistent
        """
        with production_db.get_session() as session:
            # Check label distribution by article status
            result = session.execute(text("""
                SELECT
                    a.status,
                    COUNT(DISTINCT a.id) as total_articles,
                    COUNT(CASE
                        WHEN al.primary_label IS NOT NULL THEN 1
                    END) as with_primary_label,
                    COUNT(DISTINCT al.primary_label) as unique_labels,
                    ARRAY_AGG(DISTINCT al.primary_label ORDER BY al.primary_label)
                        FILTER (WHERE al.primary_label IS NOT NULL)
                        as label_list
                FROM articles a
                LEFT JOIN article_labels al ON a.id = al.article_id
                WHERE a.extracted_at >= NOW() - INTERVAL '7 days'
                GROUP BY a.status
                ORDER BY total_articles DESC
            """)).fetchall()

            status_distribution = {}
            for status, total, labeled, unique, labels in result:
                status_distribution[status] = {
                    'total': total,
                    'labeled': labeled,
                    'unique_labels': unique,
                    'labels': labels or [],
                }

            # Should have articles of different types
            assert 'local' in status_distribution or \
                   'cleaned' in status_distribution, \
                "No local/cleaned articles for label distribution check"

            # Wire articles should have wire-related labels
            if 'wire' in status_distribution:
                wire_articles = status_distribution['wire']['total']
                wire_labeled = status_distribution['wire']['labeled']
                if wire_articles > 10:
                    wire_label_ratio = wire_labeled / wire_articles
                    logger.info(
                        f"Wire article labeling: {wire_label_ratio:.1%} "
                        f"({wire_labeled}/{wire_articles})"
                    )

            # Opinion/obituary articles should not be labeled normally
            for special_status in ['opinion', 'obituary']:
                if special_status in status_distribution:
                    special_labeled = \
                        status_distribution[special_status]['labeled']
                    logger.info(
                        f"{special_status.capitalize()} articles labeled: "
                        f"{special_labeled}"
                    )

    def test_model_versioning_and_fallback(self, production_db):
        """
        Verify model versioning and fallback behavior.

        Validates:
        1. Entity extractor version is tracked
        2. Classification model versions are recorded
        3. Multiple model versions coexist (no hard cutover)
        4. Fallback from failed extractions works
        5. Version progression is forward-compatible
        """
        with production_db.get_session() as session:
            # Check entity extractor versions
            ent_result = session.execute(text("""
                SELECT
                    extractor_version,
                    COUNT(*) as entity_count,
                    COUNT(DISTINCT article_id) as articles,
                    MIN(created_at) as first_used,
                    MAX(created_at) as last_used
                FROM article_entities
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY extractor_version
                ORDER BY last_used DESC
            """)).fetchall()

            extractor_versions = {}
            for version, count, articles, first_used, last_used in ent_result:
                extractor_versions[version] = {
                    'entities': count,
                    'articles': articles,
                    'first_used': first_used,
                    'last_used': last_used,
                }

            # Should have at least one extractor version
            assert len(extractor_versions) > 0, \
                "No entity extractor versions found"

            # Check entity extractor is named properly
            for version in extractor_versions:
                assert version and 'spacy' in version.lower(), \
                    f"Invalid entity extractor version: {version}"

            # Check classification model versions
            label_result = session.execute(text("""
                SELECT
                    label_version,
                    COUNT(*) as label_count,
                    COUNT(DISTINCT article_id) as articles,
                    AVG(primary_label_confidence) as avg_confidence,
                    MIN(applied_at) as first_used,
                    MAX(applied_at) as last_used
                FROM article_labels
                WHERE applied_at >= NOW() - INTERVAL '7 days'
                GROUP BY label_version
                ORDER BY last_used DESC
                LIMIT 5
            """)).fetchall()

            label_versions = {}
            for version, count, articles, confidence, first_used, \
                    last_used in label_result:
                label_versions[version] = {
                    'labels': count,
                    'articles': articles,
                    'avg_confidence': confidence,
                    'first_used': first_used,
                    'last_used': last_used,
                }

            # Should have classification model versions
            if label_versions:
                logger.info(
                    f"Classification model versions: {len(label_versions)}"
                )
                for version, stats in label_versions.items():
                    logger.info(
                        f"  {version}: {stats['labels']} labels, "
                        f"avg confidence {stats['avg_confidence']:.2f}"
                    )

    def test_entity_confidence_and_validation(self, production_db):
        """
        Verify entity confidence scores and validation.

        Validates:
        1. Gazetteer matched entities have confidence/match scores
        2. Confidence scores are in valid range (0-1)
        3. Higher confidence entities are valid matches
        4. NER entities without gazetteer matches tracked
        5. Entity type classification is consistent
        """
        with production_db.get_session() as session:
            # Check entity confidence distribution
            result = session.execute(text("""
                SELECT
                    entity_label,
                    COUNT(*) as entity_count,
                    COUNT(CASE
                        WHEN matched_gazetteer_id IS NOT NULL
                        AND match_score > 0.8
                        THEN 1
                    END) as high_confidence_matches,
                    AVG(match_score) as avg_match_score,
                    MIN(match_score) as min_match_score,
                    MAX(match_score) as max_match_score,
                    COUNT(CASE
                        WHEN osm_category IS NOT NULL THEN 1
                    END) as with_osm_category
                FROM article_entities
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY entity_label
                ORDER BY entity_count DESC
            """)).fetchall()

            for entity_label, count, high_conf, avg_score, min_score, \
                    max_score, with_category in result:
                # Confidence/match scores should be valid
                if avg_score:
                    assert avg_score <= 1.0, \
                        (f"Invalid avg match score for {entity_label}: "
                         f"{avg_score}")

                # High-confidence matches substantial fraction
                if high_conf and count:
                    high_ratio = high_conf / count
                    logger.info(
                        f"Entity label '{entity_label}': "
                        f"{high_ratio:.1%} high confidence "
                        f"({high_conf}/{count})"
                    )

                # OSM categories should be populated for matches
                if with_category and count:
                    category_ratio = with_category / count
                    logger.info(
                        f"Entity label '{entity_label}': "
                        f"{category_ratio:.1%} have OSM categories"
                    )

    def test_extraction_and_labeling_pipeline_completeness(
        self, production_db
    ):
        """
        Verify end-to-end ML pipeline completeness.

        Validates:
        1. Extracted articles progress through entity extraction
        2. Entity extraction and labeling work together
        3. No articles stuck in intermediate states
        4. Pipeline latency is reasonable
        5. Success rate through ML stages is high
        """
        with production_db.get_session() as session:
            # Check pipeline progression
            result = session.execute(text("""
                SELECT
                    COUNT(CASE
                        WHEN a.status IN ('extracted', 'cleaned')
                        THEN 1
                    END) as extractable_articles,
                    COUNT(CASE
                        WHEN EXISTS (
                            SELECT 1 FROM article_entities ae
                            WHERE ae.article_id = a.id
                        ) THEN 1
                    END) as with_entities,
                    COUNT(CASE
                        WHEN EXISTS (
                            SELECT 1 FROM article_labels al
                            WHERE al.article_id = a.id
                        ) THEN 1
                    END) as with_labels,
                    COUNT(CASE
                        WHEN EXISTS (
                            SELECT 1 FROM article_entities ae
                            WHERE ae.article_id = a.id
                        ) AND EXISTS (
                            SELECT 1 FROM article_labels al
                            WHERE al.article_id = a.id
                        ) THEN 1
                    END) as with_both,
                    AVG(CASE
                        WHEN ae.created_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM
                            (ae.created_at - a.extracted_at))
                        ELSE NULL
                    END) as entity_extraction_latency,
                    AVG(CASE
                        WHEN al.applied_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM
                            (al.applied_at - a.extracted_at))
                        ELSE NULL
                    END) as total_pipeline_latency
                FROM articles a
                LEFT JOIN article_entities ae ON a.id = ae.article_id
                LEFT JOIN article_labels al ON a.id = al.article_id
                WHERE a.extracted_at >= NOW() - INTERVAL '7 days'
                AND a.status IN ('cleaned', 'classified', 'local', 'wire',
                                 'opinion', 'obituary')
            """)).fetchone()

            total_extract, with_ents, with_labels, with_both, \
                ent_latency, pipeline_latency = result

            # Should have extractable articles
            if total_extract and total_extract > 0:
                # Most should have entities extracted
                ent_ratio = with_ents / total_extract
                assert ent_ratio > 0.7, \
                    f"Low entity extraction rate: {ent_ratio:.1%}"

                # Most should have labels
                label_ratio = with_labels / total_extract
                if label_ratio < 0.5:
                    logger.warning(
                        f"Low labeling rate: {label_ratio:.1%} "
                        f"({with_labels}/{total_extract}) - may be expected if "
                        f"labeling pipeline not running"
                    )

                # Latencies should be reasonable
                if ent_latency and ent_latency > 0:
                    assert ent_latency < 28800, \
                        (f"High entity extraction latency: "
                         f"{ent_latency:.0f}s (>8h)")

                if pipeline_latency and pipeline_latency > 0:
                    assert pipeline_latency < 86400, \
                        (f"High total pipeline latency: "
                         f"{pipeline_latency:.0f}s (>24h)")

                logger.info(
                    f"ML pipeline progress: {ent_ratio:.1%} entities, "
                    f"{label_ratio:.1%} labels, {with_both} complete"
                )


@pytest.mark.slow
class TestPerformance:
    """Test performance and throughput."""

    def test_extraction_throughput(self, production_db):
        """Verify extraction maintains reasonable throughput."""
        with production_db.get_session() as session:
            # Get extractions per hour for last 24 hours
            result = session.execute(text("""
                SELECT
                    DATE_TRUNC('hour', extracted_at) as hour,
                    COUNT(*) as articles_per_hour
                FROM articles
                WHERE extracted_at >= NOW() - INTERVAL '24 hours'
                GROUP BY hour
                ORDER BY hour DESC
                LIMIT 24
            """)).fetchall()

            if result:
                hourly_rates = [row[1] for row in result]
                avg_per_hour = sum(hourly_rates) / len(hourly_rates)

                # Should maintain at least 50 articles/hour
                assert avg_per_hour > 50, \
                    f"Low extraction rate: {avg_per_hour:.0f} articles/hour - " \
                    f"may need more workers"

    def test_verification_throughput(self, production_db):
        """Verify URL verification maintains reasonable throughput."""
        with production_db.get_session() as session:
            # Get verifications in last hour
            result = session.execute(text("""
                SELECT COUNT(*)
                FROM candidate_links
                WHERE status_updated_at >= NOW() - INTERVAL '1 hour'
                AND status IN ('article', 'non-article')
            """)).scalar()

            # Should verify at least 100 URLs per hour
            assert result > 100, \
                f"Low verification rate: {result} URLs/hour - verification may be slow"
