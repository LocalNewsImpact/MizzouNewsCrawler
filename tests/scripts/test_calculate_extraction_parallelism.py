"""Test coverage for calculate_extraction_parallelism.py script.

This module tests both the pure calculation logic and database integration
for determining extraction worker parallelism based on backlog size.
"""

import pytest

import scripts.calculate_extraction_parallelism as calc_script
from scripts.calculate_extraction_parallelism import (
    ARTICLES_PER_WORKER,
    MAX_WORKERS,
    MIN_WORKERS,
    calculate_parallelism,
    get_extraction_backlog,
    main,
)

pytestmark = pytest.mark.local_scripts


from src.models import Article, CandidateLink


class TestCalculateParallelism:
    """Unit tests for calculate_parallelism() function (no database required)."""

    def test_zero_backlog_returns_minimum(self):
        """Zero backlog should return MIN_WORKERS to handle ongoing discovery."""
        assert calculate_parallelism(0) == MIN_WORKERS

    def test_small_backlog_returns_minimum(self):
        """Backlog < 60 articles should return MIN_WORKERS."""
        # 50 articles / 60 = 0.83 workers → minimum of 3
        assert calculate_parallelism(50) == MIN_WORKERS
        assert calculate_parallelism(30) == MIN_WORKERS
        assert calculate_parallelism(1) == MIN_WORKERS

    def test_minimum_threshold(self):
        """Backlog at minimum threshold should return MIN_WORKERS."""
        # 180 articles / 60 = 3 workers (exactly at minimum)
        assert calculate_parallelism(180) == MIN_WORKERS

    def test_mid_range_backlog(self):
        """Mid-range backlog should return calculated workers."""
        # 300 articles / 60 = 5 workers
        assert calculate_parallelism(300) == 5
        # 420 articles / 60 = 7 workers
        assert calculate_parallelism(420) == 7
        # 600 articles / 60 = 10 workers
        assert calculate_parallelism(600) == 10

    def test_maximum_threshold(self):
        """Backlog at maximum threshold should return MAX_WORKERS."""
        # 900 articles / 60 = 15 workers (exactly at maximum)
        assert calculate_parallelism(900) == MAX_WORKERS

    def test_exceeds_maximum(self):
        """Backlog exceeding maximum should cap at MAX_WORKERS."""
        # 1200 articles / 60 = 20 workers → capped at 15
        assert calculate_parallelism(1200) == MAX_WORKERS
        assert calculate_parallelism(2000) == MAX_WORKERS
        assert calculate_parallelism(5000) == MAX_WORKERS

    def test_formula_constants(self):
        """Verify formula constants are correctly set."""
        assert ARTICLES_PER_WORKER == 60  # 240 minutes / 4 minutes per article
        assert MIN_WORKERS == 3  # Baseline for ongoing discovery
        assert MAX_WORKERS == 15  # Cost constraint

    def test_edge_case_just_below_minimum(self):
        """Backlog just below minimum threshold returns MIN_WORKERS."""
        # 179 articles / 60 = 2.98 workers → 2 → minimum of 3
        assert calculate_parallelism(179) == MIN_WORKERS

    def test_edge_case_just_above_minimum(self):
        """Backlog just above minimum threshold returns calculated value."""
        # 181 articles / 60 = 3.01 workers → 3 → still minimum
        assert calculate_parallelism(181) == MIN_WORKERS
        # 240 articles / 60 = 4 workers → 4
        assert calculate_parallelism(240) == 4

    def test_edge_case_just_below_maximum(self):
        """Backlog just below maximum threshold returns calculated value."""
        # 899 articles / 60 = 14.98 workers → 14
        assert calculate_parallelism(899) == 14

    def test_edge_case_just_above_maximum(self):
        """Backlog just above maximum threshold caps at MAX_WORKERS."""
        # 901 articles / 60 = 15.01 workers → 15 → capped
        assert calculate_parallelism(901) == MAX_WORKERS


