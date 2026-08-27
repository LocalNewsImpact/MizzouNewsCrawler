"""Unit tests for the enrichment adapter. No network, no backfield install.

Backfield nodes are reached only through adapter._load, which these tests patch,
so the suite runs in the crawler venv where backfield is not installed.
"""

from __future__ import annotations

import re
import sys
import types as _types
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from src.enrichment import adapter
from src.enrichment.cost import call_cost
from src.enrichment.types import ArticleInput


@pytest.fixture
def litellm_stub(monkeypatch):
    """A fake litellm module: the crawler venv deliberately lacks the real one."""
    stub = _types.ModuleType("litellm")
    stub.success_callback = []
    stub.completion = None  # tests assign per-case
    monkeypatch.setitem(sys.modules, "litellm", stub)
    return stub


ARTICLE = ArticleInput(
    id="a1",
    title="City council approves budget",
    content="The council voted 5-2 on Tuesday to approve the budget. " * 40,
    dataset_slug="Mizzou-Missouri-State",
    publication_city="Columbia",
)
MODEL = "openrouter/deepseek/deepseek-v3.2"
SRC = Path(__file__).parent.parent.parent / "src"


class TestImportBoundary:
    """adapter.py is the only module permitted to import backfield (§1)."""

    BACKFIELD_IMPORT = re.compile(
        r"^\s*(from|import)\s+(agate_runtime|agate_nodes|agate_utils|backfield_\w+)",
        re.M,
    )

    def test_only_adapter_imports_backfield(self):
        offenders = []
        for path in SRC.rglob("*.py"):
            if path.name == "adapter.py" and path.parent.name == "enrichment":
                continue
            if self.BACKFIELD_IMPORT.search(path.read_text(errors="ignore")):
                offenders.append(str(path))
        assert offenders == [], f"backfield imported outside the adapter: {offenders}"

    def test_adapter_defers_the_import(self):
        # Importing the adapter itself must not require backfield: the import
        # happens inside _load, at call time.
        source = (SRC / "enrichment" / "adapter.py").read_text()
        head = source.split("def _load", 1)[0]
        assert not self.BACKFIELD_IMPORT.search(
            head
        ), "backfield must be imported lazily inside _load, not at module top"


class TestNodeFailureHandling:
    """A model failure is a StepResult, never an exception (§2)."""

    def test_node_exception_becomes_ok_false(self):
        with patch.object(adapter, "_load", side_effect=RuntimeError("boom")):
            result = adapter.run_scope(ARTICLE, MODEL)
        assert result.ok is False
        assert result.step == "scope"
        assert "RuntimeError: boom" in result.error
        assert result.cost_usd == Decimal("0")

    def test_node_raising_inside_becomes_ok_false(self):
        def bad_runner(params, inputs):
            raise TimeoutError("upstream timeout")

        with patch.object(adapter, "_load", return_value=bad_runner):
            result = adapter.run_places(ARTICLE, MODEL)
        assert result.ok is False
        assert "TimeoutError" in result.error

    def test_non_dict_payload_becomes_ok_false(self):
        with patch.object(adapter, "_load", return_value=lambda p, i: "not a dict"):
            result = adapter.run_people(ARTICLE, MODEL)
        assert result.ok is False
        assert "expected dict" in result.error

    def test_success_payload_passes_through(self):
        payload = {"text": "x", "locations": []}
        with patch.object(adapter, "_load", return_value=lambda p, i: payload):
            result = adapter.run_places(ARTICLE, MODEL)
        assert result.ok is True
        assert result.payload == payload
        assert result.error is None

    def test_preset_step_is_named_after_the_preset(self):
        with patch.object(adapter, "_load", return_value=lambda p, i: {}):
            result = adapter.run_preset(ARTICLE, "subject", MODEL)
        assert result.step == "subject"

    def test_params_carry_model_and_preset(self):
        seen = {}

        def capture(params, inputs):
            seen.update(params)
            return {}

        with patch.object(adapter, "_load", return_value=capture):
            adapter.run_preset(ARTICLE, "topic", MODEL)
        assert seen["model"] == MODEL
        assert seen["prompt_preset"] == "topic"
        assert seen["meta_type"] == "topic"


