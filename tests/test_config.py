import importlib
import sys
import types


def _mock_dotenv(monkeypatch):
    basic_dotenv = types.ModuleType("dotenv")
    setattr(basic_dotenv, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "dotenv", basic_dotenv)


def _import_fresh_config():
    sys.modules.pop("src.config", None)
    return importlib.import_module("src.config")


def test_get_config_reflects_environment(monkeypatch):
    _mock_dotenv(monkeypatch)

    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp.db")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TELEMETRY_URL", "https://telemetry.local")
    monkeypatch.setenv("OAUTH_PROVIDER", "auth0")
    monkeypatch.setenv("REQUEST_TIMEOUT", "45")
    monkeypatch.setenv("REQUEST_DELAY", "2.5")

    config = _import_fresh_config()

    assert config.DATABASE_URL == "sqlite:///tmp.db"
    assert config.LOG_LEVEL == "DEBUG"
    assert config.TELEMETRY_URL == "https://telemetry.local"
    assert config.REQUEST_TIMEOUT == 45
    assert config.REQUEST_DELAY == 2.5

    values = config.get_config()
    assert values["database_url"] == "sqlite:///tmp.db"
    assert values["log_level"] == "DEBUG"
    assert values["telemetry_url"] == "https://telemetry.local"
    assert values["oauth_provider"] == "auth0"

    llm_defaults = values["llm"]
    assert llm_defaults == {
        "provider_sequence": None,
        "request_timeout": 30,
        "max_retries": 2,
        "default_max_output_tokens": 1024,
        "default_temperature": 0.2,
        "api_keys": {
            "openai": False,
            "anthropic": False,
            "google": False,
        },
    }

    vector_store_defaults = values["vector_store"]
    assert vector_store_defaults == {
        "provider": None,
        "namespace": None,
        "pinecone_configured": False,
        "weaviate_configured": False,
    }


def test_config_loads_dotenv_when_available(monkeypatch, tmp_path):
    spy = {}

    dotenv_module = types.ModuleType("dotenv")

    def fake_load_dotenv(*, dotenv_path):
        spy["called"] = True
        spy["path"] = dotenv_path
        monkeypatch.setenv("DATABASE_URL", "sqlite:///from_env_file.db")

    setattr(dotenv_module, "load_dotenv", fake_load_dotenv)
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_module)

    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=sqlite:///from_env_file.db")

    config = _import_fresh_config()

    assert spy["called"] is True
    assert spy["path"].endswith(".env")
    assert config.DATABASE_URL == "sqlite:///from_env_file.db"


def test_config_builds_database_url_from_components(monkeypatch):
    _mock_dotenv(monkeypatch)

    for key in [
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_SSLMODE",
        "DATABASE_REQUIRE_SSL",
    ]:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("DATABASE_ENGINE", "postgresql+psycopg2")
    monkeypatch.setenv("DATABASE_HOST", "db.internal")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_NAME", "crawler")
    monkeypatch.setenv("DATABASE_USER", "crawler-user")
    monkeypatch.setenv("DATABASE_PASSWORD", "p@ss word")
    monkeypatch.setenv("DATABASE_SSLMODE", "prefer")

    config = _import_fresh_config()

    expected_url = (
        "postgresql+psycopg2://crawler-user:p%40ss+word@db.internal:5432/"
        "crawler?sslmode=prefer"
    )

    assert config.DATABASE_URL == expected_url

    db_config = config.get_config()["database"]
    assert db_config == {
        "engine": "postgresql+psycopg2",
        "host": "db.internal",
        "port": "5432",
        "name": "crawler",
        "user": "crawler-user",
        "sslmode": "prefer",
    }


def test_config_normalizes_telemetry_settings(monkeypatch):
    _mock_dotenv(monkeypatch)

    for key in [
        "TELEMETRY_URL",
        "TELEMETRY_HOST",
        "TELEMETRY_PORT",
        "TELEMETRY_BASE_PATH",
        "TELEMETRY_SCHEME",
        "TELEMETRY_USE_TLS",
    ]:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("TELEMETRY_HOST", "telemetry.svc")
    monkeypatch.setenv("TELEMETRY_PORT", "9000")
    monkeypatch.setenv("TELEMETRY_BASE_PATH", "metrics")
    monkeypatch.setenv("TELEMETRY_USE_TLS", "yes")
    monkeypatch.setenv("TELEMETRY_SCHEME", "HTTPS://")

    config = _import_fresh_config()

    assert config.TELEMETRY_SCHEME == "https"
    assert config.TELEMETRY_BASE_PATH == "/metrics"
    assert config.TELEMETRY_URL == "https://telemetry.svc:9000/metrics"

    telemetry_config = config.get_config()["services"]["telemetry"]
    assert telemetry_config == {
        "host": "telemetry.svc",
        "port": "9000",
        "scheme": "https",
        "base_path": "/metrics",
        "url": "https://telemetry.svc:9000/metrics",
    }

    monkeypatch.setenv("TELEMETRY_BASE_PATH", "   ")
    monkeypatch.setenv("TELEMETRY_SCHEME", "")
    monkeypatch.setenv("TELEMETRY_USE_TLS", "0")
    monkeypatch.delenv("TELEMETRY_URL", raising=False)

    config_without_path = _import_fresh_config()

    assert config_without_path.TELEMETRY_SCHEME == "http"
    assert config_without_path.TELEMETRY_BASE_PATH == ""
    telemetry_config_no_path = config_without_path.get_config()["services"][
        "telemetry"
    ]
    assert telemetry_config_no_path == {
        "host": "telemetry.svc",
        "port": "9000",
        "scheme": "http",
        "base_path": None,
        "url": "http://telemetry.svc:9000",
    }
