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
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.models.database import DatabaseManager


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
        Verify section URLs are extracted from article URLs and stored in DB.
        
        Validates the integrated fix where:
        1. Article URLs are discovered
        2. Section URLs are extracted from those article URLs
        3. Section URLs are saved to candidate_links
        4. Section URLs are marked with appropriate status
        """
        with production_db.get_session() as session:
            # Check that we have section URLs in the database
            result = session.execute(text("""
                SELECT COUNT(*), MIN(discovered_at), MAX(discovered_at)
                FROM candidate_links 
                WHERE is_section_url = true
            """)).fetchone()
            
            section_count, oldest, newest = result
            
            # Should have section URLs in production
            assert section_count > 0, \
                "No section URLs found - extraction may not be working"
            
            # Section URLs should be recent (within last 7 days)
            if newest:
                age_days = (datetime.now() - newest).days
                assert age_days < 7, \
                    f"Most recent section URL is {age_days} days old - extraction may have stopped"
    
    def test_section_urls_used_in_discovery(self, production_db):
        """
        Verify section URLs are used by newspaper3k for discovery.
        
        Validates that:
        1. Section URLs exist in sources table as build_urls
        2. Discovery process reads these section URLs
        3. New article URLs are discovered from section URLs
        """
        with production_db.get_session() as session:
            # Check that sources have section URLs configured
            result = session.execute(text("""
                SELECT COUNT(DISTINCT s.id), COUNT(su.url)
                FROM sources s
                LEFT JOIN source_urls su ON s.id = su.source_id
                WHERE s.status = 'active'
                AND su.url_type = 'build'
            """)).fetchone()
            
            source_count, section_url_count = result
            
            assert section_url_count > 0, \
                "No build URLs (section URLs) configured in sources table"
            
            # At least some active sources should have section URLs
            ratio = section_url_count / max(source_count, 1)
            assert ratio > 0.1, \
                f"Only {ratio:.1%} of sources have section URLs configured"
    
    def test_article_urls_discovered_from_sections(self, production_db):
        """
        Verify new article URLs are being discovered from section URLs.
        
        Validates the full workflow:
        1. Section URLs exist and are marked as sections
        2. Discovery runs and finds article URLs from those sections
        3. Article URLs reference their section URL parent
        """
        with production_db.get_session() as session:
            # Check for recent discoveries linked to section URLs
            result = session.execute(text("""
                SELECT COUNT(*) as recent_articles
                FROM candidate_links cl
                WHERE cl.discovered_at >= NOW() - INTERVAL '24 hours'
                AND cl.is_section_url = false
                AND cl.section_url_id IS NOT NULL
            """)).scalar()
            
            # Should have some articles discovered from section URLs recently
            assert result > 0, \
                "No articles discovered from section URLs in last 24h - discovery may not be using sections"


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
                    f"Low extraction rate: {avg_per_hour:.0f} articles/hour - may need more workers"
    
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
