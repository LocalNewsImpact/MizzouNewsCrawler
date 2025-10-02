from __future__ import annotations

import argparse
from argparse import Namespace
from types import SimpleNamespace

import src.cli.commands.llm as llm


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    llm.add_llm_parser(subparsers)
    return parser


def test_add_llm_parser_registers_subcommands():
    parser = _build_parser()
    args = parser.parse_args(["llm", "run", "--limit", "5"])

    assert args.llm_command == "run"
    assert args.func is llm._handle_llm_run
    assert args.limit == 5


def test_handle_llm_command_requires_subcommand(capsys):
    exit_code = llm.handle_llm_command(Namespace(llm_command=None))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Please provide an LLM subcommand" in captured.out


def test_handle_llm_status_reports_configuration(monkeypatch, capsys):
    fake_settings = SimpleNamespace(
        provider_names=lambda: ["openai-gpt4.1", "claude-3.5-sonnet"],
        openai_api_key="openai-token",
        anthropic_api_key=None,
        google_api_key="",
        vector_store=SimpleNamespace(
            provider="pgvector",
            is_enabled=lambda: True,
        ),
    )
    monkeypatch.setattr(llm, "load_llm_settings", lambda: fake_settings)
    monkeypatch.setattr(
        llm.ProviderRegistry,
        "names",
        classmethod(lambda cls: ["openai-gpt4.1", "claude-3.5-sonnet"]),
    )

    exit_code = llm._handle_llm_status(Namespace())

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Provider order" in output
    assert "Vector store provider: pgvector" in output
    assert "OpenAI API key configured? yes" in output
    assert "Anthropic API key configured? no" in output


def test_handle_llm_run_executes_pipeline(monkeypatch):
    fake_settings = SimpleNamespace(
        provider_order=["openai-gpt4.1"],
        provider_names=lambda: ["openai-gpt4.1"],
        openai_api_key="token",
        anthropic_api_key=None,
        google_api_key=None,
        vector_store=None,
    )
    monkeypatch.setattr(llm, "load_llm_settings", lambda: fake_settings)

    factory_calls = []
    monkeypatch.setattr(
        llm.VectorStoreFactory,
        "create",
        classmethod(
            lambda cls, settings: factory_calls.append(settings) or None
        ),
    )

    orchestrators = []
    monkeypatch.setattr(
        llm.LLMOrchestrator,
        "from_settings",
        classmethod(
            lambda cls, settings, vector_store=None: orchestrators.append(
                (settings, vector_store)
            )
            or SimpleNamespace()
        ),
    )

    class FakeDB:
        def __init__(self):
            self.session = object()
            self.closed = False

        def close(self):
            self.closed = True

    db_instance = FakeDB()
    monkeypatch.setattr(llm, "DatabaseManager", lambda: db_instance)

    run_calls = []

    class FakePipeline:
        instances = []
        results = [
            llm.ArticleLLMResult(
                article_id="a1",
                success=True,
                provider="openai-gpt4.1",
                content="summary",
                failures=[],
            ),
            llm.ArticleLLMResult(
                article_id="a2",
                success=False,
                provider=None,
                content=None,
                failures=[{"provider": "openai-gpt4.1", "reason": "error"}],
            ),
        ]

        def __init__(self, session, orchestrator, *, prompt_template=None):
            self.session = session
            self.orchestrator = orchestrator
            self.prompt_template = prompt_template
            FakePipeline.instances.append(self)

        @staticmethod
        def load_prompt_template(path):
            return "PROMPT" if path else None

        def run(self, *, statuses=None, limit=None, dry_run=False):
            run_calls.append(
                {
                    "statuses": statuses,
                    "limit": limit,
                    "dry_run": dry_run,
                }
            )
            return list(self.results)

    monkeypatch.setattr(llm, "ArticleLLMPipeline", FakePipeline)

    printed = []
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **_k: printed.append(" ".join(str(a) for a in args)),
    )

    args = Namespace(
        statuses=["cleaned"],
        limit=3,
        dry_run=False,
        show_failures=True,
        prompt_template=None,
    )

    exit_code = llm._handle_llm_run(args)

    assert exit_code == 0
    assert db_instance.closed is True
    assert factory_calls == [fake_settings]
    assert orchestrators and orchestrators[0][0] is fake_settings
    assert run_calls == [
        {
            "statuses": ["cleaned"],
            "limit": 3,
            "dry_run": False,
        }
    ]
    assert any("Total articles evaluated: 2" in line for line in printed)
    assert any("Failures: 1" in line for line in printed)
    assert any("Summary sample" in line for line in printed)
