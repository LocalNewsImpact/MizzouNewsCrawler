"""Integration tests for pipeline-status CLI command against PostgreSQL.

These tests validate that the pipeline-status command works correctly with
PostgreSQL/Cloud SQL, including:
- All 5 pipeline stages (discovery, verification, extraction, entity extraction, analysis)
- PostgreSQL-specific queries (INTERVAL, COALESCE, aggregations)
- Detailed mode with grouping
- Overall health calculations

Following the test development protocol from .github/copilot-instructions.md:
1. Uses cloud_sql_session fixture for PostgreSQL with automatic rollback
2. Creates all required parent records with proper foreign keys
3. Marks with @pytest.mark.postgres AND @pytest.mark.integration
4. Tests run in postgres-integration CI job with PostgreSQL 15
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text

from src.cli.commands.pipeline_status import (
    _check_analysis_status,
    _check_discovery_status,
    _check_entity_extraction_status,
    _check_extraction_status,
    _check_overall_health,
    _check_verification_status,
    handle_pipeline_status_command,
)
from src.models import Article, CandidateLink, Source

# Mark all tests to require PostgreSQL and run in integration job
pytestmark = [pytest.mark.postgres, pytest.mark.integration]


@pytest.fixture
def test_sources(cloud_sql_session):
    """Create multiple test sources for pipeline testing."""
    sources = []
    for i in range(3):
        source = Source(
            id=str(uuid.uuid4()),
            host=f"test-pipeline-{i}.example.com",
            host_norm=f"test-pipeline-{i}.example.com",
            canonical_name=f"Test Pipeline Source {i}",
            city=f"Test City {i}",
            county="Test County",
            state="MO",
        )
        sources.append(source)
        cloud_sql_session.add(source)
    
    cloud_sql_session.commit()
    for source in sources:
        cloud_sql_session.refresh(source)
    return sources


@pytest.fixture
def pipeline_test_data(cloud_sql_session, test_sources):
    """Create complete pipeline test data across all stages."""
    # Stage 1: Discovery - recently discovered URLs
    discovered_candidates = []
    for i in range(5):
        candidate = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://test-pipeline-0.example.com/discovered-{i}",
            source=test_sources[0].canonical_name,
            source_host_id=test_sources[0].id,
            crawl_depth=0,
            status="discovered",
            discovered_at=datetime.now(timezone.utc),
            discovered_by="test_pipeline",
        )
        discovered_candidates.append(candidate)
        cloud_sql_session.add(candidate)
    
    # Stage 2: Verification - verified as articles
    verified_candidates = []
    for i in range(3):
        candidate = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://test-pipeline-0.example.com/verified-{i}",
            source=test_sources[0].canonical_name,
            source_host_id=test_sources[0].id,
            crawl_depth=0,
            status="article",
            discovered_at=datetime.now(timezone.utc) - timedelta(hours=1),
            discovered_by="test_pipeline",
            processed_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        verified_candidates.append(candidate)
        cloud_sql_session.add(candidate)
    
    cloud_sql_session.commit()
    
    # Stage 3: Extraction - extracted articles
    extracted_articles = []
    for i, candidate in enumerate(verified_candidates[:2]):
        article = Article(
            id=str(uuid.uuid4()),
            url=candidate.url,
            candidate_link_id=candidate.id,
            title=f"Test Article {i}",
            content=f"Test content for article {i}",
            text=f"Test text for article {i}",
            status="extracted",
            extracted_at=datetime.now(timezone.utc) - timedelta(minutes=15),
        )
        extracted_articles.append(article)
        cloud_sql_session.add(article)
    
    cloud_sql_session.commit()
    
    return {
        "sources": test_sources,
        "discovered": discovered_candidates,
        "verified": verified_candidates,
        "extracted": extracted_articles,
    }


class TestPipelineDiscoveryStatusPostgres:
    """Test discovery status queries with PostgreSQL."""

    def test_discovery_total_sources_postgres(
        self, cloud_sql_session, test_sources
    ):
        """Test counting total sources in PostgreSQL."""
        query = text("""
            SELECT COUNT(*) 
            FROM sources 
            WHERE host IS NOT NULL
        """)
        
        result = cloud_sql_session.execute(query)
        total_sources = result.scalar()
        
        # Should have our 3 test sources
        assert total_sources >= 3

    def test_discovery_recent_activity_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test querying recent discovery activity with PostgreSQL INTERVAL."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        query = text("""
            SELECT COUNT(DISTINCT source_host_id)
            FROM candidate_links
            WHERE discovered_at >= :cutoff
        """)
        
        result = cloud_sql_session.execute(query, {"cutoff": cutoff})
        sources_discovered = result.scalar()
        
        # Should have discovered from at least 1 source
        assert sources_discovered >= 1

    def test_discovery_urls_discovered_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting URLs discovered in time window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        query = text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE discovered_at >= :cutoff
        """)
        
        result = cloud_sql_session.execute(query, {"cutoff": cutoff})
        urls_discovered = result.scalar()
        
        # Should have discovered URLs
        assert urls_discovered >= 5

    def test_discovery_top_sources_detailed_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test detailed discovery breakdown by source."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        query = text("""
            SELECT s.canonical_name, COUNT(*) as url_count
            FROM candidate_links cl
            JOIN sources s ON cl.source_host_id = s.id
            WHERE cl.discovered_at >= :cutoff
            GROUP BY s.canonical_name
            ORDER BY url_count DESC
            LIMIT 10
        """)
        
        result = cloud_sql_session.execute(query, {"cutoff": cutoff})
        top_sources = list(result)
        
        # Should have at least 1 source with URLs
        assert len(top_sources) >= 1
        
        # Each row should have source name and count
        for row in top_sources:
            assert row[0] is not None  # canonical_name
            assert row[1] > 0  # url_count


class TestPipelineVerificationStatusPostgres:
    """Test verification status queries with PostgreSQL."""

    def test_verification_pending_count_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting pending verification URLs."""
        query = text("""
            SELECT COUNT(*) 
            FROM candidate_links 
            WHERE status = 'discovered'
        """)
        
        result = cloud_sql_session.execute(query)
        pending = result.scalar()
        
        # Should have discovered URLs pending verification
        assert pending >= 5

    def test_verification_articles_count_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting verified articles."""
        query = text("""
            SELECT COUNT(*) 
            FROM candidate_links 
            WHERE status = 'article'
        """)
        
        result = cloud_sql_session.execute(query)
        articles = result.scalar()
        
        # Should have verified articles
        assert articles >= 3

    def test_verification_recent_activity_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting recent verification activity with INTERVAL."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        query = text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE processed_at >= :cutoff
        """)
        
        result = cloud_sql_session.execute(query, {"cutoff": cutoff})
        verified_recent = result.scalar()
        
        # Should have recent verification activity
        assert verified_recent >= 3


