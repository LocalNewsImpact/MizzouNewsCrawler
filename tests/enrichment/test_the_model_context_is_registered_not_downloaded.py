"""The model's context window is registered with litellm, not downloaded.

backfield sizes every prompt from `litellm.get_model_info`, and litellm builds
that table from a JSON file it downloads from GitHub on import. The file
dropped `openrouter/deepseek/deepseek-v3.2` after 2026-10-05; backfield then
assumed 8,000 tokens, and the places prompt -- about 7,300 tokens before any
article -- failed for every article in the 2026-10-15 WSU run, from an image
unchanged since September.
"""

from __future__ import annotations

import sys
import types

import pytest

from src.cli.commands.enrichment import DEFAULT_MODEL
from src.enrichment import adapter
from src.enrichment.cost import RATES


@pytest.fixture
def litellm_stub(monkeypatch):
    stub = types.ModuleType("litellm")
    stub.success_callback = []
    stub.registered = []
    stub.register_model = stub.registered.append
    monkeypatch.setitem(sys.modules, "litellm", stub)
    monkeypatch.setattr(adapter, "_MODELS_REGISTERED", False)
    return stub


def test_the_default_model_has_a_registered_window():
    assert DEFAULT_MODEL in adapter.MODEL_CONTEXT
    assert adapter.MODEL_CONTEXT[DEFAULT_MODEL]["max_input_tokens"] >= 100_000


def test_registration_gives_litellm_the_window_and_the_rates(litellm_stub):
    adapter._register_model_context()
    (entries,) = litellm_stub.registered
    entry = entries[DEFAULT_MODEL]
    assert entry["max_input_tokens"] == 163_840
    assert entry["litellm_provider"] == "openrouter"
    assert entry["mode"] == "chat"
    assert entry["input_cost_per_token"] == float(RATES[DEFAULT_MODEL]["in"])


def test_it_registers_once_per_process(litellm_stub):
    adapter._register_model_context()
    adapter._register_model_context()
    assert len(litellm_stub.registered) == 1


def test_every_node_step_registers_before_it_runs(litellm_stub, monkeypatch):
    monkeypatch.setattr(adapter, "_register_usage_callback", lambda: None)
    monkeypatch.setattr(adapter, "_load", lambda node: lambda params, inputs: {})
    adapter._run_node("places", "place_extract", {}, {}, DEFAULT_MODEL)
    assert len(litellm_stub.registered) == 1


def test_without_litellm_nothing_is_attempted(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    monkeypatch.setattr(adapter, "_MODELS_REGISTERED", False)
    adapter._register_model_context()  # does not raise
    assert adapter._MODELS_REGISTERED is False
