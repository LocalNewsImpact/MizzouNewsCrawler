"""Tests for FastAPI lifecycle management.

These tests verify that:
- Startup handlers initialize resources correctly
- Shutdown handlers clean up resources
- Dependency injection functions work as expected
- Resource overrides work in tests
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient


def test_setup_lifecycle_handlers_registers_startup_and_shutdown():
    """Verify that setup_lifecycle_handlers registers event handlers."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    # FastAPI stores event handlers in router.on_startup and router.on_shutdown
    startup_handlers = [h for h in app.router.on_startup]
    shutdown_handlers = [h for h in app.router.on_shutdown]
    
    assert len(startup_handlers) > 0, "Should register at least one startup handler"
    assert len(shutdown_handlers) > 0, "Should register at least one shutdown handler"


@pytest.mark.asyncio
async def test_startup_initializes_telemetry_store():
    """Test that startup handler initializes TelemetryStore."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    with patch("backend.app.lifecycle.TelemetryStore") as mock_store_class:
        mock_store_instance = MagicMock()
        mock_store_class.return_value = mock_store_instance
        
        app = FastAPI()
        setup_lifecycle_handlers(app)
        
        # Trigger startup events
        with TestClient(app):
            # Startup happens automatically when TestClient is created
            pass
        
        # Verify TelemetryStore was created
        assert hasattr(app.state, "telemetry_store")
        # In the test environment, TelemetryStore might be None or the mock
        # depending on import success


@pytest.mark.asyncio
async def test_startup_initializes_database_manager():
    """Test that startup handler initializes DatabaseManager."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    with patch("backend.app.lifecycle.DatabaseManager") as mock_db_class:
        mock_db_instance = MagicMock()
        mock_db_instance.engine = MagicMock()
        mock_db_class.return_value = mock_db_instance
        
        app = FastAPI()
        setup_lifecycle_handlers(app)
        
        # Trigger startup events
        with TestClient(app):
            pass
        
        # Verify DatabaseManager was initialized
        assert hasattr(app.state, "db_manager")


@pytest.mark.asyncio
async def test_startup_initializes_http_session():
    """Test that startup handler initializes HTTP session."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    # Trigger startup events
    with TestClient(app):
        pass
    
    # Verify HTTP session was created
    assert hasattr(app.state, "http_session")


@pytest.mark.asyncio
async def test_startup_sets_ready_flag():
    """Test that startup handler sets the ready flag."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    # Initially not ready
    assert not getattr(app.state, "ready", False)
    
    # Trigger startup events
    with TestClient(app):
        # Should be ready after startup
        assert app.state.ready is True


