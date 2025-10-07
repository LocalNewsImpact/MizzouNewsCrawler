"""FastAPI lifecycle management for shared resources.

This module centralizes startup and shutdown handling for:
- TelemetryStore (with background writer thread management)
- DatabaseManager (connection pool/engine)
- HTTP Session (with optional origin proxy adapter)
- Other long-lived resources

This ensures proper resource initialization and cleanup, and makes
dependency injection straightforward for route handlers and tests.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import requests
from fastapi import FastAPI, Request
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from src.models.database import DatabaseManager
    from src.telemetry.store import TelemetryStore

logger = logging.getLogger(__name__)


def setup_lifecycle_handlers(app: FastAPI) -> None:
    """Register startup and shutdown handlers for the FastAPI app.
    
    This function should be called once during app initialization.
    It registers handlers that:
    - Create and attach shared resources to app.state on startup
    - Clean up resources gracefully on shutdown
    
    Args:
        app: The FastAPI application instance
    """
    
    @app.on_event("startup")
    async def startup_resources():
        """Initialize shared resources and attach to app.state."""
        logger.info("Starting resource initialization...")
        
        # 1. Initialize TelemetryStore
        try:
            from src.telemetry.store import TelemetryStore
            from src import config as app_config
            
            # Determine if async writes should be enabled
            # Default to True for production, can be overridden via env
            async_writes = os.getenv("TELEMETRY_ASYNC_WRITES", "true").lower() in (
                "true", "1", "yes"
            )
            
            telemetry_store = TelemetryStore(
                database=app_config.DATABASE_URL,
                async_writes=async_writes,
                timeout=30.0,
                thread_name="TelemetryStoreWriter",
            )
            app.state.telemetry_store = telemetry_store
            logger.info(
                f"TelemetryStore initialized (async_writes={async_writes})"
            )
        except Exception as exc:
            logger.exception("Failed to initialize TelemetryStore", exc_info=exc)
            # Continue without telemetry rather than failing startup
            app.state.telemetry_store = None
        
        # 2. Initialize DatabaseManager
        try:
            from src.models.database import DatabaseManager
            from src import config as app_config
            
            db_manager = DatabaseManager(app_config.DATABASE_URL)
            app.state.db_manager = db_manager
            logger.info(
                f"DatabaseManager initialized: {app_config.DATABASE_URL[:50]}..."
            )
        except Exception as exc:
            logger.exception("Failed to initialize DatabaseManager", exc_info=exc)
            # Allow startup to continue; endpoints will fail if DB is needed
            app.state.db_manager = None
        
        # 3. Initialize shared HTTP session with optional origin proxy
        try:
            session = requests.Session()
            
            # Install origin proxy adapter if enabled
            use_origin_proxy = os.getenv("USE_ORIGIN_PROXY", "").lower() in (
                "1", "true", "yes"
            )
            
            if use_origin_proxy:
                from src.crawler.origin_proxy import enable_origin_proxy
                
                enable_origin_proxy(session)
                logger.info("Origin proxy adapter installed on shared session")
            
            app.state.http_session = session
            logger.info("HTTP session initialized")
        except Exception as exc:
            logger.exception("Failed to initialize HTTP session", exc_info=exc)
            app.state.http_session = None
        
        # 4. Set ready flag
        app.state.ready = True
        logger.info("All resources initialized, app is ready")
    
    @app.on_event("shutdown")
    async def shutdown_resources():
        """Clean up shared resources gracefully."""
        logger.info("Starting resource cleanup...")
        
        # 1. Shutdown TelemetryStore (flush pending writes, stop worker thread)
        if hasattr(app.state, "telemetry_store") and app.state.telemetry_store:
            try:
                logger.info("Shutting down TelemetryStore...")
                app.state.telemetry_store.shutdown(wait=True)
                logger.info("TelemetryStore shutdown complete")
            except Exception as exc:
                logger.exception("Error shutting down TelemetryStore", exc_info=exc)
        
        # 2. Dispose DatabaseManager engine/connection pool
        if hasattr(app.state, "db_manager") and app.state.db_manager:
            try:
                logger.info("Disposing DatabaseManager engine...")
                app.state.db_manager.engine.dispose()
                logger.info("DatabaseManager engine disposed")
            except Exception as exc:
                logger.exception("Error disposing DatabaseManager", exc_info=exc)
        
        # 3. Close HTTP session
        if hasattr(app.state, "http_session") and app.state.http_session:
            try:
                logger.info("Closing HTTP session...")
                app.state.http_session.close()
                logger.info("HTTP session closed")
            except Exception as exc:
                logger.exception("Error closing HTTP session", exc_info=exc)
        
        # 4. Clear ready flag
        if hasattr(app.state, "ready"):
            app.state.ready = False
        
        logger.info("Resource cleanup complete")


# Dependency injection functions for route handlers


def get_telemetry_store(request: Request) -> TelemetryStore | None:
    """Dependency that provides the shared TelemetryStore.
    
    Usage in route handlers:
        @app.get("/some-route")
        def handler(store: TelemetryStore | None = Depends(get_telemetry_store)):
            if store:
                store.submit(...)
    
    Returns None if telemetry is unavailable (startup failed or not initialized).
    Tests can override this dependency to inject a test store.
    """
    return getattr(request.app.state, "telemetry_store", None)


def get_db_manager(request: Request) -> DatabaseManager | None:
    """Dependency that provides the shared DatabaseManager.
    
    Usage in route handlers:
        @app.get("/some-route")
        def handler(db: DatabaseManager | None = Depends(get_db_manager)):
            if not db:
                raise HTTPException(500, "Database unavailable")
            with db.get_session() as session:
                ...
    
    Returns None if database is unavailable.
    Tests can override this dependency to inject a test DB manager.
    """
    return getattr(request.app.state, "db_manager", None)


def get_http_session(request: Request) -> requests.Session | None:
    """Dependency that provides the shared HTTP session.
    
    The session may have the origin proxy adapter installed if
    USE_ORIGIN_PROXY was enabled at startup.
    
    Usage in route handlers:
        @app.get("/some-route")
        def handler(session: requests.Session | None = Depends(get_http_session)):
            if session:
                response = session.get("https://example.com")
    
    Returns None if HTTP session is unavailable.
    Tests can override this dependency to inject a mock session.
    """
    return getattr(request.app.state, "http_session", None)


def is_ready(request: Request) -> bool:
    """Check if the application is ready to serve traffic.
    
    Returns True if startup completed successfully and resources are available.
    Used by health/readiness endpoints.
    """
    return getattr(request.app.state, "ready", False)


def check_db_health(db_manager: DatabaseManager | None) -> tuple[bool, str]:
    """Perform a lightweight database health check.
    
    Args:
        db_manager: The DatabaseManager instance to check, or None
    
    Returns:
        Tuple of (is_healthy, message)
    """
    if db_manager is None:
        return False, "DatabaseManager not initialized"
    
    try:
        # Perform a simple query to verify connection
        with db_manager.get_session() as session:
            session.execute("SELECT 1")
        return True, "Database connection OK"
    except OperationalError as exc:
        return False, f"Database connection failed: {exc}"
    except Exception as exc:
        return False, f"Database health check error: {exc}"
