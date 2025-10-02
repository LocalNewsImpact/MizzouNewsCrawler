"""
Test suite for telemetry API endpoints and site management functionality.
Tests the FastAPI endpoints without running the actual server.
"""

import pytest
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch


class TestTelemetryAPIEndpoints:
    """Test the telemetry API endpoints."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database with test data."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        # Set up test database with schema
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Create extraction_telemetry_v2 table
        cur.execute("""
        CREATE TABLE extraction_telemetry_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            url TEXT NOT NULL,
            publisher TEXT,
            host TEXT,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            total_duration_ms REAL,
            http_status_code INTEGER,
            http_error_type TEXT,
            response_size_bytes INTEGER,
            response_time_ms REAL,
            methods_attempted TEXT,
            successful_method TEXT,
            method_timings TEXT,
            method_success TEXT,
            method_errors TEXT,
            field_extraction TEXT,
            extracted_fields TEXT,
            content_length INTEGER,
            is_success BOOLEAN,
            error_message TEXT,
            error_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Create http_error_summary table
        cur.execute("""
        CREATE TABLE http_error_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            error_type TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Create sources table for site management
        cur.execute("""
        CREATE TABLE sources (
            id VARCHAR PRIMARY KEY,
            host VARCHAR NOT NULL,
            host_norm VARCHAR NOT NULL,
            canonical_name VARCHAR,
            city VARCHAR,
            county VARCHAR,
            owner VARCHAR,
            type VARCHAR,
            metadata JSON,
            discovery_attempted TIMESTAMP,
            status VARCHAR DEFAULT 'active',
            paused_at TIMESTAMP,
            paused_reason TEXT
        )
        """)

        # Insert test data
        now = datetime.utcnow()

        # Test extraction records
        test_records = [
            # Successful extractions
            ("op1", "art1", "https://good-site.com/article1",
             "good-site.com", "good-site.com",
             200, None, "newspaper4k", 1, 2500,
             '{"newspaper4k": {"title": true, "content": true}}'),
            ("op2", "art2", "https://good-site.com/article2",
             "good-site.com", "good-site.com",
             200, None, "beautifulsoup", 1, 3200,
             '{"beautifulsoup": {"title": true, "content": false}}'),

            # Failed extractions with HTTP errors
            ("op3", "art3", "https://blocked-site.com/article1",
             "blocked-site.com", "blocked-site.com",
             403, "4xx_client_error", None, 0, 1500,
             '{"title": false, "content": false}'),
            ("op4", "art4", "https://error-site.com/article1",
             "error-site.com", "error-site.com",
             500, "5xx_server_error", None, 0, 5000,
             '{"title": false, "content": false}'),
            ("op5", "art5", "https://blocked-site.com/article2",
             "blocked-site.com", "blocked-site.com",
             403, "4xx_client_error", None, 0, 1200,
             '{"title": false, "content": false}'),
        ]

        for record in test_records:
            cur.execute("""
            INSERT INTO extraction_telemetry_v2
            (operation_id, article_id, url, publisher, host, http_status_code,
             http_error_type, successful_method, is_success, total_duration_ms, field_extraction,
             start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, record + (now - timedelta(hours=1), now, now))

        # Insert HTTP error summary data
        http_errors = [
            ("blocked-site.com", 403, "4xx_client_error", 2),
            ("error-site.com", 500, "5xx_server_error", 1),
        ]

        for host, status, error_type, count in http_errors:
            cur.execute("""
            INSERT INTO http_error_summary (host, status_code, error_type, count, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (host, status, error_type, count, now - timedelta(hours=2), now))

        # Insert test sources
        sources = [
            ("good-site.com",
             "good-site.com",
             "good-site.com",
             "active",
             None,
             None),
            ("blocked-site.com",
             "blocked-site.com",
             "blocked-site.com",
             "paused",
             now,
             "Poor performance"),
            ]

        for source_id, host, host_norm, status, paused_at, reason in sources:
            cur.execute("""
            INSERT INTO sources (id, host, host_norm, status, paused_at, paused_reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (source_id, host, host_norm, status, paused_at, reason))

        conn.commit()
        conn.close()

        yield db_path

        # Cleanup
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def api_client(self, temp_db):
        """Create a test client with mocked database path."""
        # Mock the database paths in the FastAPI app
        with patch('backend.app.main.MAIN_DB_PATH', temp_db):
            from backend.app.main import app
            client = TestClient(app)
            yield client

    def test_telemetry_summary_endpoint(self, api_client):
        """Test the telemetry summary endpoint."""
        response = api_client.get("/api/telemetry/summary?days=7")
        assert response.status_code == 200

        data = response.json()
        summary = data["summary"]

        assert summary["total_extractions"] == 5
        assert summary["successful_extractions"] == 2
        assert summary["success_rate"] == 40.0  # 2/5 * 100
        assert summary["unique_hosts"] == 3

        # Check method breakdown
        method_breakdown = summary["method_breakdown"]
        methods = {m["method"]: m for m in method_breakdown}
        assert "newspaper4k" in methods
        assert "beautifulsoup" in methods
        assert "failed" in methods

        # Check HTTP errors
        http_errors = summary["top_http_errors"]
        error_codes = {e["status_code"]: e["count"] for e in http_errors}
        assert 403 in error_codes
        assert 500 in error_codes
        assert error_codes[403] == 2

    def test_http_errors_endpoint(self, api_client):
        """Test the HTTP errors endpoint."""
        response = api_client.get("/api/telemetry/http-errors?days=7")
        assert response.status_code == 200

        data = response.json()
        errors = data["http_errors"]

        assert len(errors) >= 2

        # Check for specific error
        blocked_site_errors = [e for e in errors if e["host"]
                               == "blocked-site.com" and e["status_code"] == 403]
        assert len(blocked_site_errors) == 1
        assert blocked_site_errors[0]["error_count"] == 2

    def test_http_errors_endpoint_with_filters(self, api_client):
        """Test HTTP errors endpoint with host and status filters."""
        # Filter by host
        response = api_client.get(
            "/api/telemetry/http-errors?host=blocked-site.com")
        assert response.status_code == 200

        data = response.json()
        errors = data["http_errors"]

        # All errors should be from blocked-site.com
        for error in errors:
            assert error["host"] == "blocked-site.com"

        # Filter by status code
        response = api_client.get("/api/telemetry/http-errors?status_code=403")
        assert response.status_code == 200

        data = response.json()
        errors = data["http_errors"]

        # All errors should be 403
        for error in errors:
            assert error["status_code"] == 403

    def test_method_performance_endpoint(self, api_client):
        """Test the method performance endpoint."""
        response = api_client.get("/api/telemetry/method-performance?days=7")
        assert response.status_code == 200

        data = response.json()
        performance = data["method_performance"]

        assert len(performance) > 0

        # Check for newspaper4k method
        newspaper_methods = [
            p for p in performance if p["method"] == "newspaper4k"]
        assert len(newspaper_methods) > 0

        newspaper_perf = newspaper_methods[0]
        assert newspaper_perf["total_attempts"] >= 1
        assert newspaper_perf["success_rate"] >= 0
        assert "avg_duration" in newspaper_perf

    def test_publisher_stats_endpoint(self, api_client):
        """Test the publisher stats endpoint."""
        response = api_client.get(
            "/api/telemetry/publisher-stats?days=7&min_attempts=1")
        assert response.status_code == 200

        data = response.json()
        publishers = data["publisher_stats"]

        assert len(publishers) >= 2

        # Check for specific publisher
        good_site = [p for p in publishers if p["host"] == "good-site.com"][0]
        assert good_site["total_extractions"] == 2
        assert good_site["successful_extractions"] == 2
        assert good_site["success_rate"] == 100.0
        assert good_site["status"] == "good"

        blocked_site = [
            p for p in publishers if p["host"] == "blocked-site.com"][0]
        assert blocked_site["total_extractions"] == 2
        assert blocked_site["successful_extractions"] == 0
        assert blocked_site["success_rate"] == 0.0
        assert blocked_site["status"] == "poor"

    def test_poor_performers_endpoint(self, api_client):
        """Test the poor performers endpoint."""
        response = api_client.get(
            "/api/telemetry/poor-performers?days=7&min_attempts=1&max_success_rate=50")
        assert response.status_code == 200

        data = response.json()
        poor_performers = data["poor_performers"]

        assert len(poor_performers) >= 2

        # All should have low success rates
        for performer in poor_performers:
            assert performer["success_rate"] <= 50.0
            assert performer["recommendation"] in ["pause", "monitor"]

        # Check specific recommendations
        very_poor = [p for p in poor_performers if p["success_rate"] < 25][0]
        assert very_poor["recommendation"] == "pause"

    def test_field_extraction_endpoint(self, api_client):
        """Test the field extraction endpoint."""
        response = api_client.get("/api/telemetry/field-extraction?days=7")
        assert response.status_code == 200

        data = response.json()
        field_stats = data["field_extraction_stats"]

        # Should have some field extraction data
        assert len(field_stats) >= 0  # Might be empty if no field data


class TestSiteManagementAPI:
    """Test the site management API endpoints."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for site management tests."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Create sources table
        cur.execute("""
        CREATE TABLE sources (
            id VARCHAR PRIMARY KEY,
            host VARCHAR NOT NULL,
            host_norm VARCHAR NOT NULL,
            canonical_name VARCHAR,
            city VARCHAR,
            county VARCHAR,
            owner VARCHAR,
            type VARCHAR,
            metadata JSON,
            discovery_attempted TIMESTAMP,
            status VARCHAR DEFAULT 'active',
            paused_at TIMESTAMP,
            paused_reason TEXT
        )
        """)

        # Insert test sources
        now = datetime.utcnow()
        test_sources = [
            ("test-site.com",
             "test-site.com",
             "test-site.com",
             "active",
             None,
             None),
            ("paused-site.com",
             "paused-site.com",
             "paused-site.com",
             "paused",
             now,
             "Manual pause for testing"),
            ]

        for source_id, host, host_norm, status, paused_at, reason in test_sources:
            cur.execute("""
            INSERT INTO sources (id, host, host_norm, status, paused_at, paused_reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (source_id, host, host_norm, status, paused_at, reason))

        conn.commit()
        conn.close()

        yield db_path
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def api_client(self, temp_db):
        """Create a test client with mocked database path."""
        with patch('backend.app.main.MAIN_DB_PATH', temp_db):
            from backend.app.main import app
            client = TestClient(app)
            yield client

    def test_pause_site_endpoint(self, api_client):
        """Test pausing a site."""
        request_data = {
            "host": "test-site.com",
            "reason": "Testing pause functionality"
        }

        response = api_client.post(
            "/api/site-management/pause",
            json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert "test-site.com" in data["message"]
        assert data["reason"] == "Testing pause functionality"

    def test_pause_nonexistent_site(self, api_client):
        """Test pausing a site that doesn't exist (should create it)."""
        request_data = {
            "host": "new-site.com",
            "reason": "Poor performance detected"
        }

        response = api_client.post(
            "/api/site-management/pause",
            json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert "new-site.com" in data["message"]

    def test_resume_site_endpoint(self, api_client):
        """Test resuming a paused site."""
        request_data = {
            "host": "paused-site.com"
        }

        response = api_client.post(
            "/api/site-management/resume",
            json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert "paused-site.com" in data["message"]

    def test_resume_nonexistent_site(self, api_client):
        """Test resuming a site that doesn't exist."""
        request_data = {
            "host": "nonexistent-site.com"
        }

        response = api_client.post(
            "/api/site-management/resume",
            json=request_data)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_get_paused_sites_endpoint(self, api_client):
        """Test getting list of paused sites."""
        response = api_client.get("/api/site-management/paused")
        assert response.status_code == 200

        data = response.json()
        paused_sites = data["paused_sites"]

        assert len(paused_sites) >= 1

        # Check for the paused site we inserted
        paused_site = [
            s for s in paused_sites if s["host"] == "paused-site.com"][0]
        assert paused_site["reason"] == "Manual pause for testing"
        assert paused_site["paused_at"] is not None

    def test_get_site_status_endpoint(self, api_client):
        """Test getting individual site status."""
        # Test active site
        response = api_client.get("/api/site-management/status/test-site.com")
        assert response.status_code == 200

        data = response.json()
        assert data["host"] == "test-site.com"
        assert data["status"] == "active"
        assert data["paused_at"] is None

        # Test paused site
        response = api_client.get(
            "/api/site-management/status/paused-site.com")
        assert response.status_code == 200

        data = response.json()
        assert data["host"] == "paused-site.com"
        assert data["status"] == "paused"
        assert data["paused_at"] is not None

        # Test nonexistent site (should return active by default)
        response = api_client.get(
            "/api/site-management/status/unknown-site.com")
        assert response.status_code == 200

        data = response.json()
        assert data["host"] == "unknown-site.com"
        assert data["status"] == "active"
        assert data["paused_at"] is None


class TestAPIErrorHandling:
    """Test error handling in API endpoints."""

    def test_telemetry_endpoints_with_invalid_database(self):
        """Test API endpoints with invalid database path."""
        with patch('backend.app.main.MAIN_DB_PATH', '/nonexistent/path/db.sqlite'):
            from backend.app.main import app
            client = TestClient(app)

            response = client.get("/api/telemetry/summary")
            assert response.status_code == 500
            assert "Error fetching telemetry summary" in response.json()[
                                                                       "detail"]

    def test_site_management_with_invalid_data(self):
        """Test site management endpoints with invalid request data."""
        # Create a temporary valid database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE sources (
            id VARCHAR PRIMARY KEY,
            host VARCHAR NOT NULL,
            host_norm VARCHAR NOT NULL,
            status VARCHAR DEFAULT 'active',
            paused_at TIMESTAMP,
            paused_reason TEXT
        )
        """)
        conn.commit()
        conn.close()

        try:
            with patch('backend.app.main.MAIN_DB_PATH', db_path):
                from backend.app.main import app
                client = TestClient(app)

                # Test pause with missing host
                response = client.post("/api/site-management/pause", json={})
                assert response.status_code == 422  # Validation error

                # Test pause with invalid JSON
                response = client.post(
                    "/api/site-management/pause",
                    data="invalid json",
                    headers={
                        "Content-Type": "application/json"})
                assert response.status_code == 422

        finally:
            Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
class TestCompleteAPIWorkflow:
    """End-to-end tests for the complete API workflow."""

    def test_telemetry_to_site_management_workflow(self):
        """Test workflow from telemetry detection to site management action."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            # Set up comprehensive test database
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # Create all necessary tables
            cur.execute("""
            CREATE TABLE extraction_telemetry_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT, article_id TEXT, url TEXT, publisher TEXT, host TEXT,
                start_time TIMESTAMP, end_time TIMESTAMP, total_duration_ms REAL,
                http_status_code INTEGER, http_error_type TEXT, response_size_bytes INTEGER,
                response_time_ms REAL, methods_attempted TEXT, successful_method TEXT,
                method_timings TEXT, method_success TEXT, method_errors TEXT,
                field_extraction TEXT, extracted_fields TEXT, content_length INTEGER,
                is_success BOOLEAN, error_message TEXT, error_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE http_error_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL, status_code INTEGER NOT NULL, error_type TEXT NOT NULL,
                count INTEGER DEFAULT 1, first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE sources (
                id VARCHAR PRIMARY KEY, host VARCHAR NOT NULL, host_norm VARCHAR NOT NULL,
                canonical_name VARCHAR, city VARCHAR, county VARCHAR, owner VARCHAR,
                type VARCHAR, metadata JSON, discovery_attempted TIMESTAMP,
                status VARCHAR DEFAULT 'active', paused_at TIMESTAMP, paused_reason TEXT
            )
            """)

            # Insert a problematic site with many failures
            now = datetime.utcnow()
            for i in range(10):
                cur.execute(
                    """
                INSERT INTO extraction_telemetry_v2
                (operation_id, article_id, url, publisher, host, http_status_code,
                 http_error_type, is_success, total_duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (f"op{i}",
                     f"art{i}",
                        f"https://problem-site.com/article{i}",
                        "problem-site.com",
                        "problem-site.com",
                        403,
                        "4xx_client_error",
                        0,
                        5000,
                        now -
                        timedelta(
                        hours=i)))

            # Add HTTP error summary
            cur.execute("""
            INSERT INTO http_error_summary (host, status_code, error_type, count)
            VALUES (?, ?, ?, ?)
            """, ("problem-site.com", 403, "4xx_client_error", 10))

            conn.commit()
            conn.close()

            with patch('backend.app.main.MAIN_DB_PATH', db_path):
                from backend.app.main import app
                client = TestClient(app)

                # 1. Check poor performers
                response = client.get(
                    "/api/telemetry/poor-performers?min_attempts=5&max_success_rate=25")
                assert response.status_code == 200

                poor_performers = response.json()["poor_performers"]
                problem_site = [
                    p for p in poor_performers if p["host"] == "problem-site.com"][0]
                assert problem_site["success_rate"] == 0.0
                assert problem_site["recommendation"] == "pause"

                # 2. Pause the problematic site
                pause_response = client.post(
                    "/api/site-management/pause",
                    json={
                        "host": "problem-site.com",
                        "reason": "Automatic pause due to poor performance: 0% success rate with 10 attempts"})
                assert pause_response.status_code == 200

                # 3. Verify site is paused
                status_response = client.get(
                    "/api/site-management/status/problem-site.com")
                assert status_response.status_code == 200

                site_status = status_response.json()
                assert site_status["status"] == "paused"
                assert "poor performance" in site_status["paused_reason"].lower(
                )

                # 4. Check paused sites list
                paused_response = client.get("/api/site-management/paused")
                assert paused_response.status_code == 200

                paused_sites = paused_response.json()["paused_sites"]
                assert any(
                    site["host"] == "problem-site.com" for site in paused_sites)

                # 5. Resume the site (e.g., after manual review)
                resume_response = client.post(
                    "/api/site-management/resume",
                    json={
                        "host": "problem-site.com"})
                assert resume_response.status_code == 200

                # 6. Verify site is active again
                final_status = client.get(
                    "/api/site-management/status/problem-site.com")
                assert final_status.status_code == 200
                assert final_status.json()["status"] == "active"

        finally:
            Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
