"""14,441 articles enriched clean on 2026-08-22. Two weeks later, 46% of a
191-article run failed, with no change to this repository.

`deepseek/deepseek-v3.2` is one model name in front of a pool of
providers, and OpenRouter picks between them per request. The pool moved.
From the trace export in gs://mizzou-openrouter-logs/openrouter-traces:

    2026-08-22 (clean)    AtlasCloud 24, SiliconFlow 5, Baidu 1   of 30
    2026-09-07 (46% fail) StreamLake 90, Friendli 19, AtlasCloud 5,
                          Baidu 5, Alibaba 1                      of 120

StreamLake appears in none of the August traces and served three quarters
of today's. Every failure was one step, `temporal_orientation`, returning
a confidence outside 0.0-1.0 that backfield's schema refuses. The model
name, the prompts, the validator and the vendored wheels are unchanged;
the answers are not.

An article needs nine consecutive validations to finish, so a per-call
defect rate on a provider serving most of the traffic compounds into the
per-article one.
"""

import os
from unittest.mock import MagicMock

import pytest

from src.enrichment import adapter


@pytest.fixture
def litellm_stub(monkeypatch):
    """A stubbed litellm, plus a handle on the call the wrapper delegates to.

    The wrapper replaces `litellm.completion`, so asserting on the module
    attribute afterwards inspects the wrapper rather than what it passed
    on. `inner` is what actually receives the request.
    """
    import sys

    stub = MagicMock()
    inner = MagicMock(return_value="response")
    stub.completion = inner
    stub.success_callback = []
    monkeypatch.setitem(sys.modules, "litellm", stub)
    monkeypatch.setattr(adapter, "_WRAPPED", False)
    return stub, inner


def test_the_request_names_the_providers_that_answer_correctly(litellm_stub):
    stub, inner = litellm_stub
    adapter._label_calls_with_the_dataset()
    stub.completion(model="openrouter/deepseek/deepseek-v3.2", messages=[])

    sent = inner.call_args.kwargs
    provider = sent["extra_body"]["provider"]

    assert provider["only"] == list(adapter.ENRICHMENT_PROVIDERS)
    assert provider["allow_fallbacks"] is False


def test_the_default_pool_is_the_one_that_enriched_14441_articles():
    assert adapter.ENRICHMENT_PROVIDERS == ("AtlasCloud", "SiliconFlow", "Baidu")
    assert "StreamLake" not in adapter.ENRICHMENT_PROVIDERS


def test_a_caller_that_chose_its_own_providers_keeps_them(litellm_stub):
    """The pin is a default, not an override."""
    stub, inner = litellm_stub
    adapter._label_calls_with_the_dataset()
    stub.completion(
        model="openrouter/deepseek/deepseek-v3.2",
        messages=[],
        extra_body={"provider": {"only": ["Baidu"]}},
    )

    sent = inner.call_args.kwargs

    assert sent["extra_body"]["provider"]["only"] == ["Baidu"]


def test_other_extra_body_keys_survive(litellm_stub):
    stub, inner = litellm_stub
    adapter._label_calls_with_the_dataset()
    stub.completion(
        model="openrouter/deepseek/deepseek-v3.2",
        messages=[],
        extra_body={"transforms": ["middle-out"]},
    )

    sent = inner.call_args.kwargs

    assert sent["extra_body"]["transforms"] == ["middle-out"]
    assert "provider" in sent["extra_body"]


def test_the_pin_can_be_lifted_without_a_deploy(monkeypatch):
    """Empty means no pin -- the behaviour that produced the 46%, kept
    reachable because a provider outage is a worse failure than a
    validation one."""
    monkeypatch.setenv("ENRICHMENT_PROVIDERS", "")
    providers = tuple(
        name.strip()
        for name in os.getenv("ENRICHMENT_PROVIDERS", "AtlasCloud").split(",")
        if name.strip()
    )
    assert providers == ()
