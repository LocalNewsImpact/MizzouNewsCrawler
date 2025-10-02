import logging
import sys
import types
from pathlib import Path

import pytest

import src.cli.context as context


class DummyLogger(logging.Logger):
    def __init__(self):
        super().__init__("dummy")
        self.info_messages = []
        self.warning_messages = []
        self.error_messages = []

    def info(self, msg, *args, **kwargs):
        self.info_messages.append(msg % args if args else msg)

    def warning(self, msg, *args, **kwargs):
        self.warning_messages.append(msg % args if args else msg)

    def error(self, msg, *args, **kwargs):
        self.error_messages.append(msg % args if args else msg)


@pytest.fixture
def tracker_spy():
    class FakeProcess:
        def __init__(self):
            self.id = "process-123"

    class Tracker:
        def __init__(self):
            self.register_kwargs = None
            self.update_calls = []
            self.complete_calls = []

        def register_process(self, **kwargs):
            self.register_kwargs = kwargs
            return FakeProcess()

        def update_progress(self, *args, **kwargs):
            self.update_calls.append((args, kwargs))

        def complete_process(self, *args, **kwargs):
            self.complete_calls.append((args, kwargs))

    tracker = Tracker()
    return tracker


def test_setup_logging_uses_expected_handlers(monkeypatch, tmp_path):
    captured = {}

    def fake_basic_config(**kwargs):
        captured.update(kwargs)

    stream_handler_calls = []
    file_handler_calls = []

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)
    monkeypatch.setattr(
        logging,
        "StreamHandler",
        lambda stream: stream_handler_calls.append(stream) or "stream-handler",
    )
    monkeypatch.setattr(
        logging,
        "FileHandler",
        lambda filename: file_handler_calls.append(filename) or "file-handler",
    )

    log_file = tmp_path / "test.log"

    context.setup_logging("debug", str(log_file))

    assert captured["level"] == logging.DEBUG
    assert captured["format"].startswith("%(asctime)")
    assert captured["handlers"] == ["stream-handler", "file-handler"]
    assert stream_handler_calls == [sys.stdout]
    assert file_handler_calls == [str(log_file)]


def test_trigger_gazetteer_population_success(monkeypatch, tracker_spy):
    monkeypatch.setattr(
        "src.utils.process_tracker.get_tracker", lambda: tracker_spy
    )

    fake_db_module = types.ModuleType("src.models.database")

    class FakeDatabaseManager:
        def __init__(self):
            self.engine = object()

    setattr(fake_db_module, "DatabaseManager", FakeDatabaseManager)
    monkeypatch.setitem(sys.modules, "src.models.database", fake_db_module)

    fake_models_module = types.ModuleType("src.models")

    class FakeDataset:
        slug = "slug"

        def __init__(self, id: int, name: str):
            self.id = id
            self.name = name

    setattr(fake_models_module, "Dataset", FakeDataset)
    monkeypatch.setitem(sys.modules, "src.models", fake_models_module)

    fake_sqlalchemy_module = types.ModuleType("sqlalchemy")

    def fake_select(model):  # noqa: ARG001 - mimic sqlalchemy.select
        class Selector:
            def where(self, condition):
                return (model, condition)

        return Selector()

    setattr(fake_sqlalchemy_module, "select", fake_select)
    monkeypatch.setitem(sys.modules, "sqlalchemy", fake_sqlalchemy_module)

    fake_sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")

    def fake_sessionmaker(*, bind):  # noqa: ARG001
        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN002
                return False

            def execute(self, query):  # noqa: ARG001
                class Result:
                    def scalar_one_or_none(self):
                        return types.SimpleNamespace(id=7, name="Sample")

                return Result()

        return FakeSession

    setattr(fake_sqlalchemy_orm, "sessionmaker", fake_sessionmaker)
    monkeypatch.setitem(sys.modules, "sqlalchemy.orm", fake_sqlalchemy_orm)

    popen_calls = {}

    class FakePopen:
        def __init__(self, cmd, cwd, stdout, stderr, text):
            popen_calls.update(
                {
                    "cmd": cmd,
                    "cwd": cwd,
                    "stdout": stdout,
                    "stderr": stderr,
                    "text": text,
                }
            )
            self.pid = 4242
            self.stdout = None
            self.stderr = None

    monkeypatch.setattr("subprocess.Popen", FakePopen)

    logger = DummyLogger()

    context.trigger_gazetteer_population_background("test-slug", logger)

    assert (
        tracker_spy.register_kwargs["process_type"]
        == "gazetteer_population"
    )
    assert "test-slug" in tracker_spy.register_kwargs["command"]
    assert tracker_spy.register_kwargs["metadata"]["dataset_id"] == "7"
    assert tracker_spy.register_kwargs["metadata"]["dataset_name"] == "Sample"

    assert tracker_spy.update_calls
    update_args, update_kwargs = tracker_spy.update_calls[0]
    assert update_args[0] == "process-123"
    assert "PID: 4242" in update_kwargs["message"]
    assert update_kwargs["status"] == "running"

    expected_cwd = Path(context.__file__).resolve().parent.parent
    assert popen_calls["cwd"] == expected_cwd
    assert popen_calls["cmd"][0] == sys.executable
    assert logger.error_messages == []
    assert tracker_spy.complete_calls == []
