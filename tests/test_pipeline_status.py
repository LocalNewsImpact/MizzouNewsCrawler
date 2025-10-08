"""Tests for the pipeline-status command."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from src.cli.commands.pipeline_status import (
    _check_discovery_status,
    _check_verification_status,
    _check_extraction_status,
    _check_entity_extraction_status,
    _check_analysis_status,
    _check_overall_health,
)


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    session = Mock()
    return session


class TestDiscoveryStatus:
    """Tests for discovery status checking."""
    
    def test_check_discovery_status_with_sources_due(self, mock_session, capsys):
        """Test discovery status when sources are due."""
        # Mock database queries
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 157),  # total sources
            Mock(scalar=lambda: 15),   # sources discovered
            Mock(scalar=lambda: 453),  # URLs discovered
            Mock(scalar=lambda: 143),  # sources due
        ]
        
        _check_discovery_status(mock_session, 24, False)
        
        captured = capsys.readouterr()
        assert "Total sources: 157" in captured.out
        assert "Sources due for discovery: 143" in captured.out
        assert "URLs discovered (last 24h): 453" in captured.out
        assert "WARNING" in captured.out  # Should warn about sources due
    
    def test_check_discovery_status_healthy(self, mock_session, capsys):
        """Test discovery status when healthy."""
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 157),  # total sources
            Mock(scalar=lambda: 15),   # sources discovered
            Mock(scalar=lambda: 453),  # URLs discovered
            Mock(scalar=lambda: 0),    # sources due
        ]
        
        _check_discovery_status(mock_session, 24, False)
        
        captured = capsys.readouterr()
        assert "Average URLs per source:" in captured.out
        assert "✓" in captured.out


class TestVerificationStatus:
    """Tests for verification status checking."""
    
    def test_check_verification_status_with_backlog(self, mock_session, capsys):
        """Test verification status with large backlog."""
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 1500),  # pending
            Mock(scalar=lambda: 5432),  # articles
            Mock(scalar=lambda: 187),   # verified recent
        ]
        
        _check_verification_status(mock_session, 24, False)
        
        captured = capsys.readouterr()
        assert "Pending verification: 1500" in captured.out
        assert "WARNING" in captured.out  # Should warn about large backlog
    
    def test_check_verification_status_no_activity(self, mock_session, capsys):
        """Test verification status with no recent activity."""
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 100),  # pending
            Mock(scalar=lambda: 5432), # articles
            Mock(scalar=lambda: 0),    # verified recent
        ]
        
        _check_verification_status(mock_session, 24, False)
        
        captured = capsys.readouterr()
        assert "No verification activity" in captured.out
        assert "WARNING" in captured.out


class TestExtractionStatus:
    """Tests for extraction status checking."""
    
    def test_check_extraction_status_active(self, mock_session, capsys):
        """Test extraction status when active."""
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 123),  # ready for extraction
            Mock(scalar=lambda: 4892), # total extracted
            Mock(scalar=lambda: 98),   # extracted recent
            Mock(fetchall=lambda: [     # status breakdown
                ("extracted", 2134),
                ("cleaned", 1892),
                ("wire", 567),
                ("local", 299),
            ]),
        ]
        
        _check_extraction_status(mock_session, 24, False)
        
        captured = capsys.readouterr()
        assert "Ready for extraction: 123" in captured.out
        assert "Extracted (last 24h): 98" in captured.out
        assert "✓ Extraction active" in captured.out
        assert "extracted: 2134" in captured.out


class TestEntityExtractionStatus:
    """Tests for entity extraction status checking."""
    
    def test_check_entity_extraction_status_large_backlog(self, mock_session, capsys):
        """Test entity extraction with large backlog."""
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 1538),  # ready for entities
            Mock(scalar=lambda: 3354),  # total with entities
            Mock(scalar=lambda: 89),    # entities recent
        ]
        
        _check_entity_extraction_status(mock_session, 24, False)
        
        captured = capsys.readouterr()
        assert "Ready for entity extraction: 1538" in captured.out
        assert "WARNING" in captured.out  # Should warn about large backlog


class TestAnalysisStatus:
    """Tests for analysis status checking."""
    
    def test_check_analysis_status_not_available(self, mock_session, capsys):
        """Test analysis status when table doesn't exist."""
        mock_session.execute.side_effect = Exception("Table does not exist")
        
        _check_analysis_status(mock_session, 24, False)
        
        captured = capsys.readouterr()
        assert "not available" in captured.out