class TestContentGate:
    """The gate parses strictly and fails closed (§5.6)."""

    def _fake_response(self, content: str, tokens=(500, 20)):
        class Usage:
            prompt_tokens, completion_tokens = tokens

        class Message:
            pass

        class Choice:
            pass

        class Response:
            pass

        message = Message()
        message.content = content
        choice = Choice()
        choice.message = message
        response = Response()
        response.choices = [choice]
        response.usage = Usage()
        return response

    def test_the_call_says_which_dataset_paid_for_it(self, litellm_stub):
        """LiteLLM forwards `user` to OpenRouter, which records it as
        `external_user` on the generation. Without it a trace says only
        that money was spent: every trace collected up to 2026-08-22 has
        `external_user` null, so the cost page can split the recorded side
        per dataset and not the billed one."""
        response = self._fake_response('{"verdict": "news", "reason": "x"}')
        seen = {}

        def capture(**kw):
            seen.update(kw)
            return response

        litellm_stub.completion = capture
        adapter.run_content_gate(ARTICLE, MODEL)
        assert seen["user"] == "Mizzou-Missouri-State"

    def test_valid_verdict_passes(self, litellm_stub):
        response = self._fake_response('{"verdict": "news", "reason": "story present"}')
        litellm_stub.completion = lambda **kw: response
        result = adapter.run_content_gate(ARTICLE, MODEL)
        assert result.ok is True
        assert result.payload["verdict"] == "news"
        assert result.input_tokens == 500
        assert result.cost_usd == call_cost(MODEL, 500, 20)

    def test_fenced_json_is_tolerated(self, litellm_stub):
        response = self._fake_response(
            '```json\n{"verdict": "not_news", "reason": "x"}\n```'
        )
        litellm_stub.completion = lambda **kw: response
        result = adapter.run_content_gate(ARTICLE, MODEL)
        assert result.ok is True
        assert result.payload["verdict"] == "not_news"

    def test_malformed_json_fails_closed(self, litellm_stub):
        response = self._fake_response("The article looks like news to me.")
        litellm_stub.completion = lambda **kw: response
        result = adapter.run_content_gate(ARTICLE, MODEL)
        assert result.ok is False

    def test_unknown_verdict_fails_closed(self, litellm_stub):
        response = self._fake_response('{"verdict": "maybe", "reason": "?"}')
        litellm_stub.completion = lambda **kw: response
        result = adapter.run_content_gate(ARTICLE, MODEL)
        assert result.ok is False
        assert "maybe" in result.error

    def test_transport_error_fails_closed(self, litellm_stub):
        def down(**kw):
            raise ConnectionError("down")

        litellm_stub.completion = down
        result = adapter.run_content_gate(ARTICLE, MODEL)
        assert result.ok is False
        assert "ConnectionError" in result.error

    def test_windows_are_head_and_middle(self, litellm_stub):
        captured = {}

        def capture(**kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"]
            return self._fake_response('{"verdict": "news", "reason": "y"}')

        litellm_stub.completion = capture
        body = "HEADTEXT " * 200 + "MIDDLETEXT " * 200
        article = ArticleInput("a2", "T", body, "ds", None)
        adapter.run_content_gate(article, MODEL)
        assert "START:" in captured["prompt"] and "MIDDLE:" in captured["prompt"]
        assert "HEADTEXT" in captured["prompt"].split("MIDDLE:")[0]
        assert "MIDDLETEXT" in captured["prompt"].split("MIDDLE:")[1]


# --- the gate's verdict is countable and its reason is not -------------------


def test_the_gate_answers_from_a_fixed_set():
    """Three verdicts, validated. That is the field a dashboard can group
    by, and it was the one being discarded."""
    from src.enrichment.adapter import _VALID_VERDICTS

    assert _VALID_VERDICTS == {"news", "paywall", "not_news"}


def test_the_verdict_is_written_and_not_only_the_prose():
    """15,747 enrichment rows carry 6,280 distinct reasons, because a model
    wrote each one. Nothing could ask how many articles a publisher lost to
    a paywall -- a question the gate answered every single time."""
    from pathlib import Path

    repo = (
        Path(__file__).resolve().parents[2] / "src/enrichment/repository.py"
    ).read_text()
    assert '"content_gate_verdict": gate.get("verdict")' in repo
    # Present in all three halves of the upsert, or a re-enrichment keeps
    # the first verdict for ever.
    assert repo.count("content_gate_verdict") >= 4


def test_the_column_exists_in_a_migration():
    from pathlib import Path

    versions = Path(__file__).resolve().parents[2] / "alembic/versions"
    added = [
        f
        for f in versions.glob("*.py")
        if "content_gate_verdict" in f.read_text() and "add_column" in f.read_text()
    ]
    assert added, "the column is written to and never created"
