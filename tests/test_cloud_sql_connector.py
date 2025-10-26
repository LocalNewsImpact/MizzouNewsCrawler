import sys
import types
from unittest.mock import Mock

import pytest
from sqlalchemy.pool import NullPool

from src.models import cloud_sql_connector


@pytest.fixture(autouse=True)
def reset_global_connector(monkeypatch):
    monkeypatch.setattr(cloud_sql_connector, "_GLOBAL_CONNECTOR", None)


@pytest.fixture()
def stub_connector(monkeypatch):
    connector_instance = Mock()
    connector_instance.connect.return_value = object()

    connector_cls = Mock(return_value=connector_instance)

    connector_module = types.ModuleType("google.cloud.sql.connector")
    connector_module.Connector = connector_cls

    sql_module = types.ModuleType("google.cloud.sql")
    sql_module.__path__ = []
    sql_module.connector = connector_module

    cloud_module = types.ModuleType("google.cloud")
    cloud_module.__path__ = []
    cloud_module.sql = sql_module

    google_module = types.ModuleType("google")
    google_module.__path__ = []
    google_module.cloud = cloud_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.sql", sql_module)
    monkeypatch.setitem(sys.modules, "google.cloud.sql.connector", connector_module)

    return connector_cls, connector_instance


def test_create_engine_strips_pool_kwargs_when_poolclass(monkeypatch, stub_connector):
    connector_cls, _ = stub_connector
    captured_kwargs: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs):
        captured_kwargs.update(kwargs)
        return "engine"

    monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)

    engine = cloud_sql_connector.create_cloud_sql_engine(
        instance_connection_name="project:region:instance",
        user="dbuser",
        password="dbpass",
        database="db",
        poolclass=NullPool,
    )

    assert engine == "engine"
    assert captured_kwargs["poolclass"] is NullPool
    assert "pool_size" not in captured_kwargs
    assert "max_overflow" not in captured_kwargs
    assert "pool_pre_ping" not in captured_kwargs

    connector_cls.assert_called_once()
    creator = captured_kwargs["creator"]
    assert callable(creator)
    assert creator() is not None


def test_create_engine_sets_defaults_without_poolclass(monkeypatch, stub_connector):
    connector_cls, connector_instance = stub_connector
    captured_kwargs: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs):
        captured_kwargs.update(kwargs)
        return "engine"

    monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)

    engine = cloud_sql_connector.create_cloud_sql_engine(
        instance_connection_name="project:region:instance",
        user="dbuser",
        password="dbpass",
        database="db",
    )

    assert engine == "engine"
    assert captured_kwargs["pool_size"] == 5
    assert captured_kwargs["max_overflow"] == 10
    assert captured_kwargs["pool_pre_ping"] is True
    assert captured_kwargs["pool_recycle"] == 3600
    assert "poolclass" not in captured_kwargs

    connector_cls.assert_called_once()
    creator = captured_kwargs["creator"]
    assert creator() is connector_instance.connect.return_value
