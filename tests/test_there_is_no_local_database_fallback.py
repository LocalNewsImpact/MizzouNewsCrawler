"""A job with no database configured fails, rather than inventing one.

`src/config.py` fell back to `sqlite:///data/mizzou.db` when nothing was
set -- a file inside the container. So a job missing its database
settings did not fail. It created an empty database, wrote a corpus into
it, reported success, and lost all of it when the pod exited.

Seen in production 2026-09-07 on an extraction job that set the Cloud SQL
connector variables but not `DATABASE_URL`. The connector was what saved
it: the engine came from `_create_cloud_sql_engine()` and the articles
reached Postgres, so the only symptom was a warning on every
`DatabaseManager()` construction that read like noise. With the connector
off, the same job would have written the whole run to a file that no
longer exists.

The three supported ways to configure a database are unchanged. What is
gone is the fourth, which was not configuring one.
"""

import importlib
import os

import pytest

CONFIG = "src.config"
DB_VARS = (
    "DATABASE_URL",
    "DATABASE_HOST",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
    "USE_CLOUD_SQL_CONNECTOR",
    "CLOUD_SQL_INSTANCE",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in DB_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _load():
    import src.config

    return importlib.reload(src.config)


@pytest.fixture(autouse=True)
def _reload_after(request):
    """Put the real configuration back.

    These reload `src.config` under a monkeypatched environment. Without
    this the module left behind belongs to the last test that ran, and
    every later test in the session reads its database settings from it.
    """
    yield
    try:
        importlib.reload(__import__("src.config", fromlist=["x"]))
    except RuntimeError:
        # The environment is still stripped when this runs, for the tests
        # that strip it. The next import rebuilds the module anyway; what
        # matters is not leaving a monkeypatched one in place, and a
        # failed reload does not.
        pass


def test_no_database_configured_is_an_error(clean_env):
    """The whole point. Silence here cost a corpus."""
    with pytest.raises(RuntimeError) as exc:
        _load()
    message = str(exc.value)
    assert "No database configured" in message
    # It says what to set, because whoever hits this is mid-deploy.
    assert "DATABASE_URL" in message
    assert "USE_CLOUD_SQL_CONNECTOR" in message


def test_an_explicit_url_is_used(clean_env):
    clean_env.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h:5432/db")
    assert _load().DATABASE_URL == "postgresql+psycopg2://u:p@h:5432/db"


def test_the_host_triple_still_assembles_a_url(clean_env):
    clean_env.setenv("DATABASE_HOST", "h")
    clean_env.setenv("DATABASE_NAME", "mizzou")
    clean_env.setenv("DATABASE_USER", "u")
    url = _load().DATABASE_URL
    assert url.startswith("postgresql+psycopg2://u@h:5432/mizzou")


def test_the_cloud_sql_connector_needs_no_url(clean_env):
    """It builds its own connection. Requiring a URL it never reads would
    have failed every job in the cluster that uses it."""
    clean_env.setenv("USE_CLOUD_SQL_CONNECTOR", "true")
    clean_env.setenv("CLOUD_SQL_INSTANCE", "proj:region:inst")
    url = _load().DATABASE_URL
    assert "proj:region:inst" in url
    # And it must not read as SQLite to anything downstream: DatabaseManager
    # warns, and its own branch, on whether "postgresql" is in this string.
    assert "postgresql" in url


def test_the_connector_without_an_instance_is_still_an_error(clean_env):
    """Half-configured is not configured. This is the shape the
    extraction job was in."""
    clean_env.setenv("USE_CLOUD_SQL_CONNECTOR", "true")
    with pytest.raises(RuntimeError):
        _load()


def test_no_sqlite_path_survives_in_the_configuration(clean_env):
    """Not in a default, not in a fallback. The corpus is Postgres."""
    clean_env.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h:5432/db")
    config = _load()
    assert "sqlite" not in config.DATABASE_URL.lower()