class TestPipelineExtractionStatusPostgres:
    """Test extraction status queries with PostgreSQL."""

    def test_extraction_ready_count_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting articles ready for extraction."""
        query = text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE status = 'article'
            AND id NOT IN (
                SELECT candidate_link_id 
                FROM articles 
                WHERE candidate_link_id IS NOT NULL
            )
        """)
        
        result = cloud_sql_session.execute(query)
        ready_for_extraction = result.scalar()
        
        # Should have at least 1 article ready (3 verified, 2 extracted)
        assert ready_for_extraction >= 1

    def test_extraction_total_count_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting total extracted articles."""
        query = text("""
            SELECT COUNT(*) 
            FROM articles
        """)
        
        result = cloud_sql_session.execute(query)
        total_extracted = result.scalar()
        
        # Should have extracted articles
        assert total_extracted >= 2

    def test_extraction_recent_activity_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting recent extraction activity."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        query = text("""
            SELECT COUNT(*) 
            FROM articles 
            WHERE extracted_at >= :cutoff
        """)
        
        result = cloud_sql_session.execute(query, {"cutoff": cutoff})
        extracted_recent = result.scalar()
        
        # Should have recent extraction activity
        assert extracted_recent >= 2

    def test_extraction_status_breakdown_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test extraction status breakdown with GROUP BY."""
        query = text("""
            SELECT status, COUNT(*) as count
            FROM articles
            GROUP BY status
            ORDER BY count DESC
        """)
        
        result = cloud_sql_session.execute(query)
        status_breakdown = list(result)
        
        # Should have status breakdown
        assert len(status_breakdown) >= 1
        
        # All should be extracted status
        statuses = {row[0]: row[1] for row in status_breakdown}
        assert statuses.get("extracted", 0) >= 2