@pytest.mark.integration
@pytest.mark.postgres
class TestGetExtractionBacklog:
    """Integration tests for get_extraction_backlog() (requires PostgreSQL)."""

    def test_empty_database_returns_zero(self, cloud_sql_session):
        """Empty database should return 0 backlog."""
        # No setup needed - cloud_sql_session is clean
        backlog = get_extraction_backlog()
        assert backlog == 0

    def test_no_article_status_candidates_returns_zero(self, cloud_sql_session):
        """Candidates without 'article' status should not count."""
        # Create candidates with various statuses but none with 'article'
        cloud_sql_session.add(
            CandidateLink(
                url="https://example.com/new",
                source="example.com",
                status="new",
            )
        )
        cloud_sql_session.add(
            CandidateLink(
                url="https://example.com/fetched",
                source="example.com",
                status="fetched",
            )
        )
        cloud_sql_session.add(
            CandidateLink(
                url="https://example.com/extracted",
                source="example.com",
                status="extracted",
            )
        )
        cloud_sql_session.commit()

        backlog = get_extraction_backlog()
        assert backlog == 0

    def test_article_status_not_extracted_counts(self, cloud_sql_session, monkeypatch):
        """Candidates with 'article' status but not extracted should count."""
        # Create 3 candidate_links with status='article'
        candidates = [
            CandidateLink(
                url=f"https://example.com/article-{i}",
                source="example.com",
                status="article",
            )
            for i in range(3)
        ]
        for c in candidates:
            cloud_sql_session.add(c)
        cloud_sql_session.commit()

        # Mock DatabaseManager to use test session
        class FakeDBManager:
            def get_session(self):
                from contextlib import contextmanager

                @contextmanager
                def session():
                    yield cloud_sql_session

                return session()

        monkeypatch.setattr(calc_script, "DatabaseManager", lambda: FakeDBManager())

        backlog = get_extraction_backlog()
        assert backlog == 3

    def test_extracted_articles_excluded(self, cloud_sql_session, monkeypatch):
        """Candidates with status='article' but already extracted should not count."""
        # Create 5 candidate_links with status='article'
        candidates = [
            CandidateLink(
                url=f"https://example.com/article-{i}",
                source="example.com",
                status="article",
            )
            for i in range(5)
        ]
        for c in candidates:
            cloud_sql_session.add(c)
        cloud_sql_session.commit()

        # Extract 2 of them (create Article records)
        cloud_sql_session.add(
            Article(
                candidate_link_id=candidates[0].id,
                url=candidates[0].url,
                title="Test Article 1",
                text="Content 1",
            )
        )
        cloud_sql_session.add(
            Article(
                candidate_link_id=candidates[1].id,
                url=candidates[1].url,
                title="Test Article 2",
                text="Content 2",
            )
        )
        cloud_sql_session.commit()

        # Mock DatabaseManager to use test session
        class FakeDBManager:
            def get_session(self):
                from contextlib import contextmanager

                @contextmanager
                def session():
                    yield cloud_sql_session

                return session()

        monkeypatch.setattr(calc_script, "DatabaseManager", lambda: FakeDBManager())

        # Should count 3 remaining (5 total - 2 extracted)
        backlog = get_extraction_backlog()
        assert backlog == 3

    def test_mixed_statuses_only_unextracted_articles_count(
        self, cloud_sql_session, monkeypatch
    ):
        """Complex scenario with mixed statuses and extraction states."""

        # Mock DatabaseManager to use test session
        class FakeDBManager:
            def get_session(self):
                from contextlib import contextmanager

                @contextmanager
                def session():
                    yield cloud_sql_session

                return session()

        monkeypatch.setattr(calc_script, "DatabaseManager", lambda: FakeDBManager())

        # 2 candidates with status='new' (should not count)
        cloud_sql_session.add(
            CandidateLink(
                url="https://example.com/new-1",
                source="example.com",
                status="new",
            )
        )
        cloud_sql_session.add(
            CandidateLink(
                url="https://example.com/new-2",
                source="example.com",
                status="new",
            )
        )

        # 4 candidates with status='article' but not extracted (SHOULD COUNT)
        unextracted = [
            CandidateLink(
                url=f"https://example.com/unextracted-{i}",
                source="example.com",
                status="article",
            )
            for i in range(4)
        ]
        for c in unextracted:
            cloud_sql_session.add(c)

        # 3 candidates with status='article' AND extracted (should NOT count)
        extracted = [
            CandidateLink(
                url=f"https://example.com/extracted-{i}",
                source="example.com",
                status="article",
            )
            for i in range(3)
        ]
        for c in extracted:
            cloud_sql_session.add(c)
        cloud_sql_session.commit()

        # Create Article records for extracted candidates
        for c in extracted:
            cloud_sql_session.add(
                Article(
                    candidate_link_id=c.id,
                    url=c.url,
                    title=f"Article {c.url}",
                    text="Content",
                )
            )
        cloud_sql_session.commit()

        # Should count only the 4 unextracted candidates with status='article'
        backlog = get_extraction_backlog()
        assert backlog == 4

    def test_large_backlog(self, cloud_sql_session, monkeypatch):
        """Test with larger backlog to verify scalability."""

        # Mock DatabaseManager to use test session
        class FakeDBManager:
            def get_session(self):
                from contextlib import contextmanager

                @contextmanager
                def session():
                    yield cloud_sql_session

                return session()

        monkeypatch.setattr(calc_script, "DatabaseManager", lambda: FakeDBManager())

        # Create 150 candidates with status='article'
        candidates = [
            CandidateLink(
                url=f"https://example.com/article-{i}",
                source="example.com",
                status="article",
            )
            for i in range(150)
        ]
        for c in candidates:
            cloud_sql_session.add(c)
        cloud_sql_session.commit()

        backlog = get_extraction_backlog()
        assert backlog == 150


