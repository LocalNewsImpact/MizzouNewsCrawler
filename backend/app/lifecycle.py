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
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional, Protocol, cast

import requests
from sqlalchemy import text
from fastapi import FastAPI, Request
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from src.models.database import DatabaseManager as _DatabaseManagerProtocol
    from src.telemetry.store import TelemetryStore as _TelemetryStoreProtocol

    TelemetryStoreProtocol = _TelemetryStoreProtocol
    DatabaseManagerProtocol = _DatabaseManagerProtocol
else:  # pragma: no cover - runtime fallback for optional imports
    class TelemetryStoreProtocol(Protocol):  # pragma: no cover - type shunt
        def shutdown(self, wait: bool = True) -> None: ...

    class DatabaseManagerProtocol(Protocol):  # pragma: no cover - type shunt
        engine: Any

        def get_session(self) -> Any: ...

logger = logging.getLogger(__name__)


# Expose enable_origin_proxy at module level so tests can patch it.
EnableOriginProxyCallable = Callable[[requests.Session], None]

try:  # pragma: no cover - best-effort import
    from src.crawler.origin_proxy import enable_origin_proxy as _enable_origin_proxy

    enable_origin_proxy: Optional[EnableOriginProxyCallable] = cast(
        EnableOriginProxyCallable, _enable_origin_proxy
    )
except Exception:
    enable_origin_proxy = None


# Expose TelemetryStore and DatabaseManager module symbols so tests can
# patch them. If the imports fail, set to None (startup will attempt
# to import locally as well).
TelemetryStore: Optional[type[TelemetryStoreProtocol]]
try:  # pragma: no cover - best-effort import
    from src.telemetry.store import TelemetryStore as _TelemetryStore
except Exception:
    TelemetryStore = None
else:
    TelemetryStore = _TelemetryStore

DatabaseManager: Optional[type[DatabaseManagerProtocol]]
try:  # pragma: no cover - best-effort import
    from src.models.database import DatabaseManager as _DatabaseManager
except Exception:
    DatabaseManager = None
else:
    DatabaseManager = _DatabaseManager


async def startup_resources(app: FastAPI) -> None:
    """Initialize shared resources for the FastAPI app.
    
    This function can be called from a lifespan context manager or directly.
    
    Args:
        app: The FastAPI application instance
    """
    logger.info("Starting resource initialization...")

    # 1. Initialize TelemetryStore (unless already provided by tests)
    try:
        if (
            not hasattr(app.state, "telemetry_store")
            or getattr(app.state, "telemetry_store") is None
        ):
            from src.telemetry.store import TelemetryStore
            from src import config as app_config

            # Determine if async writes should be enabled
            # Default to True for production, can be overridden via env
            async_writes = os.getenv("TELEMETRY_ASYNC_WRITES", "true").lower() in (
                "true",
                "1",
                "yes",
            )

            telemetry_store: TelemetryStoreProtocol = TelemetryStore(
                database=app_config.DATABASE_URL,
                async_writes=async_writes,
                timeout=30.0,
                thread_name="TelemetryStoreWriter",
            )
            app.state.telemetry_store = telemetry_store
            logger.info(f"TelemetryStore initialized (async_writes={async_writes})")
        else:
            logger.info(
                "TelemetryStore already provided on app.state; skipping init"
            )
    except Exception as exc:
        logger.exception("Failed to initialize TelemetryStore", exc_info=exc)
        # Continue without telemetry rather than failing startup
        app.state.telemetry_store = None

    # 2. Initialize DatabaseManager (unless already provided by tests)
    try:
        if (
            not hasattr(app.state, "db_manager")
            or getattr(app.state, "db_manager") is None
        ):
            from src.models.database import DatabaseManager
            from src import config as app_config

            db_manager = DatabaseManager(app_config.DATABASE_URL)
            app.state.db_manager = db_manager
            logger.info(
                f"DatabaseManager initialized: {app_config.DATABASE_URL[:50]}..."
            )
        else:
            logger.info(
                "DatabaseManager already provided on app.state; skipping init"
            )
    except Exception as exc:
        logger.exception("Failed to initialize DatabaseManager", exc_info=exc)
        # Allow startup to continue; endpoints will fail if DB is needed
        app.state.db_manager = None

    # 3. Initialize shared HTTP session with optional origin proxy
    try:
        # Only create an HTTP session if not already provided by tests
        if (
            not hasattr(app.state, "http_session")
            or getattr(app.state, "http_session") is None
        ):
            session = requests.Session()

            # Install origin proxy adapter if enabled
            use_origin_proxy = os.getenv("USE_ORIGIN_PROXY", "").lower() in (
                "1",
                "true",
                "yes",
            )

            if use_origin_proxy:
                try:
                    # Prefer the module-level symbol which tests can patch.
                    if enable_origin_proxy:
                        enable_origin_proxy(session)
                    else:
                        # Fall back to importing the implementation
                        from src.crawler.origin_proxy import (
                            enable_origin_proxy as _enable_origin_proxy,
                        )

                        _enable_origin_proxy(session)

                    logger.info("Origin proxy adapter installed on shared session")
                except Exception as exc:
                    logger.exception(
                        "Failed to install origin proxy adapter", exc_info=exc
                    )

            app.state.http_session = session
            logger.info("HTTP session initialized")
        else:
            logger.info("HTTP session already provided on app.state; skipping init")
    except Exception as exc:
        logger.exception("Failed to initialize HTTP session", exc_info=exc)
        app.state.http_session = None

    # 4. Set ready flag
    app.state.ready = True
    logger.info("All resources initialized, app is ready")


async def shutdown_resources(app: FastAPI) -> None:
    """Clean up shared resources gracefully.
    
    This function can be called from a lifespan context manager or directly.
    
    Args:
        app: The FastAPI application instance
    """
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for FastAPI app lifecycle.

    This replaces the deprecated @app.on_event("startup") and @app.on_event("shutdown")
    decorators with the modern lifespan pattern.

    Resources are initialized on startup (before yield) and cleaned up on
    shutdown (after yield).

    Args:
        app: The FastAPI application instance

    Yields:
        None
    """
    await startup_resources(app)
    yield
    await shutdown_resources(app)


# Dependency injection functions for route handlers


def get_telemetry_store(request: Request) -> TelemetryStoreProtocol | None:
    """Dependency that provides the shared TelemetryStore.

    Usage in route handlers:
        @app.get("/some-route")
        def handler(
            store: TelemetryStoreProtocol | None = Depends(get_telemetry_store),
        ):
            if store:
                store.submit(...)

    Returns None if telemetry is unavailable (startup failed or not initialized).
    Tests can override this dependency to inject a test store.
    """
    return cast(
        Optional[TelemetryStoreProtocol],
        getattr(request.app.state, "telemetry_store", None),
    )


def get_db_manager(request: Request) -> DatabaseManagerProtocol | None:
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
    return cast(
        Optional[DatabaseManagerProtocol],
        getattr(request.app.state, "db_manager", None),
    )


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


def check_db_health(db_manager: DatabaseManagerProtocol | None) -> tuple[bool, str]:
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
            session.execute(text("SELECT 1"))
        return True, "Database connection OK"
    except OperationalError as exc:
        return False, f"Database connection failed: {exc}"
    except Exception as exc:
        return False, f"Database health check error: {exc}"