class TestPipelineEntityExtractionStatusPostgres:
    """Test entity extraction status queries with PostgreSQL."""

    def test_entity_extraction_ready_count_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting articles ready for entity extraction."""
        query = text("""
            SELECT COUNT(*)
            FROM articles a
            WHERE a.content IS NOT NULL
            AND a.text IS NOT NULL
            AND a.status NOT IN ('wire', 'opinion', 'obituary', 'error')
            AND NOT EXISTS (
                SELECT 1 FROM article_entities ae 
                WHERE ae.article_id = a.id
            )
        """)
        
        result = cloud_sql_session.execute(query)
        ready_for_entities = result.scalar()
        
        # Should have articles ready for entity extraction
        assert ready_for_entities >= 2

    def test_entity_extraction_subquery_not_exists_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test NOT EXISTS subquery works in PostgreSQL."""
        # This tests a PostgreSQL-specific optimization
        query = text("""
            SELECT a.id, a.title
            FROM articles a
            WHERE NOT EXISTS (
                SELECT 1 FROM article_entities ae 
                WHERE ae.article_id = a.id
                LIMIT 1
            )
        """)
        
        result = cloud_sql_session.execute(query)
        articles_without_entities = list(result)
        
        # Should find articles without entities
        assert len(articles_without_entities) >= 2


