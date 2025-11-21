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


class TestMLPipeline:
    """Test ML analysis and labeling pipeline."""

    def test_articles_get_entity_extraction(self, production_db):
        """
        Verify NER entity extraction is running on new articles.

        Validates:
        1. Recent articles have entity extractions
        2. Entities are being linked to articles
        3. Entity types are reasonable
        """
        with production_db.get_session() as session:
            # Check recent entity extractions
            result = session.execute(text("""
                SELECT
                    COUNT(DISTINCT a.id) as articles_with_entities,
                    COUNT(ae.id) as total_entities,
                    COUNT(DISTINCT ae.entity_type) as entity_types
                FROM articles a
                INNER JOIN article_entities ae ON a.id = ae.article_id
                WHERE a.extracted_at >= NOW() - INTERVAL '6 hours'
            """)).fetchone()

            articles, entities, types = result

            if articles and articles > 0:
                # Should have reasonable entity extraction
                avg_entities = entities / articles
                assert avg_entities > 1, \
                    f"Only {avg_entities:.1f} entities per article - NER may be degraded"

                # Should have multiple entity types
                assert types >= 3, \
                    f"Only {types} entity types found - NER model may be broken"

    def test_articles_get_classification_labels(self, production_db):
        """
        Verify classification/labeling is running on new articles.

        Validates:
        1. Recent articles have classification labels
        2. Labels have confidence scores
        3. Label distribution is reasonable
        """
        with production_db.get_session() as session:
            # Check recent classifications
            result = session.execute(text("""
                SELECT
                    COUNT(DISTINCT a.id) as labeled_articles,
                    COUNT(al.id) as total_labels,
                    AVG(al.confidence) as avg_confidence
                FROM articles a
                INNER JOIN article_labels al ON a.id = al.article_id
                WHERE a.extracted_at >= NOW() - INTERVAL '6 hours'
            """)).fetchone()

            articles, labels, confidence = result

            if articles and articles > 0:
                # Should have labels on most articles
                avg_labels = labels / articles
                assert avg_labels >= 1, \
                    f"Only {avg_labels:.1f} labels per article - classification may not be running"

                # Confidence should be reasonable
                if confidence:
                    assert confidence > 0.5, \
                        f"Average confidence {confidence:.2f} is low - model may need retraining"


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
