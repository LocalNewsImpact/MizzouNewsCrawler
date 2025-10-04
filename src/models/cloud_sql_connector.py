"""Cloud SQL Python Connector for direct database connections.

This module provides connection factories that use the Cloud SQL Python Connector
library to connect directly to Cloud SQL instances without requiring a proxy sidecar.

Benefits over proxy sidecar:
- Jobs complete automatically when main container exits
- Reduces cluster resource consumption (~89-445Mi memory, ~75-125m CPU per pod)
- Simpler Kubernetes configuration
- Production-grade architecture (Google-recommended)
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_cloud_sql_engine(
    instance_connection_name: str,
    user: str,
    password: str,
    database: str,
    driver: str = "pg8000",
    **engine_kwargs: Any,
):
    """Create a SQLAlchemy engine using Cloud SQL Python Connector.

    Args:
        instance_connection_name: Cloud SQL instance in format "project:region:instance"
        user: Database user
        password: Database password
        database: Database name
        driver: Database driver ('pg8000' recommended for connector)
        **engine_kwargs: Additional arguments passed to create_engine

    Returns:
        SQLAlchemy Engine configured with Cloud SQL connector

    Example:
        >>> engine = create_cloud_sql_engine(
        ...     instance_connection_name="my-project:us-central1:my-instance",
        ...     user="db_user",
        ...     password="db_pass",
        ...     database="my_db"
        ... )
    """
    try:
        from google.cloud.sql.connector import Connector
        from sqlalchemy import create_engine
        from sqlalchemy.engine import Engine
    except ImportError as e:
        logger.error(
            "Cloud SQL connector dependencies not installed. "
            "Install with: pip install cloud-sql-python-connector[pg8000]"
        )
        raise ImportError(
            "cloud-sql-python-connector is required. "
            "Install with: pip install cloud-sql-python-connector[pg8000]"
        ) from e

    logger.info(
        f"Creating Cloud SQL engine for instance: {instance_connection_name}"
    )

    # Initialize Cloud SQL Python Connector
    connector = Connector()

    def getconn():
        """Create a database connection using the Cloud SQL Python Connector."""
        conn = connector.connect(
            instance_connection_name,
            driver,
            user=user,
            password=password,
            db=database,
        )
        return conn

    # Create SQLAlchemy engine with the connector
    engine: Engine = create_engine(
        f"postgresql+{driver}://",
        creator=getconn,
        **engine_kwargs,
    )

    logger.info("Cloud SQL engine created successfully")
    return engine


def get_connection_string_info(database_url: str) -> dict[str, str | None]:
    """Parse a database URL to extract connection components.

    Args:
        database_url: Database connection string

    Returns:
        Dictionary with keys: engine, user, password, host, port, database

    Example:
        >>> info = get_connection_string_info(
        ...     "postgresql://user:pass@localhost:5432/mydb"
        ... )
        >>> info['user']
        'user'
    """
    from urllib.parse import urlparse

    parsed = urlparse(database_url)

    return {
        "engine": parsed.scheme,
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": str(parsed.port) if parsed.port else None,
        "database": parsed.path.lstrip("/") if parsed.path else None,
    }
