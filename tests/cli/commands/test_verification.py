from __future__ import annotations

from argparse import Namespace
from typing import Any

import src.cli.commands.verification as verification


def _default_args(**overrides) -> Namespace:
    defaults = dict(
        batch_size=100,
        sleep_interval=30,
        max_batches=None,
        log_level="INFO",
        status=False,
        continuous=False,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def test_handle_verification_status_mode(monkeypatch, capsys):
    monkeypatch.setattr(verification.logging, "basicConfig", lambda **_: None)

    summary = {
        "total_urls": 120,
        "verification_pending": 5,
        "articles_verified": 90,
        "non_articles_verified": 15,
        "verification_failures": 10,
        "status_breakdown": {
            "pending": 5,
            "verified": 105,
            "failed": 10,
        },
    }

    instances: list[Any] = []

    class FakeService:
        def __init__(self, *, batch_size: int, sleep_interval: int) -> None:
            self.init_args = (batch_size, sleep_interval)
            instances.append(self)

        def get_status_summary(self):
            return summary

    monkeypatch.setattr(verification, "URLVerificationService", FakeService)

    args = _default_args(status=True, batch_size=50, sleep_interval=15)

    exit_code = verification.handle_verification_command(args)

    assert exit_code == 0
    assert instances[0].init_args == (50, 15)

    stdout = capsys.readouterr().out
    assert "URL Verification Status:" in stdout
    assert "Total URLs: 120" in stdout
    assert "pending: 5" in stdout


def test_handle_verification_runs_service(monkeypatch):
    monkeypatch.setattr(verification.logging, "basicConfig", lambda **_: None)

    run_calls: list[int | None] = []

    class FakeService:
        def __init__(self, *, batch_size: int, sleep_interval: int) -> None:
            self.batch_size = batch_size
            self.sleep_interval = sleep_interval

        def run_verification_loop(self, *, max_batches: int | None) -> None:
            run_calls.append(max_batches)

    monkeypatch.setattr(verification, "URLVerificationService", FakeService)

    args = _default_args(max_batches=3)

    exit_code = verification.handle_verification_command(args)

    assert exit_code == 0
    assert run_calls == [3]


def test_handle_verification_returns_error_on_failure(monkeypatch):
    monkeypatch.setattr(verification.logging, "basicConfig", lambda **_: None)

    def broken_service(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(verification, "URLVerificationService", broken_service)

    args = _default_args()

    exit_code = verification.handle_verification_command(args)

    assert exit_code == 1


def test_show_verification_status_handles_exception(monkeypatch):
    class BrokenService:
        def get_status_summary(self):
            raise RuntimeError("bad status")

    monkeypatch.setattr(
        verification.logging,
        "error",
        lambda *args, **kwargs: None,
    )

    broken_service = BrokenService()  # type: Any

    exit_code = verification.show_verification_status(broken_service)

    assert exit_code == 1


def test_run_verification_service_handles_keyboard_interrupt(monkeypatch):
    class InterruptService:
        def run_verification_loop(self, *, max_batches: int | None) -> None:
            raise KeyboardInterrupt()

    monkeypatch.setattr(
        verification.logging,
        "info",
        lambda *args, **kwargs: None,
    )

    interrupt_service = InterruptService()  # type: Any

    exit_code = verification.run_verification_service(
        interrupt_service,
        max_batches=None,
    )

    assert exit_code == 0


def test_run_verification_service_handles_runtime_error(monkeypatch):
    errors: list[str] = []

    class BrokenService:
        def run_verification_loop(self, *, max_batches: int | None) -> None:
            raise RuntimeError("nope")

    monkeypatch.setattr(
        verification.logging,
        "info",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        verification.logging,
        "error",
        lambda message, *args, **kwargs: errors.append(message),
    )

    broken_service = BrokenService()  # type: Any

    exit_code = verification.run_verification_service(
        broken_service,
        max_batches=2,
    )

    assert exit_code == 1
    assert any("failed" in msg for msg in errors)


def test_handle_verification_returns_error_when_run_loop_fails(monkeypatch):
    monkeypatch.setattr(verification.logging, "basicConfig", lambda **_: None)

    errors: list[str] = []

    class FailingService:
        def __init__(self, *, batch_size: int, sleep_interval: int) -> None:
            self.batch_size = batch_size
            self.sleep_interval = sleep_interval

        def run_verification_loop(self, *, max_batches: int | None) -> None:
            raise RuntimeError("loop exploded")

    monkeypatch.setattr(
        verification,
        "URLVerificationService",
        FailingService,
    )

    monkeypatch.setattr(
        verification.logging,
        "error",
        lambda message, *args, **kwargs: errors.append(message),
    )

    args = _default_args(max_batches=1)

    exit_code = verification.handle_verification_command(args)

    assert exit_code == 1
    assert any("Verification service failed" in msg for msg in errors)