class TestPipelineAnalysisStatusPostgres:
    """Test analysis/classification status queries with PostgreSQL."""

    def test_analysis_ready_count_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test counting articles ready for classification."""
        # This tests that the query doesn't fail even if article_labels doesn't exist
        query = text("""
            SELECT COUNT(*)
            FROM articles a
            WHERE a.status IN ('extracted', 'cleaned', 'local')
        """)
        
        result = cloud_sql_session.execute(query)
        ready_for_analysis = result.scalar()
        
        # Should have articles in analyzed-ready statuses
        assert ready_for_analysis >= 2

    def test_analysis_error_handling_missing_table_postgres(
        self, cloud_sql_session, capsys
    ):
        """Test that analysis handles missing tables gracefully."""
        # Call the actual analysis status function
        _check_analysis_status(cloud_sql_session, 24, False)
        
        captured = capsys.readouterr()
        # Should either show results or graceful error message
        # (depending on whether article_labels table exists)
        assert "Ready for classification" in captured.out or "not available" in captured.out


class TestPipelineOverallHealthPostgres:
    """Test overall pipeline health calculation with PostgreSQL."""

    def test_overall_health_calculation_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test overall health calculation with real data."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Count active stages
        stages_active = 0
        
        # Discovery
        result = cloud_sql_session.execute(
            text("SELECT COUNT(*) FROM candidate_links WHERE discovered_at >= :cutoff"),
            {"cutoff": cutoff}
        )
        if (result.scalar() or 0) > 0:
            stages_active += 1
        
        # Verification
        result = cloud_sql_session.execute(
            text("SELECT COUNT(*) FROM candidate_links WHERE processed_at >= :cutoff"),
            {"cutoff": cutoff}
        )
        if (result.scalar() or 0) > 0:
            stages_active += 1
        
        # Extraction
        result = cloud_sql_session.execute(
            text("SELECT COUNT(*) FROM articles WHERE extracted_at >= :cutoff"),
            {"cutoff": cutoff}
        )
        if (result.scalar() or 0) > 0:
            stages_active += 1
        
        # Should have at least 3 active stages from our test data
        assert stages_active >= 3

    def test_overall_health_with_capsys_postgres(
        self, cloud_sql_session, pipeline_test_data, capsys
    ):
        """Test overall health output with real data."""
        _check_overall_health(cloud_sql_session, 24)
        
        captured = capsys.readouterr()
        # Should show pipeline stages and health score
        assert "Pipeline stages active:" in captured.out
        assert "Health score:" in captured.out
        # Should show at least some activity (3+ stages active = 60%+)
        assert "%" in captured.out


class TestPipelineCommandPostgres:
    """Test full pipeline-status command execution with PostgreSQL."""

    @patch("src.cli.commands.pipeline_status.DatabaseManager")
    def test_pipeline_status_command_execution_postgres(
        self, mock_db_manager, cloud_sql_session, pipeline_test_data, capsys
    ):
        """Test full pipeline-status command with real PostgreSQL session."""
        # Mock DatabaseManager to return our test session
        mock_db = Mock()
        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=cloud_sql_session)
        mock_context.__exit__ = Mock(return_value=False)
        mock_db.get_session = Mock(return_value=mock_context)
        mock_db_manager.return_value = mock_db
        
        # Create mock args
        args = Mock()
        args.detailed = False
        args.hours = 24
        
        # Execute command
        result = handle_pipeline_status_command(args)
        
        # Should execute successfully
        assert result == 0
        
        # Verify output contains all stages
        captured = capsys.readouterr()
        assert "STAGE 1: DISCOVERY" in captured.out
        assert "STAGE 2: VERIFICATION" in captured.out
        assert "STAGE 3: EXTRACTION" in captured.out
        assert "STAGE 4: ENTITY EXTRACTION" in captured.out
        assert "STAGE 5: ANALYSIS" in captured.out
        assert "OVERALL PIPELINE HEALTH" in captured.out

    @patch("src.cli.commands.pipeline_status.DatabaseManager")
    def test_pipeline_status_detailed_mode_postgres(
        self, mock_db_manager, cloud_sql_session, pipeline_test_data, capsys
    ):
        """Test pipeline-status command detailed mode."""
        # Mock DatabaseManager to return our test session
        mock_db = Mock()
        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=cloud_sql_session)
        mock_context.__exit__ = Mock(return_value=False)
        mock_db.get_session = Mock(return_value=mock_context)
        mock_db_manager.return_value = mock_db
        
        # Create mock args with detailed flag
        args = Mock()
        args.detailed = True
        args.hours = 24
        
        # Execute command
        result = handle_pipeline_status_command(args)
        
        # Should execute successfully
        assert result == 0
        
        # In detailed mode, should show source breakdowns
        captured = capsys.readouterr()
        # The detailed flag should trigger additional queries
        assert "STAGE 1: DISCOVERY" in captured.out


class TestPipelinePostgresSpecificFeatures:
    """Test PostgreSQL-specific features in pipeline queries."""

    def test_interval_syntax_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test PostgreSQL INTERVAL syntax in queries."""
        # Test various INTERVAL syntaxes used in pipeline_status
        intervals = [
            "INTERVAL '1 minute'",
            "INTERVAL '1 hour'",
            "INTERVAL '24 hours'",
            "INTERVAL '7 days'",
        ]
        
        for interval in intervals:
            query = text(f"""
                SELECT CURRENT_TIMESTAMP - {interval} as cutoff_time
            """)
            
            result = cloud_sql_session.execute(query)
            cutoff = result.scalar()
            
            # Should return a valid timestamp
            assert cutoff is not None
            assert isinstance(cutoff, datetime)

    def test_coalesce_in_aggregation_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test COALESCE with SUM in PostgreSQL."""
        # This pattern is used in pipeline metrics
        query = text("""
            SELECT 
                status,
                COUNT(*) as count,
                COALESCE(SUM(CASE WHEN processed_at IS NOT NULL THEN 1 ELSE 0 END), 0) as processed
            FROM candidate_links
            GROUP BY status
        """)
        
        result = cloud_sql_session.execute(query)
        metrics = list(result)
        
        # Should have status metrics
        assert len(metrics) >= 1
        
        # COALESCE should prevent NULL values
        for row in metrics:
            assert row[2] is not None  # processed count

    def test_case_statement_in_aggregation_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test CASE statements in aggregate queries."""
        query = text("""
            SELECT 
                CASE 
                    WHEN status = 'discovered' THEN 'pending'
                    WHEN status = 'article' THEN 'verified'
                    ELSE 'other'
                END as status_category,
                COUNT(*) as count
            FROM candidate_links
            GROUP BY status_category
            ORDER BY count DESC
        """)
        
        result = cloud_sql_session.execute(query)
        categories = list(result)
        
        # Should have categorized results
        assert len(categories) >= 1
        
        # Should have proper categories
        category_names = {row[0] for row in categories}
        assert len(category_names & {"pending", "verified", "other"}) > 0

    def test_distinct_count_in_subquery_postgres(
        self, cloud_sql_session, pipeline_test_data
    ):
        """Test DISTINCT COUNT in complex subqueries."""
        query = text("""
            SELECT 
                (SELECT COUNT(DISTINCT source_host_id) 
                 FROM candidate_links 
                 WHERE discovered_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours') as sources_discovered,
                (SELECT COUNT(*) 
                 FROM candidate_links 
                 WHERE discovered_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours') as urls_discovered
        """)
        
        result = cloud_sql_session.execute(query)
        row = result.fetchone()
        
        # Both metrics should be non-negative
        assert row[0] is not None
        assert row[1] is not None
        assert row[0] >= 0  # sources
        assert row[1] >= 0  # urls