class TestOverallHealth:
    """Tests for overall health checking."""
    
    def test_overall_health_all_active(self, mock_session, capsys):
        """Test overall health when all stages are active."""
        # Mock all stages having recent activity
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 10),  # discovery
            Mock(scalar=lambda: 20),  # verification
            Mock(scalar=lambda: 30),  # extraction
            Mock(scalar=lambda: 40),  # entity extraction
            Mock(scalar=lambda: 50),  # analysis
        ]
        
        _check_overall_health(mock_session, 24)
        
        captured = capsys.readouterr()
        assert "5/5" in captured.out
        assert "100%" in captured.out
        assert "✅" in captured.out
        assert "healthy" in captured.out.lower()
    
    def test_overall_health_partially_active(self, mock_session, capsys):
        """Test overall health when partially active."""
        # Mock 3 out of 5 stages having activity
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 10),  # discovery - active
            Mock(scalar=lambda: 0),   # verification - inactive
            Mock(scalar=lambda: 30),  # extraction - active
            Mock(scalar=lambda: 0),   # entity extraction - inactive
            Mock(scalar=lambda: 50),  # analysis - active
        ]
        
        _check_overall_health(mock_session, 24)
        
        captured = capsys.readouterr()
        assert "3/5" in captured.out
        assert "60%" in captured.out
        assert "⚠️" in captured.out
    
    def test_overall_health_mostly_stalled(self, mock_session, capsys):
        """Test overall health when mostly stalled."""
        # Mock only 1 stage having activity
        mock_session.execute.side_effect = [
            Mock(scalar=lambda: 0),   # discovery - inactive
            Mock(scalar=lambda: 0),   # verification - inactive
            Mock(scalar=lambda: 10),  # extraction - active
            Mock(scalar=lambda: 0),   # entity extraction - inactive
            Mock(scalar=lambda: 0),   # analysis - inactive
        ]
        
        _check_overall_health(mock_session, 24)
        
        captured = capsys.readouterr()
        assert "1/5" in captured.out
        assert "20%" in captured.out
        assert "❌" in captured.out
        assert "stalled" in captured.out.lower()


class TestPipelineStatusCommand:
    """Integration tests for the pipeline-status command."""
    
    @patch('src.cli.commands.pipeline_status.DatabaseManager')
    def test_command_runs_without_error(self, mock_db_manager, capsys):
        """Test that the pipeline-status command runs without errors."""
        # Mock database manager
        mock_db = Mock()
        mock_session = Mock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session
        mock_db_manager.return_value = mock_db
        
        # Mock all database queries to return 0 (empty pipeline)
        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.fetchall.return_value = []
        
        from src.cli.commands.pipeline_status import handle_pipeline_status_command
        
        # Create mock args
        args = Mock()
        args.detailed = False
        args.hours = 24
        
        result = handle_pipeline_status_command(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "PIPELINE STATUS REPORT" in captured.out
        assert "STAGE 1: DISCOVERY" in captured.out
        assert "STAGE 2: VERIFICATION" in captured.out
        assert "STAGE 3: EXTRACTION" in captured.out
        assert "STAGE 4: ENTITY EXTRACTION" in captured.out
        assert "STAGE 5: ANALYSIS" in captured.out
        assert "OVERALL PIPELINE HEALTH" in captured.out


def test_pipeline_status_parser_registration():
    """Test that the pipeline-status parser is registered correctly."""
    import argparse
    from src.cli.commands.pipeline_status import add_pipeline_status_parser
    
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    
    status_parser = add_pipeline_status_parser(subparsers)
    
    assert status_parser is not None
    
    # Test parsing with default args
    args = parser.parse_args(['pipeline-status'])
    assert args.detailed is False
    assert args.hours == 24
    
    # Test parsing with options
    args = parser.parse_args(['pipeline-status', '--detailed', '--hours', '48'])
    assert args.detailed is True
    assert args.hours == 48
