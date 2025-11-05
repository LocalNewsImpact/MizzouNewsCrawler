"""Tests for FastAPI lifecycle management.

These tests verify that:
- Startup handlers initialize resources correctly
- Shutdown handlers clean up resources
- Dependency injection functions work as expected
- Resource overrides work in tests
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


@pytest.mark.postgres
@pytest.mark.integration
def test_lifespan_context_manager_registers_correctly():
    """Verify that lifespan context manager is available."""
    from backend.app.lifecycle import lifespan

    app = FastAPI(lifespan=lifespan)
    assert app.router.lifespan_context is not None


@pytest.mark.asyncio
async def test_startup_initializes_telemetry_store():
    """Test that startup handler initializes TelemetryStore."""
    from backend.app.lifecycle import shutdown_resources, startup_resources

    with patch("backend.app.lifecycle.TelemetryStore") as mock_store_class:
        mock_store_instance = MagicMock()
        mock_store_class.return_value = mock_store_instance

        app = FastAPI()
        await startup_resources(app)
        assert hasattr(app.state, "telemetry_store")
        await shutdown_resources(app)


@pytest.mark.asyncio
async def test_startup_initializes_database_manager():
    """Test that startup handler initializes DatabaseManager."""
    from backend.app.lifecycle import shutdown_resources, startup_resources

    with patch("backend.app.lifecycle.DatabaseManager") as mock_db_class:
        mock_db_instance = MagicMock()
        mock_db_instance.engine = MagicMock()
        mock_db_class.return_value = mock_db_instance

        app = FastAPI()
        await startup_resources(app)
        assert hasattr(app.state, "db_manager")
        await shutdown_resources(app)


@pytest.mark.asyncio
async def test_startup_initializes_http_session():
    """Test that startup handler initializes HTTP session."""
    from backend.app.lifecycle import lifespan

    app = FastAPI(lifespan=lifespan)
    with TestClient(app):
        assert hasattr(app.state, "http_session")


@pytest.mark.asyncio
async def test_startup_sets_ready_flag():
    """Test that startup handler sets the ready flag."""
    from backend.app.lifecycle import lifespan

    app = FastAPI(lifespan=lifespan)
    with TestClient(app):
        assert app.state.ready is True


@pytest.mark.asyncio
async def test_shutdown_cleans_up_telemetry_store():
    """Test that shutdown handler cleans up TelemetryStore."""
    from backend.app.lifecycle import shutdown_resources, startup_resources

    app = FastAPI()
    await startup_resources(app)
    mock_store = MagicMock()
    app.state.telemetry_store = mock_store
    await shutdown_resources(app)
    mock_store.shutdown.assert_called_once_with(wait=True)


@pytest.mark.asyncio
async def test_shutdown_disposes_database_engine():
    """Test that shutdown handler disposes database engine."""
    from backend.app.lifecycle import shutdown_resources, startup_resources

    app = FastAPI()
    await startup_resources(app)
    mock_db = MagicMock()
    mock_engine = MagicMock()
    mock_db.engine = mock_engine
    app.state.db_manager = mock_db
    await shutdown_resources(app)
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_closes_http_session():
    """Test that shutdown handler closes HTTP session."""
    from backend.app.lifecycle import shutdown_resources, startup_resources

    app = FastAPI()
    await startup_resources(app)
    mock_session = MagicMock()
    app.state.http_session = mock_session
    await shutdown_resources(app)
    mock_session.close.assert_called_once()


@pytest.mark.postgres
@pytest.mark.integration
def test_get_telemetry_store_dependency():
    """Test get_telemetry_store dependency injection."""
    from backend.app.lifecycle import get_telemetry_store, lifespan

    app = FastAPI(lifespan=lifespan)

    @app.get("/test")
    def test_endpoint(store=Depends(get_telemetry_store)):
        return {"has_store": store is not None}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        assert "has_store" in response.json()


@pytest.mark.postgres
@pytest.mark.integration
def test_get_db_manager_dependency():
    """Test get_db_manager dependency injection."""
    from backend.app.lifecycle import get_db_manager, lifespan

    app = FastAPI(lifespan=lifespan)

    @app.get("/test")
    def test_endpoint(db=Depends(get_db_manager)):
        return {"has_db": db is not None}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        assert "has_db" in response.json()


@pytest.mark.postgres
@pytest.mark.integration
def test_get_http_session_dependency():
    """Test get_http_session dependency injection."""
    from backend.app.lifecycle import get_http_session, lifespan

    app = FastAPI(lifespan=lifespan)

    @app.get("/test")
    def test_endpoint(session=Depends(get_http_session)):
        return {"has_session": session is not None}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        assert "has_session" in response.json()


@pytest.mark.postgres
@pytest.mark.integration
def test_is_ready_dependency():
    """Test is_ready dependency function."""
    from backend.app.lifecycle import is_ready, lifespan

    app = FastAPI(lifespan=lifespan)

    @app.get("/test")
    def test_endpoint(ready: bool = Depends(is_ready)):
        return {"ready": ready}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json()["ready"] is True


@pytest.mark.postgres
@pytest.mark.integration
def test_check_db_health_returns_false_when_no_db():
    """Test check_db_health returns False when db_manager is None."""
    from backend.app.lifecycle import check_db_health

    healthy, message = check_db_health(None)
    assert healthy is False
    assert "not initialized" in message.lower()


@pytest.mark.postgres
@pytest.mark.integration
def test_check_db_health_returns_true_on_successful_query():
    """Test check_db_health returns True when database query succeeds."""
    from backend.app.lifecycle import check_db_health

    mock_db = MagicMock()
    mock_session = MagicMock()
    mock_db.get_session.return_value.__enter__.return_value = mock_session

    healthy, message = check_db_health(mock_db)
    assert healthy is True
    assert "ok" in message.lower()
    mock_session.execute.assert_called_once()


@pytest.mark.postgres
@pytest.mark.integration
def test_check_db_health_returns_false_on_operational_error():
    """Test check_db_health returns False on database errors."""
    from sqlalchemy.exc import OperationalError

    from backend.app.lifecycle import check_db_health

    mock_db = MagicMock()
    mock_db.get_session.return_value.__enter__.side_effect = OperationalError(
        "connection failed", None, None
    )

    healthy, message = check_db_health(mock_db)
    assert healthy is False
    assert "connection failed" in message.lower()


@pytest.mark.postgres
@pytest.mark.integration
def test_dependency_override_in_tests():
    """Test that dependencies can be overridden for testing."""
    from backend.app.lifecycle import get_db_manager, lifespan

    app = FastAPI(lifespan=lifespan)
    mock_db = MagicMock()
    mock_db.test_value = "test"

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


@pytest.mark.postgres
@pytest.mark.integration
def test_origin_proxy_installed_when_env_var_set():
    """Test origin proxy installed when USE_ORIGIN_PROXY=true."""
    from backend.app.lifecycle import lifespan

    with patch.dict("os.environ", {"USE_ORIGIN_PROXY": "true"}):
        with patch("backend.app.lifecycle.enable_origin_proxy") as mock_enable:
            app = FastAPI(lifespan=lifespan)
            with TestClient(app):
                pass
            assert mock_enable.call_count > 0


@pytest.mark.postgres
@pytest.mark.integration
def test_origin_proxy_not_installed_when_env_var_unset():
    """Test origin proxy not installed when USE_ORIGIN_PROXY unset."""
    from backend.app.lifecycle import lifespan

    with patch.dict("os.environ", {"USE_ORIGIN_PROXY": ""}, clear=True):
        with patch("backend.app.lifecycle.enable_origin_proxy") as mock_enable:
            app = FastAPI(lifespan=lifespan)
            with TestClient(app):
                pass
            assert mock_enable.call_count == 0
