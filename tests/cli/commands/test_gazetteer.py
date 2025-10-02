import argparse
import types
from uuid import uuid4

import pytest

from src.cli.commands import gazetteer


@pytest.fixture(autouse=True)
def _reset_process_context(monkeypatch):
    instances = []

    class FakeProcessContext:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            instances.append(self)
            return types.SimpleNamespace(id="proc-1")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(gazetteer, "ProcessContext", FakeProcessContext)
    yield instances


def test_handle_gazetteer_command_missing_script(monkeypatch, capsys):
    monkeypatch.setattr(gazetteer, "run_gazetteer_population", None)

    result = gazetteer.handle_gazetteer_command(argparse.Namespace())

    assert result == 1
    captured = capsys.readouterr().out
    assert "populate_gazetteer script not available" in captured


def test_handle_gazetteer_command_success(monkeypatch, capsys, _reset_process_context):
    called = {}

    class FakeDB:
        def __init__(self):
            self.engine = types.SimpleNamespace(url="sqlite:///fake.db")

    def fake_population(**kwargs):
        called["kwargs"] = kwargs

    monkeypatch.setattr(gazetteer, "DatabaseManager", lambda: FakeDB())
    monkeypatch.setattr(gazetteer, "run_gazetteer_population", fake_population)

    args = argparse.Namespace(
        dataset=None,
        address=None,
        radius=None,
        dry_run=False,
        publisher=None,
    )

    result = gazetteer.handle_gazetteer_command(args)

    assert result == 0
    assert called["kwargs"] == {
        "database_url": "sqlite:///fake.db",
        "dataset_slug": None,
        "address": None,
        "radius_miles": None,
        "dry_run": False,
        "publisher": None,
    }

    ctx = _reset_process_context[0]
    assert "process_type" in ctx.kwargs
    assert "command" in ctx.kwargs
    assert ctx.kwargs["metadata"]["database_url"] == "sqlite:///fake.db"
    captured = capsys.readouterr()
    assert "Gazetteer population completed successfully" in captured.out


def test_handle_gazetteer_command_with_dataset_and_options(
    monkeypatch, _reset_process_context
):
    dataset_obj = types.SimpleNamespace(
        id=uuid4(), name="Local Publishers", slug="local"
    )

    class FakeResult:
        def scalar_one_or_none(self):
            return dataset_obj

    class FakeSession:
        def __init__(self):
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt):
            self.executed.append(stmt)
            return FakeResult()

    def fake_sessionmaker(bind=None):
        def factory():
            return FakeSession()

        return factory

    class FakeDB:
        def __init__(self):
            self.engine = types.SimpleNamespace(url="sqlite:///fixture.db")

    called = {}

    def fake_population(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(gazetteer, "DatabaseManager", lambda: FakeDB())
    monkeypatch.setattr("sqlalchemy.orm.sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(gazetteer, "run_gazetteer_population", fake_population)

    args = argparse.Namespace(
        dataset="local",
        address="123 Main St",
        radius=15.5,
        dry_run=True,
        publisher="publisher-123",
    )

    result = gazetteer.handle_gazetteer_command(args)

    assert result == 0

    # Ensure the CLI forwards all options to the worker script
    assert called == {
        "database_url": "sqlite:///fixture.db",
        "dataset_slug": "local",
        "address": "123 Main St",
        "radius_miles": 15.5,
        "dry_run": True,
        "publisher": "publisher-123",
    }

    ctx = _reset_process_context[0]
    metadata = ctx.kwargs["metadata"]
    assert metadata["dataset_slug"] == "local"
    assert metadata["dataset_id"] == str(dataset_obj.id)
    assert metadata["dataset_name"] == dataset_obj.name
    assert metadata["publisher_uuid"] == "publisher-123"
    assert metadata["test_address"] == "123 Main St"
    assert metadata["radius_miles"] == 15.5
    assert metadata["dry_run"] is True
    assert metadata["processing_mode"] == "test_address"

    # The dataset_id is attached to ProcessContext for telemetry correlation
    assert ctx.kwargs["dataset_id"] == str(dataset_obj.id)
    assert ctx.kwargs["source_id"] == "publisher-123"
    command = ctx.kwargs["command"]
    assert "populate-gazetteer" in command
    assert "--dataset local" in command
    assert "--address 123 Main St" in command
    assert "--radius 15.5" in command
    assert "--dry-run" in command
    assert "--publisher publisher-123" in command