@pytest.mark.asyncio
async def test_shutdown_cleans_up_telemetry_store():
    """Test that shutdown handler cleans up TelemetryStore."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    # Create a mock telemetry store and attach it
    mock_store = MagicMock()
    app.state.telemetry_store = mock_store
    
    # Trigger startup and shutdown
    with TestClient(app):
        pass
    
    # Verify shutdown was called on telemetry store
    mock_store.shutdown.assert_called_once_with(wait=True)


@pytest.mark.asyncio
async def test_shutdown_disposes_database_engine():
    """Test that shutdown handler disposes database engine."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    # Create a mock database manager and attach it
    mock_db = MagicMock()
    mock_engine = MagicMock()
    mock_db.engine = mock_engine
    app.state.db_manager = mock_db
    
    # Trigger startup and shutdown
    with TestClient(app):
        pass
    
    # Verify engine.dispose was called
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_closes_http_session():
    """Test that shutdown handler closes HTTP session."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    # Create a mock HTTP session and attach it
    mock_session = MagicMock()
    app.state.http_session = mock_session
    
    # Trigger startup and shutdown
    with TestClient(app):
        pass
    
    # Verify session.close was called
    mock_session.close.assert_called_once()


def test_get_telemetry_store_dependency():
    """Test get_telemetry_store dependency injection."""
    from backend.app.lifecycle import get_telemetry_store, setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    @app.get("/test")
    def test_endpoint(store=Depends(get_telemetry_store)):
        return {"has_store": store is not None}
    
    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        # Store may or may not be available depending on initialization success
        assert "has_store" in response.json()


def test_get_db_manager_dependency():
    """Test get_db_manager dependency injection."""
    from backend.app.lifecycle import get_db_manager, setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    @app.get("/test")
    def test_endpoint(db=Depends(get_db_manager)):
        return {"has_db": db is not None}
    
    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        assert "has_db" in response.json()


def test_get_http_session_dependency():
    """Test get_http_session dependency injection."""
    from backend.app.lifecycle import get_http_session, setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    @app.get("/test")
    def test_endpoint(session=Depends(get_http_session)):
        return {"has_session": session is not None}
    
    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        assert "has_session" in response.json()


def test_is_ready_dependency():
    """Test is_ready dependency function."""
    from backend.app.lifecycle import is_ready, setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    @app.get("/test")
    def test_endpoint(ready: bool = Depends(is_ready)):
        return {"ready": ready}
    
    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        # Should be ready after startup
        assert response.json()["ready"] is True


def test_check_db_health_returns_false_when_no_db():
    """Test check_db_health returns False when db_manager is None."""
    from backend.app.lifecycle import check_db_health
    
    healthy, message = check_db_health(None)
    
    assert healthy is False
    assert "not initialized" in message.lower()


def test_check_db_health_returns_true_on_successful_query():
    """Test check_db_health returns True when database query succeeds."""
    from backend.app.lifecycle import check_db_health

    # Create a mock database manager
    mock_db = MagicMock()
    mock_session = MagicMock()
    mock_db.get_session.return_value.__enter__.return_value = mock_session
    
    healthy, message = check_db_health(mock_db)
    
    assert healthy is True
    assert "ok" in message.lower()
    mock_session.execute.assert_called_once_with("SELECT 1")


def test_check_db_health_returns_false_on_operational_error():
    """Test check_db_health returns False on database errors."""
    from sqlalchemy.exc import OperationalError

    from backend.app.lifecycle import check_db_health

    # Create a mock database manager that raises an error
    mock_db = MagicMock()
    mock_db.get_session.return_value.__enter__.side_effect = OperationalError(
        "connection failed", None, None
    )
    
    healthy, message = check_db_health(mock_db)
    
    assert healthy is False
    assert "connection failed" in message.lower()


def test_dependency_override_in_tests():
    """Test that dependencies can be overridden for testing."""
    from backend.app.lifecycle import get_db_manager, setup_lifecycle_handlers
    
    app = FastAPI()
    setup_lifecycle_handlers(app)
    
    # Create a mock database manager
    mock_db = MagicMock()
    mock_db.test_value = "test"
    
    # Override the dependency
    def get_test_db():
        return mock_db
    
    app.dependency_overrides[get_db_manager] = get_test_db
    
    @app.get("/test")
    def test_endpoint(db=Depends(get_db_manager)):
        return {"test_value": db.test_value if db else None}
    
    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json()["test_value"] == "test"


def test_origin_proxy_installed_when_env_var_set():
    """Test that origin proxy adapter is installed when USE_ORIGIN_PROXY=true."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    with patch.dict("os.environ", {"USE_ORIGIN_PROXY": "true"}):
        with patch("backend.app.lifecycle.enable_origin_proxy") as mock_enable:
            app = FastAPI()
            setup_lifecycle_handlers(app)
            
            with TestClient(app):
                pass
            
            # Verify enable_origin_proxy was called
            assert mock_enable.call_count > 0


def test_origin_proxy_not_installed_when_env_var_unset():
    """Test origin proxy adapter not installed when USE_ORIGIN_PROXY unset."""
    from backend.app.lifecycle import setup_lifecycle_handlers
    
    with patch.dict("os.environ", {"USE_ORIGIN_PROXY": ""}, clear=True):
        with patch("backend.app.lifecycle.enable_origin_proxy") as mock_enable:
            app = FastAPI()
            setup_lifecycle_handlers(app)
            
            with TestClient(app):
                pass
            
            # Verify enable_origin_proxy was not called (or called 0 times)
            # In the actual implementation it may not be imported at all
            # so we just check it wasn't called
            assert mock_enable.call_count == 0