@pytest.mark.integration
@pytest.mark.postgres
class TestMainFunction:
    """Integration tests for main() function (end-to-end with database)."""

    def test_main_outputs_worker_count(self, cloud_sql_session, capsys, monkeypatch):
        """main() should output worker count to stdout and log to stderr."""

        # Mock DatabaseManager to use test session
        class FakeDBManager:
            def get_session(self):
                from contextlib import contextmanager

                @contextmanager
                def session():
                    yield cloud_sql_session

                return session()

        monkeypatch.setattr(calc_script, "DatabaseManager", lambda: FakeDBManager())

        # Create backlog of 300 articles
        candidates = [
            CandidateLink(
                url=f"https://example.com/article-{i}",
                source="example.com",
                status="article",
            )
            for i in range(300)
        ]
        for c in candidates:
            cloud_sql_session.add(c)
        cloud_sql_session.commit()

        # Run main function
        exit_code = main()

        # Check exit code
        assert exit_code == 0

        # Check output
        captured = capsys.readouterr()
        # stdout should have just the number (5 workers for 300 articles)
        assert captured.out.strip() == "5"
        # stderr should have the log message
        assert "Backlog: 300 articles" in captured.err
        assert "5 workers" in captured.err

    def test_main_zero_backlog_returns_minimum(self, cloud_sql_session, capsys):
        """main() with zero backlog should return MIN_WORKERS."""
        # No candidates created - empty backlog
        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == str(MIN_WORKERS)
        assert "Backlog: 0 articles" in captured.err
        assert f"{MIN_WORKERS} workers" in captured.err

    def test_main_large_backlog_caps_at_maximum(
        self, cloud_sql_session, capsys, monkeypatch
    ):
        """main() with large backlog should cap at MAX_WORKERS."""

        # Mock DatabaseManager to use test session
        class FakeDBManager:
            def get_session(self):
                from contextlib import contextmanager

                @contextmanager
                def session():
                    yield cloud_sql_session

                return session()

        monkeypatch.setattr(calc_script, "DatabaseManager", lambda: FakeDBManager())

        # Create backlog of 2000 articles (would calculate to 33 workers)
        candidates = [
            CandidateLink(
                url=f"https://example.com/article-{i}",
                source="example.com",
                status="article",
            )
            for i in range(2000)
        ]
        for c in candidates:
            cloud_sql_session.add(c)
        cloud_sql_session.commit()

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == str(MAX_WORKERS)
        assert "Backlog: 2000 articles" in captured.err
        assert f"{MAX_WORKERS} workers" in captured.err

    def test_main_handles_database_error(self, monkeypatch, capsys):
        """main() should return fallback value on database error."""

        def mock_get_backlog():
            raise Exception("Database connection failed")

        # Mock the function to raise an error
        import scripts.calculate_extraction_parallelism as script

        monkeypatch.setattr(script, "get_extraction_backlog", mock_get_backlog)

        exit_code = main()

        # Should return error code but output fallback value
        assert exit_code == 1
        captured = capsys.readouterr()
        # Should output fallback value of 2
        assert captured.out.strip() == "2"
        # Should log error to stderr
        assert "Error calculating parallelism" in captured.err
